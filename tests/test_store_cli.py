import csv
import os
import time

from conftest import FIXTURES

from clip_monitor import cli
from clip_monitor.store import Store, make_snapshot_id


def test_snapshot_id_is_utc_and_stable():
    assert make_snapshot_id("vyro", "2026-10-21T17:55:00Z", "abcdef1234") == "vyro_20261021T175500Z_abcdef12"
    assert make_snapshot_id("vyro", "2026-10-21T13:55:00-04:00", "abcdef1234") == "vyro_20261021T175500Z_abcdef12"


def test_ingest_stores_once_and_records_metadata(tmp_path, capsys):
    data = tmp_path / "data"
    args = ["ingest", str(FIXTURES / "vyro_board.html"), "--source", "vyro",
            "--observed-at", "2026-10-21T17:55:00Z", "--url", "https://vyro.com/campaigns", "--data", str(data)]
    assert cli.main(args) == 0
    assert cli.main(args) == 0  # same bytes again: skipped
    store = Store(data)
    snaps = store.snapshots()
    assert len(snaps) == 1
    assert snaps[0]["method"] == "manual_save" and snaps[0]["n_campaigns"] == 3
    rows = store.rows()
    assert len(rows) == 3
    assert {r["topic"] for r in rows} >= {"politics"}
    raw_files = list((data / "raw" / "vyro").glob("*.html"))
    assert len(raw_files) == 1


def test_ingest_reads_saved_from_url_and_mtime(tmp_path):
    page = tmp_path / "clipping.html"
    page.write_bytes((FIXTURES / "clipping_net_home.html").read_bytes())
    t = 1792540800  # 2026-10-21T00:00:00Z
    os.utime(page, (t, t))
    data = tmp_path / "data"
    assert cli.main(["ingest", str(page), "--source", "clipping_net", "--data", str(data)]) == 0
    [snap] = Store(data).snapshots()
    assert snap["page_url"] == "https://clipping.net/"
    assert snap["observed_at"] == "2026-10-21T00:00:00Z"


def test_summary_merges_detail_and_board_rows(tmp_path):
    data = tmp_path / "data"
    cli.main(["ingest", str(FIXTURES / "vyro_board.html"), "--source", "vyro",
              "--observed-at", "2026-10-21T17:55:00Z", "--data", str(data)])
    cli.main(["ingest", str(FIXTURES / "vyro_detail.html"), "--source", "vyro",
              "--observed-at", "2026-10-22T17:55:00Z", "--data", str(data)])
    view = cli.current_view(Store(data).rows())
    when, rows = view["vyro"]
    assert when == "2026-10-22T17:55:00Z"
    assert len(rows) == 4
    text = cli.summarize(Store(data).rows())
    assert "vyro" in text and "pay for X views: 2 of 3" in text


def test_summary_window_drops_stale_campaigns(tmp_path):
    data = tmp_path / "data"
    cli.main(["ingest", str(FIXTURES / "vyro_board.html"), "--source", "vyro",
              "--observed-at", "2026-09-01T00:00:00Z", "--data", str(data)])
    cli.main(["ingest", str(FIXTURES / "vyro_detail.html"), "--source", "vyro",
              "--observed-at", "2026-10-22T00:00:00Z", "--data", str(data)])
    _, rows = cli.current_view(Store(data).rows(), window_days=7)["vyro"]
    assert [r["campaign_id"] for r in rows] == ["vyro:Mm55Nn44"]


def test_fetch_refuses_when_terms_forbid(tmp_path, capsys):
    assert cli.main(["fetch", "--source", "vyro", "--data", str(tmp_path)]) == 3
    assert "automated fetching is off" in capsys.readouterr().err


