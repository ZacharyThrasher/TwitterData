import csv
import json
import os
import re
from datetime import datetime, timezone

import pytest

import bluesky_fixtures as fx
from twitterdata import schema
from twitterdata.bluesky import cli as bluesky_cli
from twitterdata.bluesky.bundle import PROFILES, RESOLVE_HANDLE, THREAD, THREAD_OTHER, Bundle, load_bundle
from twitterdata.bluesky.client import BlueskyError, Client
from twitterdata.bluesky.collector import Collector, default_capture_id, parse_target
from twitterdata.bluesky.mapping import build_rows, parse_ts
from twitterdata.cli import main
from twitterdata.privacy import SALT_ENV, pseudonym

SALT = b"test-salt"
RELEVANCE = os.path.join(fx.FIXTURE_DIR, "thread_relevance.json")
RECENT = os.path.join(fx.FIXTURE_DIR, "thread_recent.json")
POST = "app.bsky.unspecced.defs#threadItemPost"


@pytest.fixture(autouse=True)
def isolated_salt(tmp_path, monkeypatch):
    monkeypatch.setenv(SALT_ENV, "test-salt")
    monkeypatch.setenv("HOME", str(tmp_path / "home"))


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def refuse(url, timeout):
        raise AssertionError(f"test tried to reach the network: {url}")
    monkeypatch.setattr("twitterdata.bluesky.client._http_get", refuse)


def rows_of(path, **kw):
    return build_rows(load_bundle(path), SALT, os.path.basename(path), **kw)


def check_schema(row):
    """Every column present, typed, nullable and enum-valid per schema v1."""
    assert list(row) == list(schema.COLUMN_NAMES)
    for col in schema.COLUMNS:
        value = row[col.name]
        if value is None:
            assert col.nullable, col.name
            continue
        if col.type == "integer":
            assert isinstance(value, int) and not isinstance(value, bool), col.name
        elif col.type == "boolean":
            assert isinstance(value, bool), col.name
        elif col.type == "timestamp":
            assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z", value), (col.name, value)
        else:
            assert isinstance(value, str), col.name
        if col.enum:
            assert value in col.enum, (col.name, value)


# Recorded fixtures: real AppView responses with identities swapped out.


@pytest.mark.parametrize("path", [RELEVANCE, RECENT])
def test_recorded_thread_maps_to_schema_v1(path):
    bundle = load_bundle(path)
    result = build_rows(bundle, SALT, os.path.basename(path))
    rows = result.rows
    main_items = [i for i in bundle.responses_for(THREAD)[0]["body"]["thread"] if i["depth"] > 0]
    other_items = bundle.responses_for(THREAD_OTHER)[0]["body"]["thread"]
    assert len(rows) == len(main_items) + len(other_items) == result.stats["rows"]
    for row in rows:
        check_schema(row)
        assert row["platform"] == "bluesky"
        assert row["viewer_type"] == "logged_out"
        assert row["sort_order_source"] == "request"
        assert row["rank_is_absolute"] is True
        # No paid tier, no ads, no view counts on Bluesky.
        assert row["author_is_blue_verified"] is False and row["focal_author_is_blue_verified"] is False
        assert row["is_promoted"] is False and row["row_type"] != "promoted"
        assert row["view_count"] is None and row["focal_view_count"] is None
        assert row["text"] is None
        assert row["author_followers"] is not None  # profiles were fetched
    assert [r["display_index"] for r in rows] == list(range(1, len(rows) + 1))
    ranks = [r["display_rank"] for r in rows if r["row_type"] == "reply"]
    assert ranks == list(range(1, len(ranks) + 1))
    assert all(r["display_rank"] is None for r in rows if r["row_type"] == "nested_reply")


def test_recorded_thread_keeps_api_order_and_modules():
    bundle = load_bundle(RELEVANCE)
    rows = build_rows(bundle, SALT, "x.json").rows
    items = [i for i in bundle.responses_for(THREAD)[0]["body"]["thread"] if i["depth"] > 0]
    items += bundle.responses_for(THREAD_OTHER)[0]["body"]["thread"]
    assert [r["tweet_id"] for r in rows] == [i["uri"] for i in items]
    seen = set()
    module_root = None
    for row, item in zip(rows, items):
        assert (row["row_type"] == "reply") == (item["depth"] == 1)
        if item["depth"] == 1:
            assert row["module_position"] == 0
            assert row["in_reply_to_tweet_id"] == row["focal_tweet_id"]
            module_root = row["tweet_id"]
        else:
            assert row["module_position"] > 0 and module_root is not None
            assert row["in_reply_to_tweet_id"] in seen  # nested replies follow their parent
        seen.add(row["tweet_id"])


