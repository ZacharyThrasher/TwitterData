#!/usr/bin/env python3
"""Thread sampling tracker for the pre-registered X reply-ranking study.

Records which threads are screened, which are selected and why, and the
status of every scheduled capture (1h, 6h, 24h x Relevance, Recent, Likes).
State lives in plain CSV files under sampling/data/ so it can be diffed,
reviewed and committed. Standard library only.

Run `python sampling/tracker.py --help` for commands. The rules this tool
enforces are the ones in docs/preregistration.md; change them there first.
"""

import argparse
import csv
import json
import random
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEFAULT_CONFIG = HERE / "config.json"
DEFAULT_DATA = HERE / "data"

SESSION_FIELDS = ["session_id", "start_utc", "length_minutes", "status", "notes"]
SEED_FIELDS = [
    "handle", "account_type", "topic", "poster_politics", "language",
    "follower_band", "why_included", "added_utc",
]
CANDIDATE_FIELDS = [
    "candidate_id", "root_tweet_id", "poster_handle", "poster_followers",
    "posted_utc", "discovered_utc", "session_id", "source", "topic",
    "account_type", "poster_politics", "language", "follower_band",
    "replies_at_discovery", "is_original", "is_protected", "decision",
    "reason", "note",
]
THREAD_FIELDS = [
    "thread_id", "candidate_id", "poster_handle", "poster_followers",
    "posted_utc", "selected_utc", "session_id", "source", "topic",
    "account_type", "poster_politics", "language", "follower_band",
    "cell", "selection_reason", "status", "status_reason",
]
CAPTURE_FIELDS = [
    "capture_id", "thread_id", "age_hours", "sort", "viewer", "due_utc",
    "window_open_utc", "window_close_utc", "status", "captured_utc",
    "file_ref", "n_replies_captured", "notes",
]

FILES = {
    "sessions": ("sessions.csv", SESSION_FIELDS),
    "seeds": ("seed_accounts.csv", SEED_FIELDS),
    "candidates": ("candidates.csv", CANDIDATE_FIELDS),
    "threads": ("threads.csv", THREAD_FIELDS),
    "captures": ("captures.csv", CAPTURE_FIELDS),
}

CAPTURE_STATUSES = {"pending", "done", "late", "missed", "failed", "skipped"}
THREAD_STATUSES = {"active", "complete", "partial", "dropped"}
DROP_REASONS = {"deleted", "protected", "suspended", "capture_failure"}
SOURCES = {"seed_list", "trending", "search"}
# A capture in one of these states no longer needs action.
CLOSED = {"done", "late", "missed", "failed", "skipped"}
FAILED = {"missed", "failed"}
HAR_NAME = re.compile(r"\.har(\.|$)", re.IGNORECASE)


class TrackerError(Exception):
    pass


# ---------- time helpers ----------

def parse_utc(text):
    """Parse an ISO 8601 timestamp; naive values are taken as UTC."""
    if not text:
        raise TrackerError("missing timestamp")
    value = text.strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(value)
    except ValueError as exc:
        raise TrackerError(f"bad timestamp {text!r}") from exc
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fmt_utc(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def is_har(file_ref):
    """True for raw or compressed HAR names such as x.har, x.HAR, x.har.gz."""
    return bool(HAR_NAME.search(file_ref.strip()))


def norm_handle(handle):
    return handle.strip().lstrip("@").lower()


def now_utc():
    return datetime.now(timezone.utc).replace(microsecond=0)


# ---------- storage ----------

class Store:
    def __init__(self, data_dir, config_path):
        self.dir = Path(data_dir)
        self.config = json.loads(Path(config_path).read_text())

    def path(self, name):
        return self.dir / FILES[name][0]

    def read(self, name):
        path = self.path(name)
        if not path.exists():
            return []
        with path.open(newline="", encoding="utf-8") as fh:
            return list(csv.DictReader(fh))

    def write(self, name, rows):
        fields = FILES[name][1]
        self.dir.mkdir(parents=True, exist_ok=True)
        tmp = self.path(name).with_suffix(".tmp")
        with tmp.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=fields, lineterminator="\n")
            writer.writeheader()
            for row in rows:
                writer.writerow({k: row.get(k, "") for k in fields})
        tmp.replace(self.path(name))

    def init(self):
        for name in FILES:
            if not self.path(name).exists():
                self.write(name, [])


