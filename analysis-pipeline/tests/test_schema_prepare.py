import json
from pathlib import Path

import pandas as pd
import pytest

from replyanalysis.prepare import AnalysisConfig, Inputs, annotate, load_codes, select_sessions
from replyanalysis.schema import SchemaError, coerce, column_names, load_schema, read_reply_tables
from replyanalysis.synthetic import generate

REPO_SCHEMA = Path(__file__).resolve().parents[2] / "schema" / "reply_table.v1.json"


@pytest.fixture(scope="module")
def small():
    return generate(3, 5)


def _coerce(df):
    return coerce(df.astype(object).where(df.notna(), None))


def _structure(schema):
    return [(c["name"], c["type"], c["nullable"], tuple(c.get("enum") or ())) for c in schema["columns"]]


def test_bundled_schema_matches_repository_copy():
    if not REPO_SCHEMA.exists():
        pytest.skip("schema/reply_table.v1.json not found next to this package")
    repo = json.loads(REPO_SCHEMA.read_text())
    assert repo["version"] == load_schema()["version"]
    assert _structure(repo) == _structure(load_schema()), "copy schema/reply_table.v1.json into replyanalysis/data/"


def test_synthetic_rows_follow_schema(small):
    assert list(small["replies"].columns) == column_names()
    _coerce(small["replies"])


def test_missing_column_is_rejected(small):
    with pytest.raises(SchemaError, match="missing"):
        _coerce(small["replies"].drop(columns=["display_rank"]))


def test_enum_and_null_rules(small):
    bad = small["replies"].copy()
    bad.loc[0, "sort_order"] = "hot"
    with pytest.raises(SchemaError, match="sort_order"):
        _coerce(bad)
    bad = small["replies"].copy()
    bad.loc[0, "tweet_id"] = None
    with pytest.raises(SchemaError, match="tweet_id"):
        _coerce(bad)


def test_ids_stay_exact_strings(tmp_path, small):
    df = small["replies"].head(20).copy()
    df["tweet_id"] = "2112779086036599242"
    df["display_index"] = range(1, 21)
    df.to_csv(tmp_path / "a.csv", index=False)
    out = read_reply_tables([tmp_path])
    assert (out["tweet_id"] == "2112779086036599242").all()


def test_jsonl_and_duplicate_capture_guard(tmp_path, small):
    one = small["replies"][small["replies"].capture_id == small["replies"].capture_id.iloc[0]]
    with open(tmp_path / "a.jsonl", "w") as fh:
        for rec in one.to_dict("records"):
            fh.write(json.dumps({k: (None if pd.isna(v) else v) for k, v in rec.items()}) + "\n")
    assert len(read_reply_tables([tmp_path / "a.jsonl"])) == len(one)
    one.to_csv(tmp_path / "b.csv", index=False)
    with pytest.raises(SchemaError, match="loaded twice"):
        read_reply_tables([tmp_path / "a.jsonl", tmp_path / "b.csv"])


def _toy():
    """One capture: 4 top-level replies, one nested reply by the OP, one ad."""
    base = generate(1, 1)["replies"]
    rows = base[base.capture_id == base.capture_id.iloc[0]].head(6).copy().reset_index(drop=True)
    spec = [  # row_type, rank, module_position, premium, focal author
        ("reply", 1, 0, "true", "false"),
        ("nested_reply", None, 1, "false", "true"),
        ("reply", 2, 0, "false", "false"),
        ("promoted", None, 0, "true", "false"),
        ("reply", 3, 0, "true", "false"),
        ("reply", 4, 0, "false", "false"),
    ]
    for i, (rt, rank, mp, prem, op) in enumerate(spec):
        rows.loc[i, ["row_type", "display_rank", "module_position", "author_is_blue_verified", "author_is_focal_author",
                     "display_index", "is_promoted", "tweet_id"]] = [rt, rank, mp, prem, op, i + 1,
                                                                    "true" if rt == "promoted" else "false", str(100 + i)]
    return rows


def test_other_platform_rows_are_set_aside():
    rows = _toy()
    bsky = rows.copy()
    bsky["platform"] = "bluesky"
    bsky["capture_id"] = "bsky_3abc_h06_relevance_A"
    df = _coerce(pd.concat([rows, bsky], ignore_index=True))
    cfg = AnalysisConfig()
    inp = Inputs(replies=df)
    out, info = select_sessions(annotate(inp, cfg), inp, cfg)
    assert set(out.platform) == {"x"} and info["rows_from_other_platforms_set_aside"] == len(bsky)
    out, _ = select_sessions(annotate(inp, cfg), inp, AnalysisConfig(platform="bluesky"))
    assert set(out.platform) == {"bluesky"}


def test_rank_percentiles_modules_and_op_replies():
    df = annotate(Inputs(replies=_coerce(_toy())), AnalysisConfig())
    top = df[df.row_type == "reply"].set_index("tweet_id")
    assert top.loc["100", "rank_pct"] == 100 and top.loc["105", "rank_pct"] == 0
    assert top.loc["100", "tier_rank_pct"] == 100 and top.loc["104", "tier_rank_pct"] == 0
    assert top.loc["100", "op_replied"] == 1 and top.loc["102", "op_replied"] == 0
    assert df["module_id"].nunique() == 5  # 4 replies + 1 ad


def test_session_selection_and_viewer_fallback():
    rows = _toy()
    second = rows.copy()
    second["capture_session"] = 2
    late = rows.copy()
    late["capture_session"] = 3
    late["rank_is_absolute"] = "false"
    df = _coerce(pd.concat([rows, second, late], ignore_index=True))
    cfg = AnalysisConfig(viewer="Z")
    inp = Inputs(replies=df)
    out, info = select_sessions(annotate(inp, cfg), inp, cfg)
    assert set(out.capture_session) == {1}
    assert info["sessions_not_absolute"] == 1
    assert info["viewer"].startswith("all")


def test_codes_from_blindcode_jsonl(tmp_path):
    p = tmp_path / "adjudicated.jsonl"
    p.write_text("\n".join(json.dumps(r) for r in [
        {"uid": "1", "values": {"incivility": 0, "stance": "pro_stunt"}},
        {"uid": "1", "values": {"incivility": 1, "stance": "pro_stunt"}},
        {"uid": "2", "values": {"incivility": 0, "stance": "anti_stunt"}},
    ]))
    codes = load_codes(p).set_index("tweet_id")
    assert codes.loc["1", "incivility"] == 1  # latest record wins


def test_duplicate_code_rows_are_rejected(tmp_path):
    p = tmp_path / "codes.csv"
    p.write_text("uid,incivility\n1,0\n1,1\n")
    with pytest.raises(ValueError, match="adjudicated"):
        load_codes(p)


def test_mixed_iso_timestamps_parse(small):
    df = small["replies"].head(4).copy()
    df.loc[df.index[0], "created_at_utc"] = "2026-11-02T00:00:00Z"
    out = _coerce(df)
    assert out["created_at_utc"].notna().all()


def test_duplicate_author_rows_are_rejected(tmp_path, small):
    from replyanalysis.prepare import load_inputs
    small["replies"].to_csv(tmp_path / "r.csv", index=False)
    (tmp_path / "authors.csv").write_text("author_id_hash,motive\nabc,farmer\nabc,ideologue\n")
    with pytest.raises(ValueError, match="author_id_hash"):
        load_inputs([tmp_path / "r.csv"], authors=tmp_path / "authors.csv")