def test_hidden_fold_comes_after_main_list():
    rows = rows_of(RELEVANCE).rows
    sections = [r["conversation_section"] for r in rows]
    first_other = sections.index("OtherReplies")
    assert set(sections[:first_other]) == {"Main"}
    assert set(sections[first_other:]) == {"OtherReplies"}
    assert {r["page_index"] for r in rows[first_other:]} == {1}
    assert all(r["row_type"] == "reply" for r in rows[first_other:])


def test_recent_sort_is_newest_indexed_first_and_relevance_is_not():
    # Bluesky's "newest" orders by when the AppView indexed the post, not by the
    # client-set createdAt (which can be backdated), so check indexed_at_utc.
    def top_level_times(path):
        result = rows_of(path)
        return [e["indexed_at_utc"] for r, e in zip(result.rows, result.extras)
                if r["row_type"] == "reply" and r["conversation_section"] == "Main"]

    recent = top_level_times(RECENT)
    assert recent == sorted(recent, reverse=True)
    relevance = top_level_times(RELEVANCE)
    assert relevance != sorted(relevance, reverse=True)
    assert load_bundle(RECENT).responses_for(THREAD)[0]["params"]["sort"] == "newest"
    assert load_bundle(RELEVANCE).responses_for(THREAD)[0]["params"]["sort"] == "top"


def test_authors_are_hashed_with_the_parser_scheme():
    bundle = load_bundle(RELEVANCE)
    rows = build_rows(bundle, SALT, "x.json").rows
    first = bundle.responses_for(THREAD)[0]["body"]["thread"][1]["value"]["post"]["author"]
    assert rows[0]["author_id_hash"] == pseudonym(SALT, "bluesky", "user", first["did"])
    assert rows[0]["author_handle_hash"] == pseudonym(SALT, "bluesky", "handle", first["handle"].lower())
    # Same salt, different platform namespace: a Bluesky hash never equals an X hash.
    assert rows[0]["author_id_hash"] != pseudonym(SALT, "x", "user", first["did"])
    blob = json.dumps(rows)
    assert first["did"] not in blob.replace(rows[0]["tweet_id"], "")
    assert "fixture.test" not in blob


def test_text_is_opt_in():
    assert all(r["text"] is None for r in rows_of(RELEVANCE).rows)
    texts = [r["text"] for r in rows_of(RELEVANCE, include_text=True).rows]
    assert all(t and t.startswith("fixture text") for t in texts)


def test_fixtures_hold_no_real_identities():
    for path in (RELEVANCE, RECENT):
        raw = open(path, encoding="utf-8").read()
        dids = set(re.findall(r"did:[a-z]+:[A-Za-z0-9.:%-]+", raw))
        assert dids <= {fx.OFFICIAL_MODERATION} | {d for d in dids if d.startswith("did:plc:fx")}
        handles = set(re.findall(r'"handle": "([^"]+)"', raw))
        assert all(h.endswith(".fixture.test") or h == "handle.invalid" for h in handles)
        for key in ("displayName", "avatar", "description"):
            assert f'"{key}"' not in raw
        urls = re.findall(r"https?://[^\s\"]+", raw)
        assert all(re.fullmatch(r"https://(static\.klipy\.com|media\.tenor\.com)/redacted"
                                r"|https://bsky\.app/profile/user\d+\.fixture\.test/post/fx\d+", u) for u in urls), urls


# Synthetic edge cases.


def _author(n, **extra):
    return {"did": f"did:plc:{'a' * 23}{n}", "handle": f"User{n}.Example.test", "labels": [], **extra}


def _post(n, parent=None, author=1, **extra):
    uri = f"at://did:plc:{'a' * 23}{author}/app.bsky.feed.post/p{n}"
    record = {"$type": "app.bsky.feed.post", "createdAt": "2026-10-20T10:00:00Z", "langs": ["en"], "text": f"t{n}"}
    if parent:
        record["reply"] = {"root": {"uri": "at://did:plc:aaaaaaaaaaaaaaaaaaaaaaa1/app.bsky.feed.post/p0"},
                           "parent": {"uri": parent}}
    post = {"uri": uri, "author": _author(author), "record": record, "likeCount": n, "replyCount": 0,
            "repostCount": 0, "quoteCount": 0, "bookmarkCount": 0, "labels": []}
    post.update(extra)
    return post


