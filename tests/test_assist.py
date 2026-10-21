import csv
import http.client
import json
import threading
from datetime import datetime, timedelta, timezone
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

import synthetic as syn
from twitterdata.capture.assist import (AssistConfig, Assistant, Handler, build_bundle, load_tracker,
                                        match_capture, minimal_url)

ROOT = Path(__file__).resolve().parents[1]
SAMPLING = str(ROOT / "sampling")
POSTED = datetime(2026, 11, 2, 12, 0, tzinfo=timezone.utc)
SALT = b"test-salt"


def iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")


@pytest.fixture
def tracker():
    return load_tracker(SAMPLING)


@pytest.fixture
def assistant(tmp_path, tracker):
    store = tracker.Store(tmp_path / "data", ROOT / "sampling" / "config.json")
    store.init()
    store.write("threads", [{"thread_id": syn.FOCAL_ID, "topic": "sports", "status": "active"}])
    store.write("captures", tracker.build_captures(store.config, syn.FOCAL_ID, POSTED))
    cfg = AssistConfig(sampling_dir=SAMPLING, data_dir=str(tmp_path / "data"), out_dir=str(tmp_path / "out"),
                       salt=SALT)
    return Assistant(cfg, tracker)


def view(started, mode="Relevance", pages=None):
    pages = pages or [(None, syn.page_top()), ("c1", syn.page_next())]
    out = []
    for i, (cursor, body) in enumerate(pages):
        t = started + timedelta(seconds=5 * i)
        out.append({"url": syn.tweetdetail_url(ranking_mode=mode, cursor=cursor), "status": 200,
                    "text": json.dumps(body), "started": iso(t)})
    return {"session_started": iso(started), "pages": out}


def captures(assistant):
    return {c["capture_id"]: c for c in assistant._store().read("captures")}


def test_saves_parses_and_marks_due_capture(assistant, tmp_path):
    res = assistant.save(view(POSTED + timedelta(hours=6, minutes=5)))
    cid = f"{syn.FOCAL_ID}_h06_relevance_A"
    assert res["saved"] and res["capture_id"] == cid and res["status"] == "done"
    assert res["n_replies"] == 4 and res["rank_is_absolute"]
    c = captures(assistant)[cid]
    assert c["status"] == "done" and c["n_replies_captured"] == "4"
    assert c["captured_utc"] == "2026-11-02T18:05:00Z"
    assert c["file_ref"].endswith(f"tables/{cid}.csv") and ".har" not in c["file_ref"]
    rows = list(csv.DictReader(open(tmp_path / "out" / "tables" / f"{cid}.csv", encoding="utf-8")))
    assert {r["capture_id"] for r in rows} == {cid}
    assert {r["age_bucket"] for r in rows} == {"h06"}
    assert {r["viewer_type"] for r in rows} == {"free"}
    assert (tmp_path / "out" / "raw" / f"{cid}.tdcapture.json").exists()


def test_sort_comes_from_the_request(assistant):
    res = assistant.save(view(POSTED + timedelta(hours=6), mode="Likes", pages=[(None, syn.page_likes())]))
    assert res["capture_id"] == f"{syn.FOCAL_ID}_h06_likes_A"


def test_outside_window_goes_to_nearest_pending_and_is_late(assistant):
    res = assistant.save(view(POSTED + timedelta(hours=7, minutes=30)))
    assert res["capture_id"] == f"{syn.FOCAL_ID}_h06_relevance_A" and res["status"] == "late"


def test_growing_view_overwrites_but_reopening_does_not_clobber(assistant):
    start = POSTED + timedelta(hours=6)
    assistant.save(view(start, pages=[(None, syn.page_top())]))
    grown = assistant.save(view(start))
    assert grown["saved"] and grown["n_replies"] == 4
    later = start + timedelta(minutes=10)
    again = assistant.save(view(later, pages=[(None, syn.page_likes())]))
    assert again == {"saved": False, "reason": "kept_earlier", "n_replies": 4, "sort": "relevance",
                     "capture_id": f"{syn.FOCAL_ID}_h06_relevance_A"}
    assert captures(assistant)[f"{syn.FOCAL_ID}_h06_relevance_A"]["captured_utc"] == "2026-11-02T18:00:00Z"


