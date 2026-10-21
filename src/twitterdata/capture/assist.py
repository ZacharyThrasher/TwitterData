"""Local helper for hand captures: queue page plus a save endpoint.

The browser extension in `capture-extension/` only listens. It never opens,
scrolls or clicks anything on X. It copies the TweetDetail responses that the
browser already received and posts them here, to 127.0.0.1. This module:

* serves a queue page listing the captures that are due, with links to open;
* matches each posted thread view to its tracker capture id
  (`{root_tweet_id}_h{01|06|24}_{sort}_{viewer}`) by focal tweet, sort and
  time;
* writes a token-free bundle (request URL reduced to its `variables`
  parameter, response body, status and time; no headers or cookies ever
  reach this process), parses it into the reply table, and marks the
  capture done in the tracker.

Thread views that match no due capture (everyday browsing) go to a separate
`organic/` dataset that never touches the tracker or the confirmatory tests,
or are dropped when the helper runs with `--no-organic`.
"""

from __future__ import annotations

import importlib.util
import json
import os
import threading
from argparse import Namespace
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

from twitterdata.capture.parser import RANKING_MODES, CaptureMeta, build_rows
from twitterdata.capture.safe_har import _is_tweetdetail_url, load_capture
from twitterdata.output import write_csv
from twitterdata.timeutil import parse_iso_utc

BUNDLE_SUFFIX = ".tdcapture.json"
OPEN_STATUSES = ("pending", "done", "late")
SORT_ORDER = ("relevance", "likes", "recent")  # pre-registration 3.4: taken back to back in this order
MAX_BODY_BYTES = 64 * 1024 * 1024
ALLOWED_ORIGINS = ("chrome-extension://", "moz-extension://")
ALLOWED_HOSTS = ("127.0.0.1", "localhost")
EARLY_GRACE = timedelta(minutes=30)


class AssistError(Exception):
    """A request could not be handled. Messages never include page contents."""


