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