# ---------- design helpers ----------

def follower_band(followers):
    return "250k_plus" if followers >= 250_000 else "under_250k"


def cell_key(topic, account_type, language):
    return f"{language}:{topic}:{account_type}"


def cell_quota(config, language):
    quotas = config["quotas"]
    supplement = quotas["language_supplement"]
    if language == supplement["language"]:
        return supplement["per_primary_cell"]
    return quotas["per_primary_cell"]


def all_cells(config):
    s = config["strata"]
    return [
        cell_key(t, a, lang)
        for lang in s["language"]
        for t in s["topic"]
        for a in s["account_type"]
    ]


def total_target(config):
    s = config["strata"]
    per_lang = len(s["topic"]) * len(s["account_type"])
    return sum(per_lang * cell_quota(config, lang) for lang in s["language"])


def counts_toward_quota(thread):
    return thread["status"] != "dropped"


def capture_id(thread_id, age, sort, viewer):
    return f"{thread_id}_h{int(age):02d}_{sort}_{viewer}"


def build_captures(config, thread_id, posted):
    cap = config["capture"]
    rows = []
    for age in cap["ages_hours"]:
        lo, hi = cap["window_minutes"][str(age)]
        due = posted + timedelta(hours=age)
        for sort in cap["sorts"]:
            for viewer in cap["viewers"]:
                rows.append({
                    "capture_id": capture_id(thread_id, age, sort, viewer),
                    "thread_id": thread_id,
                    "age_hours": str(age),
                    "sort": sort,
                    "viewer": viewer,
                    "due_utc": fmt_utc(due),
                    "window_open_utc": fmt_utc(due + timedelta(minutes=lo)),
                    "window_close_utc": fmt_utc(due + timedelta(minutes=hi)),
                    "status": "pending",
                })
    return rows


def check_strata(config, topic, account_type, politics, language):
    s = config["strata"]
    for label, value, allowed in (
        ("topic", topic, s["topic"]),
        ("account_type", account_type, s["account_type"]),
        ("poster_politics", politics, s["poster_politics"]),
        ("language", language, s["language"]),
    ):
        if value not in allowed:
            raise TrackerError(f"{label} must be one of {allowed}, got {value!r}")


def eligibility_failures(config, cand, threads, posted, discovered):
    """Return the list of pre-registered screening rules the candidate fails."""
    rules = config["eligibility"]
    fails = []
    age_min = (discovered - posted).total_seconds() / 60
    if age_min < 0:
        fails.append("discovered_before_posted")
    if age_min > rules["max_age_minutes_at_discovery"]:
        fails.append(f"too_old_at_discovery_{age_min:.0f}min")
    if int(cand["replies_at_discovery"]) < rules["min_replies_at_discovery"]:
        fails.append("too_few_replies_at_discovery")
    if int(cand["poster_followers"]) < rules["min_poster_followers"]:
        fails.append("poster_below_follower_floor")
    if rules["must_be_original_post_or_quote"] and cand["is_original"] != "1":
        fails.append("not_original_post_or_quote")
    if rules["exclude_if_protected_account"] and cand["is_protected"] == "1":
        fails.append("protected_account")
    live = [t for t in threads if counts_toward_quota(t)]
    if any(t["thread_id"] == cand["root_tweet_id"] for t in threads):
        fails.append("thread_already_selected")
    if rules["exclude_if_poster_already_selected"] and any(
        norm_handle(t["poster_handle"]) == norm_handle(cand["poster_handle"]) for t in live
    ):
        fails.append("poster_already_in_sample")
    return fails