def load_tracker(sampling_dir: str):
    """Import sampling/tracker.py, which is a script rather than a package."""
    path = os.path.join(sampling_dir, "tracker.py")
    spec = importlib.util.spec_from_file_location("twitterdata_sampling_tracker", path)
    if spec is None or spec.loader is None:
        raise AssistError(f"no tracker at {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _utc(text: str) -> datetime | None:
    return parse_iso_utc(text) if text else None


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def page_variables(url: str) -> dict:
    try:
        raw = parse_qs(urlsplit(url).query).get("variables", [None])[0]
        variables = json.loads(raw) if raw else {}
    except (ValueError, TypeError):
        variables = {}
    return variables if isinstance(variables, dict) else {}


def sort_of(variables: dict) -> str:
    mode = variables.get("rankingMode")
    if isinstance(mode, str):
        return RANKING_MODES.get(mode.lower(), "unknown")
    return "relevance"  # X's default when the request names no mode


def minimal_url(url: str) -> str:
    """Keep only the path and the `variables` parameter of a TweetDetail URL."""
    parts = urlsplit(url)
    raw = parse_qs(parts.query).get("variables", [None])[0]
    query = urlencode({"variables": raw}) if raw else ""
    return urlunsplit((parts.scheme, parts.netloc, parts.path, query, ""))


def match_capture(captures: list[dict], focal_id: str, sort: str, viewer: str,
                  at: datetime) -> dict | None:
    """Pick the tracker capture a thread view belongs to.

    A capture whose window contains `at` wins. Otherwise the nearest still
    pending capture is used (the tracker then records it as late), as long as
    `at` is no more than EARLY_GRACE before its window opens and no later than
    twice its age (a 6h capture counts as late up to 12h). Captures that are
    already closed outside their window are never overwritten.
    """
    rows = [c for c in captures
            if c["thread_id"] == focal_id and c["sort"] == sort and c["viewer"] == viewer
            and c["status"] in OPEN_STATUSES]
    in_window = [c for c in rows if _utc(c["window_open_utc"]) <= at <= _utc(c["window_close_utc"])]
    if in_window:
        return in_window[0]
    pending = [c for c in rows if c["status"] == "pending"
               and _utc(c["window_open_utc"]) - EARLY_GRACE <= at
               <= _utc(c["due_utc"]) + timedelta(hours=int(c["age_hours"]))]
    if not pending:
        return None
    return min(pending, key=lambda c: abs((_utc(c["due_utc"]) - at).total_seconds()))


def build_bundle(pages: list[dict]) -> dict:
    """A HAR-shaped document the existing parser reads, holding no secrets."""
    entries = []
    for p in pages:
        url = p.get("url")
        if not isinstance(url, str) or not _is_tweetdetail_url(url):
            raise AssistError("a page is not an X TweetDetail response")
        text = p.get("text")
        if not isinstance(text, str):
            raise AssistError("a page has no response body")
        started = _utc(p.get("started") or "")
        entries.append({
            "startedDateTime": _iso(started) if started else None,
            "request": {"method": "GET", "url": minimal_url(url)},
            "response": {"status": int(p.get("status") or 0),
                         "content": {"mimeType": "application/json", "text": text}},
        })
    return {"log": {"version": "1.2", "creator": {"name": "twitterdata capture-extension"},
                    "entries": entries}}


@dataclass
class AssistConfig:
    sampling_dir: str
    data_dir: str
    out_dir: str
    salt: bytes
    viewer: str = "A"
    viewer_type: str = "free"
    include_text: bool = False
    organic: bool = True  # also keep thread views that are not due, in a separate dataset


class Assistant:
    """Everything the HTTP handler does, kept free of HTTP for testing."""

    def __init__(self, cfg: AssistConfig, tracker=None):
        self.cfg = cfg
        self.tracker = tracker or load_tracker(cfg.sampling_dir)
        self.lock = threading.Lock()

    def _store(self):
        return self.tracker.Store(self.cfg.data_dir, os.path.join(self.cfg.sampling_dir, "config.json"))

    def _paths(self, capture_id: str) -> tuple[Path, Path]:
        out = Path(self.cfg.out_dir)
        return out / "raw" / f"{capture_id}{BUNDLE_SUFFIX}", out / "tables" / f"{capture_id}.csv"

    def queue(self, now: datetime | None = None, ahead_minutes: int = 120) -> dict:
        """Due captures grouped into visits: one thread at one age."""
        now = now or datetime.now(timezone.utc)
        store = self._store()
        captures = store.read("captures")
        threads = {t["thread_id"]: t for t in store.read("threads")}
        visits: dict[tuple[str, str], dict] = {}
        for c in captures:
            if c["viewer"] != self.cfg.viewer:
                continue
            key = (c["thread_id"], c["age_hours"])
            v = visits.setdefault(key, {
                "thread_id": c["thread_id"], "age_hours": int(c["age_hours"]),
                "window_open_utc": c["window_open_utc"], "window_close_utc": c["window_close_utc"],
                "url": f"https://x.com/i/status/{c['thread_id']}",
                "topic": threads.get(c["thread_id"], {}).get("topic", ""),
                "sorts": {},
            })
            v["sorts"][c["sort"]] = {"capture_id": c["capture_id"], "status": c["status"],
                                     "n_replies": c.get("n_replies_captured", "")}
        out = []
        for v in visits.values():
            if not any(s["status"] == "pending" for s in v["sorts"].values()):
                continue
            opens, closes = _utc(v["window_open_utc"]), _utc(v["window_close_utc"])
            if opens > now + timedelta(minutes=ahead_minutes):
                continue
            due = opens - timedelta(minutes=int(
                store.config["capture"]["window_minutes"][str(v["age_hours"])][0]))
            if now > due + timedelta(hours=v["age_hours"]):
                continue  # past the point where match_capture would still count it as late
            v["state"] = "overdue" if closes < now else ("open" if opens <= now else "soon")
            v["minutes_left"] = round((closes - now).total_seconds() / 60)
            v["minutes_until_open"] = max(0, round((opens - now).total_seconds() / 60))
            v["sorts"] = [{"sort": s, **v["sorts"][s]} for s in SORT_ORDER if s in v["sorts"]]
            out.append(v)
        rank = {"open": 0, "overdue": 1, "soon": 2}
        out.sort(key=lambda v: (rank[v["state"]], v["window_close_utc"]))
        return {"now_utc": _iso(now), "viewer": self.cfg.viewer, "target_replies":
                store.config["capture"].get("max_reply_scroll", 200), "visits": out}

    def save(self, payload: dict) -> dict:
        """Save one thread view (one focal tweet, one sort) and mark the tracker."""
        pages = payload.get("pages")
        if not isinstance(pages, list) or not pages:
            raise AssistError("no pages")
        variables = page_variables(pages[0].get("url") or "")
        focal_id = str(variables.get("focalTweetId") or "")
        if not focal_id.isdigit():
            raise AssistError("first page has no focal tweet id")
        sort = sort_of(variables)
        started = _utc(payload.get("session_started") or "") or _utc(pages[0].get("started") or "")
        if started is None:
            raise AssistError("no session start time")

        with self.lock:
            store = self._store()
            capture = match_capture(store.read("captures"), focal_id, sort, self.cfg.viewer, started)
            if capture is None:
                if not self.cfg.organic:
                    return {"saved": False, "reason": "not_due", "focal_tweet_id": focal_id, "sort": sort}
                return self._save_organic(pages, focal_id, sort, started)
            capture_id = capture["capture_id"]
            bundle_path, table_path = self._paths(capture_id)
            bundle = build_bundle(pages)
            bundle["log"]["comment"] = json.dumps({"capture_id": capture_id, "session_started": _iso(started)})

            meta = CaptureMeta(viewer_type=self.cfg.viewer_type, viewer_label=self.cfg.viewer,
                               capture_id=capture_id, age_bucket=f"h{int(capture['age_hours']):02d}",
                               include_text=self.cfg.include_text)
            tmp = bundle_path.with_name(bundle_path.name + ".tmp")
            tmp.parent.mkdir(parents=True, exist_ok=True)
            tmp.write_text(json.dumps(bundle), encoding="utf-8")
            responses, _ = load_capture(str(tmp))
            result = build_rows(responses, meta, self.cfg.salt, bundle_path.name, fallback_time=started)
            # Only the first session is a clean view of the thread. Later
            # sessions in the same file would come from reopening the page.
            first = [r for r in result.rows if r["capture_session"] == 1]
            n_top = sum(1 for r in first if r["row_type"] == "reply")

            previous = self._previous(bundle_path)
            if (capture["status"] in ("done", "late") and previous
                    and previous["session_started"] != _iso(started)
                    and int(capture.get("n_replies_captured") or 0) >= n_top):
                tmp.unlink()
                return {"saved": False, "reason": "kept_earlier", "capture_id": capture_id,
                        "n_replies": int(capture.get("n_replies_captured") or 0), "sort": sort}

            tmp.replace(bundle_path)
            table_path.parent.mkdir(parents=True, exist_ok=True)
            write_csv(first, str(table_path))
            file_ref = os.path.relpath(table_path, start=os.getcwd()).replace(os.sep, "/")
            try:
                self.tracker.cmd_mark(store, Namespace(
                    capture_id=capture_id, status="done", file_ref=file_ref, n_replies=n_top,
                    at=_iso(started), notes=None))
            except self.tracker.TrackerError as e:
                raise AssistError(str(e)) from None
            status = [c for c in store.read("captures") if c["capture_id"] == capture_id][0]["status"]
            rank_ok = bool(first) and all(r["rank_is_absolute"] for r in first)
            return {"saved": True, "capture_id": capture_id, "status": status, "sort": sort,
                    "age_hours": int(capture["age_hours"]), "n_replies": n_top,
                    "rank_is_absolute": rank_ok, "pages": len(pages),
                    "target_replies": store.config["capture"].get("max_reply_scroll", 200)}

    def _save_organic(self, pages: list[dict], focal_id: str, sort: str, started: datetime) -> dict:
        """Keep a thread view from everyday browsing in the separate organic set.

        These are a convenience sample, not the pre-registered one, so they
        live under `<out>/organic/` and never touch the tracker.
        """
        name = f"{focal_id}_{sort}_{started.strftime('%Y%m%dT%H%M%SZ')}_{self.cfg.viewer}"
        out = Path(self.cfg.out_dir) / "organic"
        bundle_path, table_path = out / "raw" / f"{name}{BUNDLE_SUFFIX}", out / "tables" / f"{name}.csv"
        bundle = build_bundle(pages)
        bundle["log"]["comment"] = json.dumps({"capture_id": name, "session_started": _iso(started),
                                               "dataset": "organic"})
        bundle_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = bundle_path.with_name(bundle_path.name + ".tmp")
        tmp.write_text(json.dumps(bundle), encoding="utf-8")
        meta = CaptureMeta(viewer_type=self.cfg.viewer_type, viewer_label=self.cfg.viewer, capture_id=name,
                           include_text=self.cfg.include_text)
        responses, _ = load_capture(str(tmp))
        result = build_rows(responses, meta, self.cfg.salt, bundle_path.name, fallback_time=started)
        tmp.replace(bundle_path)
        table_path.parent.mkdir(parents=True, exist_ok=True)
        write_csv(result.rows, str(table_path))
        n_top = sum(1 for r in result.rows if r["row_type"] == "reply" and r["capture_session"] == 1)
        return {"saved": True, "organic": True, "capture_id": name, "sort": sort, "n_replies": n_top,
                "pages": len(pages)}

    @staticmethod
    def _previous(bundle_path: Path) -> dict | None:
        try:
            doc = json.loads(bundle_path.read_text(encoding="utf-8"))
            return json.loads(doc["log"]["comment"])
        except (OSError, ValueError, KeyError, TypeError):
            return None


QUEUE_PAGE = Path(__file__).with_name("queue_page.html")


class Handler(BaseHTTPRequestHandler):
    assistant: Assistant

    def log_message(self, fmt, *args):  # keep request lines (which carry no content) quiet
        pass

    def _host_ok(self) -> bool:
        host = (self.headers.get("Host") or "").rsplit(":", 1)[0].strip("[]")
        return host in ALLOWED_HOSTS

    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code: int, obj: dict) -> None:
        self._send(code, json.dumps(obj).encode("utf-8"), "application/json")

    def do_GET(self):
        if not self._host_ok():
            return self._json(403, {"error": "bad host"})
        path = urlsplit(self.path).path
        if path == "/":
            return self._send(200, QUEUE_PAGE.read_bytes(), "text/html; charset=utf-8")
        if path == "/api/queue":
            return self._json(200, self.assistant.queue())
        if path == "/api/ping":
            return self._json(200, {"ok": True, "viewer": self.assistant.cfg.viewer})
        return self._json(404, {"error": "not found"})

    def do_POST(self):
        # Only the extension may save. Web pages cannot forge an extension
        # Origin, so a site you visit cannot post fake captures here.
        origin = self.headers.get("Origin") or ""
        if not self._host_ok() or not origin.startswith(ALLOWED_ORIGINS):
            return self._json(403, {"error": "forbidden"})
        if urlsplit(self.path).path != "/api/capture":
            return self._json(404, {"error": "not found"})
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0 or length > MAX_BODY_BYTES:
            return self._json(413, {"error": "bad size"})
        try:
            payload = json.loads(self.rfile.read(length))
            if not isinstance(payload, dict):
                raise AssistError("payload is not an object")
            return self._json(200, self.assistant.save(payload))
        except (ValueError, AssistError) as e:
            msg = str(e) if isinstance(e, AssistError) else "payload is not JSON"
            return self._json(400, {"error": msg})


def serve(assistant: Assistant, port: int) -> None:
    handler = type("BoundHandler", (Handler,), {"assistant": assistant})
    httpd = ThreadingHTTPServer(("127.0.0.1", port), handler)
    print(f"capture helper on http://127.0.0.1:{port}/  (Ctrl+C to stop)")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