def test_tag_accounts_cli(tmp_path, capsys):
    inp = tmp_path / "replies.csv"
    with inp.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["screen_name", "user_id", "name", "description", "affiliate_badge", "full_text"])
        w.writeheader()
        w.writerow({"screen_name": "a", "user_id": "1", "name": "A", "description": "", "affiliate_badge": "Clipur.ai", "full_text": "hi"})
        w.writerow({"screen_name": "b", "user_id": "2", "name": "B", "description": "", "affiliate_badge": "", "full_text": "nice"})
        w.writerow({"screen_name": "b", "user_id": "2", "name": "B", "description": "", "affiliate_badge": "", "full_text": "#ExampleGamesPartner"})
    data = tmp_path / "data"
    cli.main(["ingest", str(FIXTURES / "vyro_board.html"), "--source", "vyro",
              "--observed-at", "2026-10-21T17:55:00Z", "--data", str(data)])
    out = tmp_path / "tags.csv"
    assert cli.main(["tag-accounts", str(inp), "--out", str(out), "--data", str(data)]) == 0
    tiers = {r["screen_name"]: r["paid_clipper_tier"] for r in csv.DictReader(out.open(encoding="utf-8"))}
    assert tiers == {"a": "paid_confirmed", "b": "paid_confirmed"}


def test_ingest_expands_wildcards_itself(tmp_path):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "vyro_1.html").write_bytes((FIXTURES / "vyro_board.html").read_bytes())
    (inbox / "vyro_2.html").write_bytes((FIXTURES / "vyro_detail.html").read_bytes())
    data = tmp_path / "data"
    assert cli.main(["ingest", str(inbox / "vyro_*.html"), "--source", "vyro", "--data", str(data)]) == 0
    assert len(Store(data).snapshots()) == 2


def test_merge_keeps_board_topic_and_platforms_over_thinner_detail_row():
    board = {"snapshot_id": "1", "observed_at": "2026-10-21T00:00:00Z", "campaign_id": "c", "source": "vyro",
             "topic": "politics", "topics": "politics", "topic_keywords": "senate",
             "platforms": "x", "platforms_known": "true", "targets_x": "true",
             "rate_per_1k_usd": "2", "rate_is_max": "false", "platform_rates_per_1k": "", "budget_total_usd": "100"}
    detail = dict(board, snapshot_id="2", observed_at="2026-10-22T00:00:00Z", topic="other", topics="other",
                  topic_keywords="", platforms="", platforms_known="false", targets_x="", budget_total_usd="",
                  rate_per_1k_usd="2.5")
    m = cli._merge_latest([board, detail])
    assert m["topic"] == "politics" and m["platforms_known"] == "true" and m["targets_x"] == "true"
    assert m["budget_total_usd"] == "100"
    assert m["rate_per_1k_usd"] == "2.5"  # newer value wins when present
    assert m["snapshot_id"] == "2"


def test_newest_is_chosen_by_time_not_string(tmp_path):
    rows = [
        {"source": "s", "campaign_id": "a", "observed_at": "2026-10-21T23:00:00-05:00"},  # 04:00Z on the 22nd
        {"source": "s", "campaign_id": "b", "observed_at": "2026-10-22T01:00:00Z"},
    ]
    when, _ = cli.current_view(rows)["s"]
    assert when == "2026-10-21T23:00:00-05:00"


def test_observed_at_is_validated_and_normalized(tmp_path, capsys):
    data = tmp_path / "data"
    bad = ["ingest", str(FIXTURES / "vyro_board.html"), "--source", "vyro", "--observed-at", "21/10/2026", "--data", str(data)]
    assert cli.main(bad) == 2
    assert "ISO 8601" in capsys.readouterr().err
    ok = ["ingest", str(FIXTURES / "vyro_board.html"), "--source", "vyro",
          "--observed-at", "2026-10-21T13:00:00-04:00", "--data", str(data)]
    assert cli.main(ok) == 0
    assert Store(data).snapshots()[0]["observed_at"] == "2026-10-21T17:00:00Z"


def test_rows_left_by_an_interrupted_run_are_not_doubled(tmp_path):
    from clip_monitor.store import SnapshotMeta
    from clip_monitor.models import Campaign
    store = Store(tmp_path)
    meta = SnapshotMeta("s_1", "vyro", "2026-10-21T00:00:00Z", "manual_save", "", "abc", 1)
    c = Campaign(source="vyro", campaign_id="x", name="n")
    # Simulate a crash after the CSV write: rows present, no log line.
    store.save(meta, b"page", [c])
    store.log_path.unlink()
    fresh = Store(tmp_path)
    assert fresh.save(meta, b"page", [c]) is True
    assert len(fresh.rows()) == 1