def _item(depth, post, **flags):
    return {"uri": post["uri"], "depth": depth, "value": {"$type": POST, "post": post, **flags}}


def synthetic_bundle():
    focal = _post(0, author=1, replyCount=9)
    a = _post(1, focal["uri"], author=2, embed={"$type": "app.bsky.embed.recordWithMedia#view"})
    a1 = _post(2, a["uri"], author=1)  # focal author answers
    a2 = _post(3, a1["uri"], author=3, embed={"$type": "app.bsky.embed.external#view",
                                              "external": {"uri": "https://media.tenor.com/x.gif"}})
    b = _post(4, focal["uri"], author=4, labels=[
        {"src": "did:plc:ar7c4by46qjdydhdevvrndac", "val": "rude"},
        {"src": _author(4)["did"], "val": "sexual"},
        {"src": "did:plc:otherlabelerxxxxxxxxxxxx", "val": "spam", "neg": False},
        {"src": "did:plc:otherlabelerxxxxxxxxxxxx", "val": "gone", "neg": True},
    ])
    b["record"]["createdAt"] = "2026-10-20T12:00:00.1234567+02:00"
    b["author"]["verification"] = {"verifiedStatus": "valid", "trustedVerifierStatus": "none"}
    c = _post(5, focal["uri"], author=5, embed={"$type": "app.bsky.embed.external#view",
                                                "external": {"uri": "https://news.example/a"}})
    hidden = _post(6, focal["uri"], author=6)
    other = _post(7, focal["uri"], author=7)
    thread = {"hasOtherReplies": True, "thread": [
        {"uri": "at://parent", "depth": -1, "value": {"$type": POST, "post": _post(99, author=9)}},
        _item(0, focal, opThread=True),
        _item(1, a), _item(2, a1, opThread=True), _item(3, a2, moreReplies=4),
        {"uri": "at://gone", "depth": 1, "value": {"$type": "app.bsky.unspecced.defs#threadItemNotFound"}},
        _item(1, b),
        {"uri": "at://optout", "depth": 2, "value": {"$type": "app.bsky.unspecced.defs#threadItemNoUnauthenticated"}},
        _item(1, c),
        _item(1, a),  # duplicate
    ]}
    other_body = {"thread": [_item(1, hidden, hiddenByThreadgate=True), _item(1, other)]}
    profiles = {"profiles": [{"did": _author(n)["did"], "followersCount": 10 * n, "followsCount": n,
                              "postsCount": 100 + n, "createdAt": "2024-01-01T00:00:00.000Z",
                              "associated": {"labeler": n == 5},
                              **({"verification": {"verifiedStatus": "none", "trustedVerifierStatus": "valid"}}
                                 if n == 1 else {})}
                             for n in range(1, 8)]}
    t = "2026-10-21T12:00:00.000001Z"
    return Bundle(anchor_uri=focal["uri"], bluesky_sort="top", sort_order="relevance", capture_id="syn",
                  age_bucket="h06", viewer_label="A", responses=[
                      {"endpoint": THREAD, "params": {}, "status": 200, "received_at": t, "body": thread},
                      {"endpoint": THREAD_OTHER, "params": {}, "status": 200, "received_at": t, "body": other_body},
                      {"endpoint": PROFILES, "params": {}, "status": 200, "received_at": t, "body": profiles},
                  ])


