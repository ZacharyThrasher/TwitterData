import csv
import json
import os
import stat

import pytest

import synthetic as syn
from twitterdata import schema
from twitterdata.capture.parser import CaptureMeta, parse_capture
from twitterdata.capture.safe_har import CaptureError, load_har
from twitterdata.cli import SCHEMA_DOC, SCHEMA_JSON, main, render_doc
from twitterdata.privacy import SALT_ENV, load_salt, pseudonym

SALT = b"test-salt"
HANDLES = ["OriginalPoster", "RootAuthor", "BlueReplier", "FreeReplier", "Spammy12345", "LateReplier"]


@pytest.fixture
def har_path(tmp_path):
    path = tmp_path / "capture.har"
    path.write_text(json.dumps(syn.standard_har()), encoding="utf-8")
    return str(path)


@pytest.fixture(autouse=True)
def isolated_salt(tmp_path, monkeypatch):
    monkeypatch.setenv(SALT_ENV, "test-salt")
    monkeypatch.setenv("HOME", str(tmp_path / "home"))


def parse(path, **meta):
    return parse_capture(path, CaptureMeta(**meta), SALT)


def by_tweet(rows, session):
    return {r["tweet_id"]: r for r in rows if r["capture_session"] == session}


# Secret handling


def test_loader_drops_headers_cookies_and_non_tweetdetail(har_path):
    responses, stats = load_har(har_path)
    assert stats == {"entries": 7, "tweetdetail": 4, "skipped_status": 1, "skipped_body": 0}
    assert len(responses) == 3
    assert syn.SENTINEL not in repr(responses)
    assert [r.has_cursor for r in responses] == [False, True, False]
    assert [r.ranking_mode for r in responses] == ["Relevance", "Relevance", "Likes"]


@pytest.mark.parametrize("ext", ["csv", "jsonl"])
def test_cli_output_and_logs_never_contain_secrets(har_path, tmp_path, capsys, ext):
    out = tmp_path / f"replies.{ext}"
    assert main(["parse", har_path, "-o", str(out), "--include-text", "--viewer-type", "free"]) == 0
    written = out.read_text(encoding="utf-8")
    logs = capsys.readouterr()
    for blob in (written, logs.out, logs.err):
        assert syn.SENTINEL not in blob
        assert "auth_token" not in blob
        assert "Bearer" not in blob


def test_raw_handles_and_user_ids_never_written(har_path, tmp_path):
    out = tmp_path / "replies.csv"
    main(["parse", har_path, "-o", str(out)])
    written = out.read_text(encoding="utf-8")
    for handle in HANDLES:
        assert handle not in written
        assert handle.lower() not in written
    rows = list(csv.DictReader(out.open(encoding="utf-8")))
    assert all(len(r["author_id_hash"]) == 24 for r in rows)
    assert not {"1000", "1001", "1002"} & {v for r in rows for v in r.values()}


def test_secret_shaped_text_is_redacted(tmp_path):
    leaky = syn.tweet("2000000000000000901", syn.FREE, reply_to=syn.FOCAL_ID,
                      text="look: auth_token=abc123 ct0=def")
    path = tmp_path / "leak.har"
    path.write_text(json.dumps(syn.har([
        syn.har_entry(syn.tweetdetail_url(), syn.body([syn.tweet_entry(syn.FOCAL, 2),
                                                       syn.module("x", [leaky], 1)]))])))
    result = parse(str(path), include_text=True)
    assert result.rows[0]["text"] == "REDACTED"
    assert result.stats["redacted_cells"] == 1


def test_bad_file_error_does_not_echo_contents(tmp_path):
    path = tmp_path / "broken.har"
    path.write_text('{"log": {"entries": [ ' + syn.SENTINEL, encoding="utf-8")
    with pytest.raises(CaptureError) as err:
        load_har(str(path))
    assert syn.SENTINEL not in str(err.value)
    assert err.value.__cause__ is None