def quota_failure(config, cand, threads):
    """Return why a quota or balancing rule blocks selection, or None."""
    live = [t for t in threads if counts_toward_quota(t)]
    cell = cell_key(cand["topic"], cand["account_type"], cand["language"])
    filled = sum(1 for t in live if t["cell"] == cell)
    if filled >= cell_quota(config, cand["language"]):
        return "cell_full"

    bal = config["quotas"]["balancing_targets"]
    side = cand["poster_politics"]
    if side in ("left", "right"):
        other = "right" if side == "left" else "left"
        n_side = sum(1 for t in live if t["poster_politics"] == side)
        n_other = sum(1 for t in live if t["poster_politics"] == other)
        floor = bal[f"poster_politics_min_{side}_overall"]
        if n_side >= floor and n_side + 1 > bal["poster_politics_max_left_right_ratio"] * max(n_other, 1):
            return f"politics_balance_{side}_ahead"

    band = cand["follower_band"]
    n_band = sum(1 for t in live if t["follower_band"] == band)
    if n_band >= total_target(config) - bal["follower_band_min_per_band_overall"]:
        return f"follower_band_{band}_full"
    return None


# ---------- commands ----------

def cmd_init(store, args):
    store.init()
    print(f"initialised {store.dir}")


def cmd_plan_sessions(store, args):
    """Draw discovery session start times, stratified across the day.

    Each day is split into `per_day` equal blocks and one start time is drawn
    uniformly inside each block, so every time of day is covered.
    """
    if args.per_day < 1 or args.days < 1 or args.length < 1:
        raise TrackerError("--days, --per-day and --length must be at least 1")
    sessions = store.read("sessions")
    if sessions and not args.append:
        raise TrackerError("sessions already planned; pass --append to add more (log it as a deviation)")
    rng = random.Random(args.seed)
    start = parse_utc(args.start).replace(hour=0, minute=0, second=0)
    block = 24 * 60 // args.per_day
    n = len(sessions)
    for day in range(args.days):
        for b in range(args.per_day):
            offset = b * block + rng.randrange(max(block - args.length, 1))
            n += 1
            sessions.append({
                "session_id": f"S{n:04d}",
                "start_utc": fmt_utc(start + timedelta(days=day, minutes=offset)),
                "length_minutes": str(args.length),
                "status": "planned",
                "notes": f"seed={args.seed}",
            })
    store.write("sessions", sessions)
    print(f"planned {args.days * args.per_day} sessions (seed {args.seed})")


def cmd_add_seed(store, args):
    s = store.config["strata"]
    if args.account_type not in s["account_type"] or args.topic not in s["topic"]:
        raise TrackerError("unknown topic or account_type")
    seeds = store.read("seeds")
    if any(norm_handle(r["handle"]) == norm_handle(args.handle) for r in seeds):
        raise TrackerError(f"seed {args.handle} already listed")
    seeds.append({
        "handle": args.handle,
        "account_type": args.account_type,
        "topic": args.topic,
        "poster_politics": args.politics,
        "language": args.language,
        "follower_band": args.follower_band,
        "why_included": args.why,
        "added_utc": fmt_utc(now_utc()),
    })
    store.write("seeds", seeds)
    print(f"added seed {args.handle}")