def test_synthetic_edge_cases():
    result = build_rows(synthetic_bundle(), SALT, "syn.json")
    rows = {r["tweet_id"].rsplit("/", 1)[-1]: r for r in result.rows}
    extras = {e["tweet_id"].rsplit("/", 1)[-1]: e for e in result.extras}
    for r in result.rows:
        check_schema(r)
    assert list(rows) == ["p1", "p2", "p3", "p4", "p5", "p6", "p7"]
    assert result.stats["unavailable"] == 2 and result.stats["duplicates"] == 1
    assert result.stats["parents_skipped"] == 1

    assert [rows[k]["display_rank"] for k in rows] == [1, None, None, 2, 3, 4, 5]
    assert [rows[k]["module_position"] for k in rows] == [0, 1, 2, 0, 0, 0, 0]
    assert rows["p1"]["is_quote"] and rows["p1"]["has_media"]
    assert rows["p3"]["has_media"] and not rows["p3"]["is_quote"]  # GIF picker link counts as media
    assert not rows["p5"]["has_media"]  # ordinary link card does not
    assert rows["p2"]["author_is_focal_author"] and not rows["p1"]["author_is_focal_author"]
    assert rows["p4"]["created_at_utc"] == "2026-10-20T10:00:00.123Z"
    assert rows["p4"]["author_verified_type"] == "BlueskyVerified"
    assert rows["p1"]["focal_author_verified_type"] == "BlueskyTrustedVerifier"
    assert rows["p1"]["focal_author_followers"] == 10 and rows["p1"]["focal_reply_count"] == 9
    assert rows["p6"]["conversation_section"] == "HiddenByAuthor"
    assert rows["p7"]["conversation_section"] == "OtherReplies"
    assert rows["p1"]["capture_time_utc"] == "2026-10-21T12:00:00.000Z"
    assert rows["p1"]["author_handle_hash"] == pseudonym(SALT, "bluesky", "handle", "user2.example.test")
    assert rows["p1"]["age_bucket"] == "h06" and rows["p1"]["viewer_label"] == "A"

    assert extras["p4"]["post_labels"] == "bsky:rude;other:spam;self:sexual"
    assert extras["p3"]["more_replies"] == 4 and extras["p3"]["depth"] == 3
    assert extras["p2"]["op_thread"] is True
    assert extras["p5"]["author_is_labeler"] is True
    assert extras["p6"]["hidden_by_threadgate"] is True


def test_descendants_of_skipped_replies_are_skipped():
    b = synthetic_bundle()
    thread = b.responses[0]["body"]["thread"]
    # Make reply p1 unavailable: its descendants p2 and p3 must not be attached to another module.
    thread[2]["value"] = {"$type": "app.bsky.unspecced.defs#threadItemBlocked"}
    result = build_rows(b, SALT, "syn.json")
    keys = [r["tweet_id"].rsplit("/", 1)[-1] for r in result.rows]
    assert keys == ["p4", "p5", "p1", "p6", "p7"]  # p1 still appears where the API listed it again
    assert result.stats["orphans_skipped"] == 2
    assert [r["module_position"] for r in result.rows] == [0, 0, 0, 0, 0]


def test_bad_created_at_keeps_the_row():
    b = synthetic_bundle()
    b.responses[0]["body"]["thread"][2]["value"]["post"]["record"]["createdAt"] = "2024-02-30T00:00:00Z"
    rows = build_rows(b, SALT, "syn.json").rows
    assert rows[0]["created_at_utc"] is None and len(rows) == 7


def test_focal_post_hidden_from_logged_out_viewers_is_an_error():
    b = synthetic_bundle()
    b.responses[0]["body"]["thread"][1]["value"] = {"$type": "app.bsky.unspecced.defs#threadItemNoUnauthenticated"}
    with pytest.raises(ValueError, match="threadItemNoUnauthenticated"):
        build_rows(b, SALT, "syn.json")


def test_parse_ts_handles_bluesky_variants():
    assert parse_ts("2026-10-20T10:00:00Z") == datetime(2026, 10, 20, 10, tzinfo=timezone.utc)
    assert parse_ts("2026-10-20T10:00:00.5-01:30").minute == 30
    assert parse_ts("2024-02-30T00:00:00Z") is None  # client-set nonsense must not abort a capture
    assert parse_ts("0001-01-01T00:00:00+01:00") is None
    assert parse_ts("2026-10-20T10:00:00") == datetime(2026, 10, 20, 10, tzinfo=timezone.utc)
    assert parse_ts("yesterday") is None and parse_ts(None) is None


# Client: pacing and retries.


class FakeClock:
    def __init__(self):
        self.t = 0.0
        self.sleeps = []

    def clock(self):
        return self.t

    def sleep(self, s):
        self.sleeps.append(s)
        self.t += s


def fake_client(answers, **kw):
    clock = FakeClock()
    calls = []

    def http_get(url, timeout):
        calls.append(url)
        answer = answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer

    client = Client(http_get=http_get, sleep=clock.sleep, clock=clock.clock, **kw)
    return client, clock, calls


def test_client_paces_requests():
    ok = (200, {}, b'{"ok": true}')
    client, clock, calls = fake_client([ok, ok, ok], min_interval=1.5)
    for _ in range(3):
        client.get("x.y", {"a": ["1", "2"]})
    assert clock.sleeps == [1.5, 1.5]
    assert calls[0].endswith("/xrpc/x.y?a=1&a=2")