def test_refuses_to_overwrite_capture(har_path, tmp_path):
    assert main(["parse", har_path, "-o", har_path]) == 2
    assert main(["parse", har_path, "-o", str(tmp_path / "out.har")]) == 2


# Reply table content


def test_sessions_pages_and_sort_orders(har_path):
    rows = parse(har_path, viewer_type="premium", viewer_label="A", age_bucket="h06").rows
    assert {(r["capture_session"], r["sort_order"], r["sort_order_source"]) for r in rows} == {
        (1, "relevance", "request"), (2, "likes", "request")}
    s1 = by_tweet(rows, 1)
    assert s1["2000000000000000205"]["page_index"] == 1
    assert s1["2000000000000000201"]["page_index"] == 0
    assert all(r["capture_time_utc"] == "2026-10-21T13:33:13.123Z" for r in s1.values())
    assert all(r["viewer_type"] == "premium" and r["viewer_label"] == "A" and r["age_bucket"] == "h06"
               for r in rows)
    assert all(r["capture_id"] == "capture" and r["capture_file"] == "capture.har" for r in rows)


def test_display_order_row_types_and_dedupe(har_path):
    result = parse(har_path)
    s1 = [r for r in result.rows if r["capture_session"] == 1]
    assert [(r["tweet_id"][-3:], r["row_type"], r["display_rank"], r["display_index"]) for r in s1] == [
        ("201", "reply", 1, 1),
        ("202", "nested_reply", None, 2),
        ("300", "promoted", None, 3),
        ("203", "reply", 2, 4),
        ("204", "reply", 3, 5),
        ("205", "reply", 4, 6),
        ("301", "promoted", None, 7),
        ("206", "nested_reply", None, 8),
    ]
    assert result.stats["duplicates"] == 1  # REPLY_A repeated on page 2
    assert result.stats["unavailable"] == 1  # the tombstone
    assert all(r["rank_is_absolute"] for r in s1)
    by_id = {r["tweet_id"]: r for r in s1}
    assert by_id["2000000000000000204"]["conversation_section"] == "LowQuality"
    assert by_id["2000000000000000202"]["module_position"] == 1
    assert by_id["2000000000000000300"]["is_promoted"] is True


def test_likes_session_ranks_restart(har_path):
    s2 = [r for r in parse(har_path).rows if r["capture_session"] == 2]
    assert [(r["tweet_id"][-3:], r["display_rank"]) for r in s2] == [("203", 1), ("201", 2)]


def test_reply_and_author_fields(har_path):
    s1 = by_tweet(parse(har_path).rows, 1)
    a, b, op_reply, late = (s1["2000000000000000201"], s1["2000000000000000203"],
                            s1["2000000000000000202"], s1["2000000000000000205"])
    assert a["author_is_blue_verified"] is True and b["author_is_blue_verified"] is False
    assert a["like_count"] == 50 and a["view_count"] == 900
    assert b["has_media"] is True  # unwrapped from TweetWithVisibilityResults
    assert a["in_reply_to_tweet_id"] == syn.FOCAL_ID
    assert a["created_at_utc"] == "2026-10-20T18:37:59.000Z"
    assert a["author_created_at_utc"] == "2012-10-04T05:22:25.000Z"
    assert a["author_followers"] == 500 and a["author_following"] == 5 and a["author_statuses"] == 100
    assert late["author_followers"] == 3  # legacy user layout
    assert op_reply["author_is_focal_author"] is True and a["author_is_focal_author"] is False
    assert op_reply["author_verified_type"] == "Business"
    assert op_reply["author_affiliate_label"] == "Example Clips Inc"
    assert a["author_id_hash"] == pseudonym(SALT, "x", "user", "1001")
    assert a["author_handle_hash"] == pseudonym(SALT, "x", "handle", "bluereplier")
    assert a["text"] is None