def cmd_screen(store, args):
    """Log a screened post and decide, by the pre-registered rules, if it is selected."""
    cfg = store.config
    check_strata(cfg, args.topic, args.account_type, args.politics, args.language)
    if args.source not in SOURCES:
        raise TrackerError(f"source must be one of {sorted(SOURCES)}")
    if args.session not in {r["session_id"] for r in store.read("sessions")}:
        raise TrackerError(f"unknown session {args.session!r}: screen only inside a planned session")
    posted = parse_utc(args.posted)
    discovered = parse_utc(args.discovered) if args.discovered else now_utc()

    candidates = store.read("candidates")
    threads = store.read("threads")
    cand = {
        "candidate_id": f"C{len(candidates) + 1:05d}",
        "root_tweet_id": args.tweet_id,
        "poster_handle": args.handle,
        "poster_followers": str(args.followers),
        "posted_utc": fmt_utc(posted),
        "discovered_utc": fmt_utc(discovered),
        "session_id": args.session,
        "source": args.source,
        "topic": args.topic,
        "account_type": args.account_type,
        "poster_politics": args.politics,
        "language": args.language,
        "follower_band": follower_band(args.followers),
        "replies_at_discovery": str(args.replies),
        "is_original": "0" if args.not_original else "1",
        "is_protected": "1" if args.protected else "0",
        "note": args.note or "",
    }
    fails = eligibility_failures(cfg, cand, threads, posted, discovered)
    blocked = None
    if not fails:
        stop = summarise(store, discovered)
        blocked = "collection_window_ended" if stop["timed_out"] else quota_failure(cfg, cand, threads)
    if fails:
        cand["decision"], cand["reason"] = "ineligible", ";".join(fails)
    elif blocked:
        cand["decision"], cand["reason"] = "not_selected", blocked
    else:
        cand["decision"] = "selected"
        cand["reason"] = "first_eligible_in_open_cell"
    candidates.append(cand)

    if cand["decision"] == "selected":
        threads.append({
            "thread_id": args.tweet_id,
            "candidate_id": cand["candidate_id"],
            "poster_handle": args.handle,
            "poster_followers": str(args.followers),
            "posted_utc": cand["posted_utc"],
            "selected_utc": cand["discovered_utc"],
            "session_id": args.session,
            "source": args.source,
            "topic": args.topic,
            "account_type": args.account_type,
            "poster_politics": args.politics,
            "language": args.language,
            "follower_band": cand["follower_band"],
            "cell": cell_key(args.topic, args.account_type, args.language),
            "selection_reason": f"{cand['reason']}; source={args.source}; session={args.session}",
            "status": "active",
            "status_reason": "",
        })
        captures = store.read("captures")
        captures.extend(build_captures(cfg, args.tweet_id, posted))
        store.write("captures", captures)
        store.write("threads", threads)
    store.write("candidates", candidates)
    print(f"{cand['candidate_id']} {cand['decision']}: {cand['reason']}")
    return cand


def cmd_due(store, args):
    now = parse_utc(args.now) if args.now else now_utc()
    horizon = now + timedelta(minutes=args.ahead)
    rows = []
    for c in store.read("captures"):
        if c["status"] != "pending":
            continue
        opens, closes = parse_utc(c["window_open_utc"]), parse_utc(c["window_close_utc"])
        if closes < now:
            rows.append(("OVERDUE", closes, c))
        elif opens <= horizon:
            rows.append(("OPEN" if opens <= now else "SOON", closes, c))
    rows.sort(key=lambda r: r[1])
    if not rows:
        print("nothing due")
    for state, closes, c in rows:
        print(f"{state:8} {c['capture_id']:48} window {c['window_open_utc']} to {c['window_close_utc']}")
    return rows


def cmd_mark(store, args):
    if args.status not in CAPTURE_STATUSES - {"pending", "late"}:
        raise TrackerError("status must be done, missed, failed or skipped")
    if args.file_ref and is_har(args.file_ref):
        raise TrackerError("refusing raw .har reference: store only the parsed, credential-free output")
    captures = store.read("captures")
    match = [c for c in captures if c["capture_id"] == args.capture_id]
    if not match:
        raise TrackerError(f"no capture {args.capture_id}")
    c = match[0]
    thread = [t for t in store.read("threads") if t["thread_id"] == c["thread_id"]]
    if thread and thread[0]["status"] in ("dropped", "partial"):
        raise TrackerError(f"thread {c['thread_id']} is {thread[0]['status']}; its captures are closed")
    status = args.status
    if status != "done":
        c["captured_utc"] = ""
        c["file_ref"] = ""
    if status == "done":
        at = parse_utc(args.at) if args.at else now_utc()
        if not parse_utc(c["window_open_utc"]) <= at <= parse_utc(c["window_close_utc"]):
            status = "late"
        c["captured_utc"] = fmt_utc(at)
    c["status"] = status
    if args.file_ref:
        c["file_ref"] = args.file_ref
    if args.n_replies is not None:
        c["n_replies_captured"] = str(args.n_replies)
    if args.notes:
        c["notes"] = args.notes
    store.write("captures", captures)
    refresh_thread_status(store)
    print(f"{c['capture_id']} -> {status}")
    return status