def test_client_retries_rate_limits_and_server_errors():
    import urllib.error
    answers = [(429, {"Retry-After": "7"}, b""), (503, {}, b""), urllib.error.URLError("down"),
               (200, {}, b'{"did": "d"}')]
    client, clock, _ = fake_client(answers, min_interval=0)
    assert client.get("x.y", {}).body == {"did": "d"}
    assert clock.sleeps == [7.0, 4.0, 8.0]
    assert client.requests == 4


def test_client_raises_api_errors_without_retrying():
    client, _, calls = fake_client([(400, {}, b'{"error": "InvalidRequest", "message": "bad anchor"}')])
    with pytest.raises(BlueskyError, match="bad anchor"):
        client.get("x.y", {})
    assert len(calls) == 1


def test_client_gives_up_after_max_retries():
    client, _, calls = fake_client([(429, {}, b"")] * 3, min_interval=0, max_retries=2)
    with pytest.raises(BlueskyError, match="HTTP 429"):
        client.get("x.y", {})
    assert len(calls) == 3


# Collector: request plan, replayed from the recorded fixture.


class ReplayClient:
    """Answers each endpoint from a recorded bundle, and logs the requests made."""

    def __init__(self, bundle_path, **_):
        self.bundle = load_bundle(bundle_path)
        self.calls = []
        self.requests = 0

    def now(self):
        return datetime(2026, 10, 21, tzinfo=timezone.utc)

    def get(self, endpoint, params):
        from twitterdata.bluesky.client import Response
        self.calls.append((endpoint, params))
        self.requests += 1
        recorded = [r for r in self.bundle.responses if r["endpoint"] == endpoint]
        if endpoint == PROFILES:
            wanted = set(params["actors"])
            profiles = [p for r in recorded for p in r["body"]["profiles"] if p["did"] in wanted]
            body = {"profiles": profiles}
        else:
            body = recorded[0]["body"]
        return Response(endpoint, params, 200, datetime(2026, 10, 21, tzinfo=timezone.utc), body)


def test_collector_request_plan():
    client = ReplayClient(RELEVANCE)
    target = "https://bsky.app/profile/User1.Fixture.test/post/fx00000000001"
    bundle = Collector(client).collect(target, "relevance", age_bucket="h24", viewer_label="A")
    endpoints = [c[0] for c in client.calls]
    n_profiles = endpoints.count(PROFILES)
    assert endpoints == [RESOLVE_HANDLE, THREAD, THREAD_OTHER] + [PROFILES] * n_profiles
    assert client.calls[0][1] == {"handle": "user1.fixture.test"}
    thread_params = client.calls[1][1]
    assert thread_params["sort"] == "top" and thread_params["above"] == "false"
    assert thread_params["below"] == 20 and thread_params["branchingFactor"] == 100
    batches = [c[1]["actors"] for c in client.calls if c[0] == PROFILES]
    assert all(len(b) <= 25 for b in batches)
    assert len(sum(batches, [])) == len(set(sum(batches, [])))
    assert bundle.capture_id == "bsky_fx00000000001_h24_relevance_A"
    assert bundle.anchor_uri.startswith("at://did:plc:fx")
    rows = build_rows(bundle, SALT, "b.json").rows
    assert len(rows) == len(rows_of(RELEVANCE).rows)


def test_collector_reuses_profiles_across_sorts():
    client = ReplayClient(RELEVANCE)
    collector = Collector(client)
    anchor = load_bundle(RELEVANCE).anchor_uri
    collector.collect(anchor, "relevance")
    first = [c[0] for c in client.calls].count(PROFILES)
    client.calls.clear()
    bundle = collector.collect(anchor, "recent")
    assert [c[0] for c in client.calls].count(PROFILES) == 0 and first > 0
    rows = build_rows(bundle, SALT, "b.json").rows
    assert all(r["author_followers"] is not None for r in rows)


def test_collector_options_skip_fold_and_profiles():
    client = ReplayClient(RELEVANCE)
    anchor = load_bundle(RELEVANCE).anchor_uri
    Collector(client, include_other=False, include_profiles=False).collect(anchor, "recent")
    assert [c[0] for c in client.calls] == [THREAD]  # did-based URI needs no handle lookup
    assert client.calls[0][1]["sort"] == "newest"
    with pytest.raises(ValueError):
        Collector(client).collect(anchor, "likes")
    with pytest.raises(ValueError):
        Collector(client, below=21)