def test_thread_columns(har_path):
    row = parse(har_path).rows[0]
    assert row["thread_id"] == syn.ROOT_ID
    assert row["focal_tweet_id"] == syn.FOCAL_ID
    assert row["focal_author_followers"] == 55953
    assert row["focal_author_is_blue_verified"] is True
    assert row["focal_author_verified_type"] == "Business"
    assert row["focal_author_affiliate_label"] == "Example Clips Inc"
    assert row["focal_view_count"] == 40000 and row["focal_like_count"] == 900


def test_include_text(har_path):
    rows = parse(har_path, include_text=True).rows
    assert rows[0]["text"] == "blue reply"


def test_flags_override_capture_id_and_sort(har_path):
    rows = parse(har_path, capture_id="2000000000000000100_h06_likes_A", sort_order="likes").rows
    assert {r["capture_id"] for r in rows} == {"2000000000000000100_h06_likes_A"}
    assert {(r["sort_order"], r["sort_order_source"]) for r in rows} == {("likes", "flag")}


def test_capture_started_mid_thread(tmp_path):
    path = tmp_path / "mid.har"
    path.write_text(json.dumps(syn.har([
        syn.har_entry(syn.tweetdetail_url(cursor="abc"), syn.page_next())])))
    rows = parse(str(path)).rows
    assert all(r["rank_is_absolute"] is False for r in rows)
    assert rows[0]["display_rank"] == 1
    assert rows[0]["thread_id"] is None and rows[0]["focal_tweet_id"] == syn.FOCAL_ID


def test_no_ranking_mode_defaults_to_relevance(tmp_path):
    path = tmp_path / "plain.har"
    path.write_text(json.dumps(syn.har([
        syn.har_entry(syn.tweetdetail_url(ranking_mode=None, host="twitter.com"), syn.page_likes())])))
    rows = parse(str(path)).rows
    assert {(r["sort_order"], r["sort_order_source"]) for r in rows} == {("relevance", "default")}


def test_raw_response_json(tmp_path):
    path = tmp_path / "response.json"
    path.write_text(json.dumps(syn.page_top()))
    from datetime import datetime, timezone
    rows = parse(str(path), capture_time=datetime(2026, 10, 21, 15, 0, tzinfo=timezone.utc)).rows
    assert rows[0]["focal_tweet_id"] == syn.FOCAL_ID  # last tweet- entry
    assert rows[0]["rank_is_absolute"] is True
    assert rows[0]["sort_order"] == "unknown" and rows[0]["sort_order_source"] == "unknown"
    assert rows[0]["capture_time_utc"] == "2026-10-21T15:00:00.000Z"


# Schema


def test_rows_match_schema_types(har_path):
    rows = parse(har_path, include_text=True).rows
    py_types = {"string": str, "integer": int, "boolean": bool, "timestamp": str}
    for row in rows:
        assert tuple(row) == schema.COLUMN_NAMES
        for col in schema.COLUMNS:
            value = row[col.name]
            if value is None:
                assert col.nullable, col.name
                continue
            assert type(value) is py_types[col.type], col.name
            if col.enum:
                assert value in col.enum, col.name


def test_schema_files_are_in_sync():
    with open(SCHEMA_JSON, encoding="utf-8") as f:
        assert f.read() == schema.json_schema_text()
    with open(SCHEMA_DOC, encoding="utf-8") as f:
        doc = f.read()
    assert render_doc(doc) == doc
    for name in schema.COLUMN_NAMES:
        assert f"`{name}`" in doc


def test_csv_round_trip(har_path, tmp_path):
    out = tmp_path / "r.csv"
    main(["parse", har_path, "-o", str(out)])
    rows = list(csv.DictReader(out.open(encoding="utf-8")))
    assert tuple(rows[0]) == schema.COLUMN_NAMES
    assert rows[0]["is_promoted"] == "false" and rows[0]["text"] == ""


# Salt


def test_salt_file_created_private_and_reused(tmp_path, monkeypatch):
    monkeypatch.delenv(SALT_ENV)
    path = tmp_path / "cfg" / "hash_salt"
    first = load_salt(str(path))
    assert load_salt(str(path)) == first
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
    assert pseudonym(first, "x", "user", "1") != pseudonym(b"other", "x", "user", "1")