def refresh_thread_status(store):
    threads = store.read("threads")
    by_thread = {}
    for c in store.read("captures"):
        by_thread.setdefault(c["thread_id"], []).append(c)
    changed = False
    for t in threads:
        if t["status"] != "active":
            continue
        caps = by_thread.get(t["thread_id"], [])
        early = [c for c in caps if c["age_hours"] in ("1", "6")]
        if early and all(c["status"] in FAILED for c in early):
            # Pre-registration 3.6: both early ages failed before any 6h data, so the cell reopens.
            t["status"], t["status_reason"] = "dropped", "capture_failure: all 1h and 6h captures failed"
            for c in caps:
                if c["status"] == "pending":
                    c["status"], c["notes"] = "skipped", "thread dropped (capture_failure)"
                    changed = True
        elif caps and all(c["status"] in CLOSED for c in caps):
            t["status"] = "complete"
    if changed:
        store.write("captures", [c for cs in by_thread.values() for c in cs])
    store.write("threads", threads)


def cmd_drop(store, args):
    """Withdraw a thread. Before its 6h Relevance capture it frees its cell for a replacement."""
    if args.reason not in DROP_REASONS:
        raise TrackerError(f"reason must be one of {sorted(DROP_REASONS)}")
    threads = store.read("threads")
    match = [t for t in threads if t["thread_id"] == args.thread_id]
    if not match:
        raise TrackerError(f"no thread {args.thread_id}")
    t = match[0]
    if t["status"] != "active":
        raise TrackerError(f"thread {args.thread_id} is already {t['status']}")
    captures = store.read("captures")
    caps = [c for c in captures if c["thread_id"] == args.thread_id]
    has_6h = any(
        c["age_hours"] == "6" and c["sort"] == "relevance" and c["status"] in ("done", "late")
        for c in caps
    )
    t["status"] = "partial" if has_6h else "dropped"
    t["status_reason"] = args.reason + (f": {args.note}" if args.note else "")
    for c in caps:
        if c["status"] == "pending":
            c["status"] = "skipped"
            c["notes"] = f"thread {t['status']} ({args.reason})"
    store.write("threads", threads)
    store.write("captures", captures)
    verdict = "cell reopened for a replacement" if t["status"] == "dropped" else "kept as partial, no replacement"
    print(f"{args.thread_id} -> {t['status']}; {verdict}")
    return t["status"]


def summarise(store, today=None):
    cfg = store.config
    threads = store.read("threads")
    live = [t for t in threads if counts_toward_quota(t)]
    caps = store.read("captures")
    sessions = store.read("sessions")
    cells = {c: 0 for c in all_cells(cfg)}
    for t in live:
        cells[t["cell"]] = cells.get(t["cell"], 0) + 1
    full = all(n >= cell_quota(cfg, c.split(":")[0]) for c, n in cells.items())
    started = None
    if threads:
        started = min(parse_utc(t["selected_utc"]) for t in threads)
    elif sessions:
        started = min(parse_utc(s["start_utc"]) for s in sessions)
    today = today or now_utc()
    elapsed = (today - started).days if started else 0
    timed_out = started is not None and elapsed >= cfg["stopping"]["collection_days"]
    on_time_6h = {
        c["thread_id"] for c in caps
        if c["age_hours"] == "6" and c["sort"] == "relevance" and c["status"] == "done"
    }
    usable = sum(1 for t in live if t["thread_id"] in on_time_6h)
    by_status = {}
    for c in caps:
        by_status[c["status"]] = by_status.get(c["status"], 0) + 1
    return {
        "cells": cells,
        "live": len(live),
        "target": total_target(cfg),
        "politics": {p: sum(1 for t in live if t["poster_politics"] == p) for p in cfg["strata"]["poster_politics"]},
        "bands": {b: sum(1 for t in live if t["follower_band"] == b) for b in cfg["strata"]["follower_band"]},
        "captures": by_status,
        "days_elapsed": elapsed,
        "stop": full or timed_out,
        "timed_out": timed_out,
        "usable_6h": usable,
        "stop_reason": "all cells full" if full else ("collection window ended" if timed_out else ""),
        "confirmatory": usable >= cfg["stopping"]["min_threads_for_confirmatory"],
    }