def test_untracked_thread_goes_to_organic_set_not_tracker(assistant, tmp_path):
    before = captures(assistant)
    payload = view(POSTED + timedelta(hours=6))
    for p in payload["pages"]:
        p["url"] = syn.tweetdetail_url(focal_id="2000000000000009999", cursor=p["url"].count("c1") and "c1")
    res = assistant.save(payload)
    assert res["saved"] and res["organic"]
    assert captures(assistant) == before
    organic = list((tmp_path / "out" / "organic" / "tables").glob("*.csv"))
    assert len(organic) == 1 and organic[0].name.startswith("2000000000000009999_relevance_")
    assert not (tmp_path / "out" / "tables").exists()


def test_tracked_thread_long_after_its_last_window_is_not_a_capture(assistant):
    res = assistant.save(view(POSTED + timedelta(days=5)))
    assert res["organic"] and all(c["status"] == "pending" for c in captures(assistant).values())


def test_no_organic_drops_untracked_views(assistant, tmp_path):
    assistant.cfg.organic = False
    payload = view(POSTED + timedelta(days=5))
    res = assistant.save(payload)
    assert res["saved"] is False and res["reason"] == "not_due"
    assert not (tmp_path / "out").exists()


def test_bundle_holds_no_secrets_and_rejects_other_urls():
    url = syn.tweetdetail_url(cursor="c1") + "&extra=" + syn.SENTINEL
    bundle = build_bundle([{"url": url, "status": 200, "text": "{}", "headers": syn.secret_headers()}])
    text = json.dumps(bundle)
    assert syn.SENTINEL not in text and "features" not in text
    assert "focalTweetId" in minimal_url(url)
    with pytest.raises(Exception):
        build_bundle([{"url": "https://x.com/i/api/graphql/a/HomeTimeline", "status": 200, "text": "{}"}])


def test_match_capture_skips_other_viewers_and_closed(tracker):
    rows = tracker.build_captures(json.loads((ROOT / "sampling" / "config.json").read_text()), "1", POSTED)
    for r in rows:
        if r["age_hours"] == "6":
            r["status"] = "missed"
    at = POSTED + timedelta(hours=6)
    assert match_capture(rows, "1", "relevance", "A", at) is None
    assert match_capture(rows, "1", "relevance", "B", at) is None


def test_queue_groups_visits_by_age(assistant):
    q = assistant.queue(now=POSTED + timedelta(hours=6))
    assert [v["age_hours"] for v in q["visits"]][:1] == [6]
    v = q["visits"][0]
    assert v["state"] == "open" and v["url"].endswith(syn.FOCAL_ID)
    assert [s["sort"] for s in v["sorts"]][0] == "relevance"


@pytest.fixture
def server(assistant):
    handler = type("H", (Handler,), {"assistant": assistant})
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    yield httpd.server_address[1]
    httpd.shutdown()
    httpd.server_close()


def request(port, method, path, body=None, headers=None):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    conn.request(method, path, body=body, headers=headers or {})
    r = conn.getresponse()
    return r.status, r.read()


def test_http_only_extensions_may_post(server):
    body = json.dumps(view(POSTED + timedelta(hours=6)))
    assert request(server, "POST", "/api/capture", body, {"Origin": "https://evil.example"})[0] == 403
    assert request(server, "POST", "/api/capture", body)[0] == 403
    status, out = request(server, "POST", "/api/capture", body, {"Origin": "chrome-extension://abc"})
    assert status == 200 and json.loads(out)["saved"]


def test_http_rejects_foreign_host_and_serves_queue(server):
    assert request(server, "GET", "/api/queue", headers={"Host": "attacker.example"})[0] == 403
    status, page = request(server, "GET", "/")
    assert status == 200 and b"Capture queue" in page
    status, q = request(server, "GET", "/api/queue")
    assert status == 200 and "visits" in json.loads(q)


def test_queue_hides_captures_too_late_to_count(assistant):
    q = assistant.queue(now=POSTED + timedelta(hours=7))
    assert [(v["age_hours"], v["state"]) for v in q["visits"]] == [(6, "overdue")]
    q = assistant.queue(now=POSTED + timedelta(hours=12, minutes=30))
    assert q["visits"] == []