# Review fixes


def test_appended_module_items_continue_module_positions(har_path):
    s1 = by_tweet(parse(har_path).rows, 1)
    nested = s1["2000000000000000206"]
    assert nested["row_type"] == "nested_reply"
    assert nested["module_position"] == 1  # after REPLY_C at position 0
    assert nested["sort_index"] == "7000"
    assert nested["conversation_section"] == "HighQuality"


def test_unreadable_variables_do_not_restart_sessions(tmp_path):
    url = "https://x.com/i/api/graphql/AbC/TweetDetail"  # no variables (e.g. a POST)
    path = tmp_path / "post.har"
    path.write_text(json.dumps(syn.har([
        syn.har_entry(url, syn.page_top()),
        syn.har_entry(url, syn.page_next()),
    ])))
    rows = parse(str(path)).rows
    assert {r["capture_session"] for r in rows} == {1}
    assert [r["display_rank"] for r in rows if r["row_type"] == "reply"] == [1, 2, 3, 4]
    assert {(r["sort_order"], r["sort_order_source"]) for r in rows} == {("unknown", "unknown")}


def test_tweets_without_ids_are_skipped(tmp_path):
    no_id = syn.tweet("2000000000000000999", syn.FREE, reply_to=syn.FOCAL_ID)
    del no_id["rest_id"], no_id["legacy"]["id_str"]
    no_author = syn.tweet("2000000000000000998", syn.user(None, "Ghost"), reply_to=syn.FOCAL_ID)
    del no_author["legacy"]["user_id_str"]
    path = tmp_path / "ids.har"
    path.write_text(json.dumps(syn.har([syn.har_entry(syn.tweetdetail_url(), syn.body([
        syn.tweet_entry(syn.FOCAL, 9), syn.module("n", [no_id], 8), syn.module("m", [no_author], 7),
        syn.module("a", [syn.REPLY_A], 6)]))])))
    result = parse(str(path))
    assert [r["tweet_id"] for r in result.rows] == [syn.REPLY_A["rest_id"]]
    assert result.stats["unavailable"] == 1 and result.stats["no_author_id"] == 1


def test_har_with_other_extension_is_still_scrubbed(tmp_path, capsys):
    doc = syn.standard_har()
    doc["log"]["pages"] = [{"title": "x" * 10000}]  # pushes "entries" far into the file
    path = tmp_path / "capture.json"
    path.write_text(json.dumps(doc))
    out = tmp_path / "out.csv"
    assert main(["parse", str(path), "-o", str(out)]) == 0
    assert syn.SENTINEL not in out.read_text() + capsys.readouterr().err
    assert len(out.read_text().splitlines()) == 11


def test_long_fraction_timestamps_parse_everywhere():
    from twitterdata.timeutil import parse_iso_utc
    dt = parse_iso_utc("2026-10-21T13:33:13.1234567Z")
    assert dt.isoformat() == "2026-10-21T13:33:13.123456+00:00"
    assert parse_iso_utc("2026-10-21T08:33:13.1-05:00").hour == 13
    assert parse_iso_utc("nonsense") is None


def test_empty_salt_file_is_a_clean_error(har_path, tmp_path, monkeypatch, capsys):
    monkeypatch.delenv(SALT_ENV)
    salt = tmp_path / "salt"
    salt.write_text("")
    assert main(["parse", har_path, "-o", str(tmp_path / "o.csv"), "--salt-file", str(salt)]) == 2
    assert "hash salt" in capsys.readouterr().err


def test_inputs_with_same_name_are_refused(har_path, tmp_path):
    other = tmp_path / "sub"
    other.mkdir()
    twin = other / "capture.har"
    twin.write_text(open(har_path).read())
    assert main(["parse", har_path, str(twin), "-o", str(tmp_path / "o.csv")]) == 2