def cmd_status(store, args):
    s = summarise(store, parse_utc(args.now) if args.now else None)
    cfg = store.config
    print(f"threads: {s['live']} of {s['target']} target, day {s['days_elapsed']} of {cfg['stopping']['collection_days']}")
    for lang in cfg["strata"]["language"]:
        quota = cell_quota(cfg, lang)
        print(f"\n[{lang}] quota {quota} per cell")
        header = "topic".ljust(26) + "".join(a[:16].rjust(17) for a in cfg["strata"]["account_type"])
        print(header)
        for topic in cfg["strata"]["topic"]:
            line = topic.ljust(26)
            for a in cfg["strata"]["account_type"]:
                line += f"{s['cells'][cell_key(topic, a, lang)]}/{quota}".rjust(17)
            print(line)
    print(f"\npolitics: {s['politics']}")
    print(f"follower bands: {s['bands']}")
    print(f"captures: {s['captures']}")
    if s["stop"]:
        print(f"STOP collecting: {s['stop_reason']}")
    need = cfg["stopping"]["min_threads_for_confirmatory"]
    verdict = "confirmatory sample size reached" if s["confirmatory"] else "below confirmatory minimum"
    print(f"threads with an on-time 6h Relevance capture: {s['usable_6h']} (need {need}); {verdict}")
    return s


def validate(store):
    cfg = store.config
    problems = []
    threads = store.read("threads")
    caps = store.read("captures")
    cands = store.read("candidates")
    expected = len(cfg["capture"]["ages_hours"]) * len(cfg["capture"]["sorts"]) * len(cfg["capture"]["viewers"])
    ids = [t["thread_id"] for t in threads]
    if len(ids) != len(set(ids)):
        problems.append("duplicate thread_id in threads.csv")
    cap_ids = [c["capture_id"] for c in caps]
    if len(cap_ids) != len(set(cap_ids)):
        problems.append("duplicate capture_id in captures.csv")
    cand_ids = {c["candidate_id"] for c in cands}
    per_thread = {}
    for c in caps:
        per_thread[c["thread_id"]] = per_thread.get(c["thread_id"], 0) + 1
        if c["status"] not in CAPTURE_STATUSES:
            problems.append(f"{c['capture_id']}: bad status {c['status']!r}")
        if is_har(c["file_ref"]):
            problems.append(f"{c['capture_id']}: references a raw .har file")
        if c["status"] in ("done", "late") and not c["captured_utc"]:
            problems.append(f"{c['capture_id']}: {c['status']} without captured_utc")
    for t in threads:
        try:
            check_strata(cfg, t["topic"], t["account_type"], t["poster_politics"], t["language"])
        except TrackerError as exc:
            problems.append(f"{t['thread_id']}: {exc}")
        if t["status"] not in THREAD_STATUSES:
            problems.append(f"{t['thread_id']}: bad status {t['status']!r}")
        if t["candidate_id"] not in cand_ids:
            problems.append(f"{t['thread_id']}: no screening record {t['candidate_id']}")
        if per_thread.get(t["thread_id"], 0) != expected:
            problems.append(f"{t['thread_id']}: {per_thread.get(t['thread_id'], 0)} captures, expected {expected}")
    orphan = set(per_thread) - set(ids)
    for tid in sorted(orphan):
        problems.append(f"captures for unknown thread {tid}")
    return problems


