"""Tests for sampling/tracker.py. Run: python -m unittest discover sampling"""

import contextlib
import io
import tempfile
import unittest
from pathlib import Path

import tracker

POSTED = "2026-11-02T12:00:00Z"
FOUND = "2026-11-02T12:20:00Z"


def run(data, *argv):
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
        code = tracker.main(["--data", data, *argv])
    return code, out.getvalue()


def screen(data, tweet_id, handle, **kw):
    args = {
        "--handle": handle,
        "--followers": "50000",
        "--posted": POSTED,
        "--discovered": FOUND,
        "--replies": "40",
        "--session": "S0001",
        "--topic": "sports",
        "--account-type": "organic_creator",
    }
    args.update({f"--{k.replace('_', '-')}": str(v) for k, v in kw.items()})
    flat = [x for pair in args.items() for x in pair]
    return run(data, "screen", tweet_id, *flat)


class TrackerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.data = self.tmp.name
        run(self.data, "init")
        run(self.data, "plan-sessions", "--start", "2026-11-02", "--days", "1", "--per-day", "1", "--seed", "1")
        self.store = tracker.Store(self.data, tracker.DEFAULT_CONFIG)

    def tearDown(self):
        self.tmp.cleanup()

    def test_target_is_144(self):
        self.assertEqual(tracker.total_target(self.store.config), 144)

    def test_selected_thread_gets_nine_captures_with_windows(self):
        code, out = screen(self.data, "111", "alice")
        self.assertEqual(code, 0)
        self.assertIn("selected", out)
        caps = self.store.read("captures")
        self.assertEqual(len(caps), 9)
        one = [c for c in caps if c["capture_id"] == "111_h01_relevance_A"][0]
        self.assertEqual(one["due_utc"], "2026-11-02T13:00:00Z")
        self.assertEqual(one["window_open_utc"], "2026-11-02T12:50:00Z")
        self.assertEqual(one["window_close_utc"], "2026-11-02T13:20:00Z")
        self.assertEqual(tracker.validate(self.store), [])

    def test_ineligible_is_logged_with_reasons_not_selected(self):
        screen(self.data, "222", "bob", discovered="2026-11-02T13:30:00Z", replies=3)
        cand = self.store.read("candidates")[0]
        self.assertEqual(cand["decision"], "ineligible")
        self.assertIn("too_old_at_discovery", cand["reason"])
        self.assertIn("too_few_replies_at_discovery", cand["reason"])
        self.assertEqual(self.store.read("threads"), [])

    def test_cell_fills_at_quota(self):
        for i in range(7):
            screen(self.data, str(1000 + i), f"user{i}")
        screen(self.data, "2000", "extra")
        last = self.store.read("candidates")[-1]
        self.assertEqual(last["decision"], "not_selected")
        self.assertEqual(last["reason"], "cell_full")

    def test_spanish_supplement_quota_is_one(self):
        screen(self.data, "3000", "es1", language="es")
        screen(self.data, "3001", "es2", language="es")
        self.assertEqual(self.store.read("candidates")[-1]["reason"], "cell_full")

    def test_same_poster_only_once(self):
        screen(self.data, "4000", "carol")
        screen(self.data, "4001", "Carol", topic="news_events")
        self.assertIn("poster_already_in_sample", self.store.read("candidates")[-1]["reason"])

    def test_politics_balance_blocks_runaway_side(self):
        cfg = self.store.config
        cfg["quotas"]["balancing_targets"]["poster_politics_min_left_overall"] = 2
        topics = cfg["strata"]["topic"]
        threads = []
        for i in range(2):
            threads.append({"thread_id": str(i), "poster_handle": f"l{i}", "poster_politics": "left",
                            "cell": f"en:{topics[i]}:organic_creator", "follower_band": "under_250k",
                            "status": "active"})
        cand = {"topic": "sports", "account_type": "news_official", "language": "en",
                "poster_politics": "left", "follower_band": "under_250k"}
        self.assertEqual(tracker.quota_failure(cfg, cand, threads), "politics_balance_left_ahead")
        cand["poster_politics"] = "right"
        self.assertIsNone(tracker.quota_failure(cfg, cand, threads))

    def test_mark_done_inside_and_outside_window(self):
        screen(self.data, "5000", "dave")
        run(self.data, "mark", "5000_h01_relevance_A", "--status", "done", "--at", "2026-11-02T13:05:00Z",
            "--file-ref", "captures/5000_h01_relevance_A.parquet")
        run(self.data, "mark", "5000_h01_recent_A", "--status", "done", "--at", "2026-11-02T14:00:00Z")
        caps = {c["capture_id"]: c for c in self.store.read("captures")}
        self.assertEqual(caps["5000_h01_relevance_A"]["status"], "done")
        self.assertEqual(caps["5000_h01_recent_A"]["status"], "late")

    def test_mark_refuses_raw_har(self):
        screen(self.data, "6000", "erin")
        code, out = run(self.data, "mark", "6000_h01_likes_A", "--status", "done", "--file-ref", "x/raw.HAR")
        self.assertEqual(code, 2)
        self.assertIn(".har", out)

    def test_drop_before_6h_reopens_cell(self):
        for i in range(7):
            screen(self.data, str(7000 + i), f"f{i}")
        run(self.data, "drop", "7000", "--reason", "deleted")
        self.assertEqual(self.store.read("threads")[0]["status"], "dropped")
        screen(self.data, "7100", "replacement")
        self.assertEqual(self.store.read("candidates")[-1]["decision"], "selected")

    def test_drop_after_6h_keeps_partial(self):
        screen(self.data, "8000", "gail")
        run(self.data, "mark", "8000_h06_relevance_A", "--status", "done", "--at", "2026-11-02T18:00:00Z")
        run(self.data, "drop", "8000", "--reason", "deleted")
        t = self.store.read("threads")[0]
        self.assertEqual(t["status"], "partial")
        caps = {c["capture_id"]: c for c in self.store.read("captures")}
        self.assertEqual(caps["8000_h24_likes_A"]["status"], "skipped")

    def test_thread_completes_when_all_captures_closed(self):
        screen(self.data, "9000", "hank")
        for c in self.store.read("captures"):
            run(self.data, "mark", c["capture_id"], "--status", "done", "--at", c["due_utc"])
        self.assertEqual(self.store.read("threads")[0]["status"], "complete")

    def test_due_lists_open_and_overdue(self):
        screen(self.data, "9100", "ivy")
        rows = tracker.cmd_due(self.store, type("A", (), {"now": "2026-11-02T13:30:00Z", "ahead": 0})())
        states = {r[0] for r in rows}
        self.assertEqual(states, {"OVERDUE"})
        rows = tracker.cmd_due(self.store, type("A", (), {"now": "2026-11-02T12:55:00Z", "ahead": 0})())
        self.assertEqual({r[0] for r in rows}, {"OPEN"})

    def test_plan_sessions_is_reproducible_and_covers_day(self):
        run(self.data, "plan-sessions", "--start", "2026-11-02", "--days", "2", "--per-day", "3", "--seed", "42", "--append")
        first = [s["start_utc"] for s in self.store.read("sessions")][1:]
        other = tempfile.TemporaryDirectory()
        run(other.name, "plan-sessions", "--start", "2026-11-02", "--days", "2", "--per-day", "3", "--seed", "42")
        second = [s["start_utc"] for s in tracker.Store(other.name, tracker.DEFAULT_CONFIG).read("sessions")]
        other.cleanup()
        self.assertEqual(first, second)
        hours = [int(s[11:13]) for s in first[:3]]
        self.assertTrue(hours[0] < 8 <= hours[1] < 16 <= hours[2])

    def test_validate_flags_missing_captures(self):
        screen(self.data, "9200", "jo")
        caps = self.store.read("captures")[:-1]
        self.store.write("captures", caps)
        self.assertTrue(any("expected 9" in p for p in tracker.validate(self.store)))

    def test_status_stop_rule_after_window(self):
        screen(self.data, "9300", "kim")
        s = tracker.summarise(self.store, tracker.parse_utc("2027-01-15T00:00:00Z"))
        self.assertTrue(s["stop"])
        self.assertEqual(s["stop_reason"], "collection window ended")
        self.assertFalse(s["confirmatory"])


    def test_unknown_session_rejected(self):
        code, out = screen(self.data, "9400", "lee", session="S9999")
        self.assertEqual(code, 2)
        self.assertIn("unknown session", out)

    def test_replanning_sessions_needs_append(self):
        code, out = run(self.data, "plan-sessions", "--start", "2026-11-02", "--seed", "1")
        self.assertEqual(code, 2)
        code, out = run(self.data, "plan-sessions", "--start", "2026-11-02", "--per-day", "0", "--seed", "1", "--append")
        self.assertEqual(code, 2)

    def test_handle_with_at_sign_is_same_poster(self):
        screen(self.data, "9500", "carol")
        screen(self.data, "9501", " @Carol", topic="news_events")
        self.assertIn("poster_already_in_sample", self.store.read("candidates")[-1]["reason"])

    def test_compressed_har_refused(self):
        screen(self.data, "9600", "mo")
        for ref in ("x/raw.har.gz", "x/raw.HAR.zip", "x/raw.har "):
            code, _ = run(self.data, "mark", "9600_h01_likes_A", "--status", "done", "--file-ref", ref)
            self.assertEqual(code, 2, ref)

    def test_no_selection_after_collection_window(self):
        screen(self.data, "9700", "ned")
        code, out = screen(self.data, "9701", "ola", topic="news_events",
                           posted="2027-01-10T12:00:00Z", discovered="2027-01-10T12:20:00Z")
        self.assertEqual(self.store.read("candidates")[-1]["reason"], "collection_window_ended")

    def test_early_capture_failure_drops_and_reopens(self):
        screen(self.data, "9800", "pat")
        for c in self.store.read("captures"):
            if c["age_hours"] in ("1", "6"):
                run(self.data, "mark", c["capture_id"], "--status", "failed")
        t = self.store.read("threads")[0]
        self.assertEqual(t["status"], "dropped")
        caps = {c["capture_id"]: c for c in self.store.read("captures")}
        self.assertEqual(caps["9800_h24_relevance_A"]["status"], "skipped")
        self.assertEqual(tracker.validate(self.store), [])

    def test_drop_refuses_non_active_and_mark_refuses_closed_thread(self):
        screen(self.data, "9900", "quinn")
        run(self.data, "drop", "9900", "--reason", "deleted")
        code, _ = run(self.data, "drop", "9900", "--reason", "deleted")
        self.assertEqual(code, 2)
        code, _ = run(self.data, "mark", "9900_h06_relevance_A", "--status", "done")
        self.assertEqual(code, 2)

    def test_remark_clears_stale_fields(self):
        screen(self.data, "9910", "rae")
        run(self.data, "mark", "9910_h01_likes_A", "--status", "done", "--at", "2026-11-02T13:00:00Z",
            "--file-ref", "captures/a.csv")
        run(self.data, "mark", "9910_h01_likes_A", "--status", "failed")
        c = [c for c in self.store.read("captures") if c["capture_id"] == "9910_h01_likes_A"][0]
        self.assertEqual((c["captured_utc"], c["file_ref"]), ("", ""))

    def test_confirmatory_counts_on_time_6h_relevance_only(self):
        cfg = self.store.config
        cfg["stopping"]["min_threads_for_confirmatory"] = 1
        screen(self.data, "9920", "sam")
        self.assertFalse(tracker.summarise(self.store)["confirmatory"])
        run(self.data, "mark", "9920_h06_relevance_A", "--status", "done", "--at", "2026-11-02T18:00:00Z")
        self.store = tracker.Store(self.data, tracker.DEFAULT_CONFIG)
        self.store.config["stopping"]["min_threads_for_confirmatory"] = 1
        self.assertTrue(tracker.summarise(self.store)["confirmatory"])


if __name__ == "__main__":
    unittest.main()