@pytest.mark.parametrize("target,expected", [
    ("https://bsky.app/profile/alice.bsky.social/post/3abc", ("alice.bsky.social", "3abc")),
    ("https://bsky.app/profile/did:plc:xyz/post/3abc/", ("did:plc:xyz", "3abc")),
    ("https://bsky.app/profile/alice.test/post/3abc?ref=x", ("alice.test", "3abc")),
    ("at://did:plc:xyz/app.bsky.feed.post/3abc", ("did:plc:xyz", "3abc")),
])
def test_parse_target(target, expected):
    assert parse_target(target) == expected


def test_parse_target_rejects_other_urls():
    with pytest.raises(ValueError):
        parse_target("https://x.com/someone/status/1")


def test_default_capture_id():
    uri = "at://did:plc:x/app.bsky.feed.post/3abc"
    assert default_capture_id(uri, "recent", None, None) == "bsky_3abc_recent"
    assert default_capture_id(uri, "relevance", "h06", "A") == "bsky_3abc_h06_relevance_A"


# CLI.


def test_cli_parse_writes_table_and_extras(tmp_path, capsys):
    out = tmp_path / "out" / "bsky.csv"
    assert main(["bluesky", "parse", RELEVANCE, RECENT, "-o", str(out)]) == 0
    with open(out, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert list(rows[0]) == list(schema.COLUMN_NAMES)
    assert {r["capture_id"] for r in rows} == {"fixture_relevance", "fixture_recent"}
    assert {r["capture_file"] for r in rows} == {"thread_relevance.json", "thread_recent.json"}
    with open(tmp_path / "out" / "bsky.bluesky_extras.csv", encoding="utf-8") as f:
        extras = list(csv.DictReader(f))
    assert len(extras) == len(rows)
    assert "hidden fold" in capsys.readouterr().err


def test_cli_collect_with_replayed_api(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(bluesky_cli, "Client", lambda **kw: ReplayClient(RELEVANCE, **kw))
    out = tmp_path / "bsky.jsonl"
    raw = tmp_path / "raw"
    target = "https://bsky.app/profile/user1.fixture.test/post/fx00000000001"
    code = main(["bluesky", "collect", target, "--sort", "relevance", "--sort", "recent", "--raw-dir", str(raw),
                 "-o", str(out), "--extras", "none", "--include-text"])
    assert code == 0
    rows = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]
    assert {r["sort_order"] for r in rows} == {"relevance", "recent"}
    assert all(r["text"] for r in rows)
    bundles = sorted(os.listdir(raw))
    assert len(bundles) == 2 and all(b.startswith("bsky_fx00000000001_") for b in bundles)
    assert {r["capture_file"] for r in rows} == set(bundles)
    assert not (tmp_path / "bsky.bluesky_extras.csv").exists()


def test_cli_collect_rejects_capture_id_for_many(tmp_path):
    assert main(["bluesky", "collect", "at://did:plc:x/app.bsky.feed.post/a", "--sort", "relevance",
                 "--sort", "recent", "--capture-id", "c", "-o", str(tmp_path / "o.csv")]) == 2


def test_cli_parse_refuses_to_overwrite_a_bundle(tmp_path):
    bundle = tmp_path / "b.json"
    bundle.write_text(open(RELEVANCE, encoding="utf-8").read(), encoding="utf-8")
    assert main(["bluesky", "parse", str(bundle), "-o", str(bundle)]) == 2
    assert load_bundle(str(bundle)).anchor_uri


def test_cli_collect_failure_leaves_old_output(tmp_path, monkeypatch):
    class Down(ReplayClient):
        def get(self, endpoint, params):
            raise BlueskyError("AppView down")

    monkeypatch.setattr(bluesky_cli, "Client", lambda **kw: Down(RELEVANCE, **kw))
    out = tmp_path / "o.csv"
    out.write_text("previous run\n", encoding="utf-8")
    assert main(["bluesky", "collect", "at://did:plc:x/app.bsky.feed.post/a", "-o", str(out),
                 "--raw-dir", str(tmp_path / "raw")]) == 1
    assert out.read_text(encoding="utf-8") == "previous run\n"


def test_cli_reports_bad_salt_file(tmp_path, monkeypatch):
    monkeypatch.delenv(SALT_ENV)
    empty = tmp_path / "salt"
    empty.write_text("", encoding="utf-8")
    assert main(["bluesky", "parse", RELEVANCE, "-o", str(tmp_path / "o.csv"), "--salt-file", str(empty)]) == 2