def cmd_validate(store, args):
    problems = validate(store)
    for p in problems:
        print(p)
    print("ok" if not problems else f"{len(problems)} problem(s)")
    return 1 if problems else 0


# ---------- CLI ----------

def build_parser():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--data", default=str(DEFAULT_DATA), help="directory holding the tracker CSVs")
    p.add_argument("--config", default=str(DEFAULT_CONFIG))
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init", help="create empty tracker CSVs")

    s = sub.add_parser("plan-sessions", help="draw random discovery session times")
    s.add_argument("--start", required=True, help="first day, e.g. 2026-11-02")
    s.add_argument("--days", type=int, default=56)
    s.add_argument("--per-day", type=int, default=3)
    s.add_argument("--length", type=int, default=45, help="session length in minutes")
    s.add_argument("--seed", type=int, required=True)
    s.add_argument("--append", action="store_true", help="add to an existing schedule")

    s = sub.add_parser("add-seed", help="add an account to the frozen seed list")
    s.add_argument("handle")
    s.add_argument("--topic", required=True)
    s.add_argument("--account-type", required=True)
    s.add_argument("--politics", default="none_unclear")
    s.add_argument("--language", default="en")
    s.add_argument("--follower-band", default="")
    s.add_argument("--why", required=True)

    s = sub.add_parser("screen", help="log a screened post; selects it if the rules allow")
    s.add_argument("tweet_id")
    s.add_argument("--handle", required=True)
    s.add_argument("--followers", type=int, required=True)
    s.add_argument("--posted", required=True, help="post time, UTC ISO 8601")
    s.add_argument("--discovered", help="when it was found (default: now)")
    s.add_argument("--replies", type=int, required=True, help="reply count when found")
    s.add_argument("--session", required=True)
    s.add_argument("--source", default="seed_list")
    s.add_argument("--topic", required=True)
    s.add_argument("--account-type", required=True)
    s.add_argument("--politics", default="none_unclear")
    s.add_argument("--language", default="en")
    s.add_argument("--not-original", action="store_true", help="post is a plain repost or reply")
    s.add_argument("--protected", action="store_true")
    s.add_argument("--note")

    s = sub.add_parser("due", help="list captures whose window is open or opening soon")
    s.add_argument("--now")
    s.add_argument("--ahead", type=int, default=60, help="minutes to look ahead")

    s = sub.add_parser("mark", help="record the outcome of a capture")
    s.add_argument("capture_id")
    s.add_argument("--status", required=True, choices=sorted(CAPTURE_STATUSES - {"pending", "late"}))
    s.add_argument("--at", help="capture time (default: now); outside the window becomes late")
    s.add_argument("--file-ref", help="path of the parsed, credential-free capture output")
    s.add_argument("--n-replies", type=int)
    s.add_argument("--notes")

    s = sub.add_parser("drop", help="withdraw a thread (deleted, protected, suspended, capture_failure)")
    s.add_argument("thread_id")
    s.add_argument("--reason", required=True)
    s.add_argument("--note")

    s = sub.add_parser("status", help="quota fill, balance and capture progress")
    s.add_argument("--now")

    sub.add_parser("validate", help="check the tracker files for integrity problems")
    return p


COMMANDS = {
    "init": cmd_init,
    "plan-sessions": cmd_plan_sessions,
    "add-seed": cmd_add_seed,
    "screen": cmd_screen,
    "due": cmd_due,
    "mark": cmd_mark,
    "drop": cmd_drop,
    "status": cmd_status,
    "validate": cmd_validate,
}


def main(argv=None):
    args = build_parser().parse_args(argv)
    store = Store(args.data, args.config)
    try:
        result = COMMANDS[args.cmd](store, args)
    except TrackerError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return result if isinstance(result, int) else 0


if __name__ == "__main__":
    sys.exit(main())
