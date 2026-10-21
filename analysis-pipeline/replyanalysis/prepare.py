"""Turn reply tables plus labels into analysis frames.

Inputs (only the reply tables are required):

- reply tables: parser output, schema v1, one file per capture or many.
- reply codes: one row per reply, keyed by `tweet_id` (or `uid` when the
  blind coding tool was fed tweet ids as uids). Columns such as `incivility`,
  `attacks_op`, `stance`, `toxicity`, `pushback`.
- threads: the sampling tracker's `threads.csv` (topic, account type,
  poster politics, posted time).
- root codes: one row per thread (`thread_id`), with `outrage_framing`,
  `targeted_insult` and optionally `poster_motive`.
- author codes: one row per `author_id_hash`, with optional `motive`,
  `account_based_in`, `claimed_location`, `political_lean`.
- captures: the tracker's `captures.csv`, used only to set aside late captures.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from .schema import read_reply_tables

CAPTURE_ID_RE = re.compile(r"^(?P<thread>\d+)_(?P<age>h\d{2})_(?P<sort>relevance|recent|likes)_(?P<viewer>.+)$")

LARGE_ROOT_FOLLOWERS = 250_000  # Grok reply-scoring threshold in X's 2026 code (mechanics.md section 2c)


@dataclass
class AnalysisConfig:
    platform: str = "x"  # never mix platforms in one model; run Bluesky separately as the comparison
    main_sort: str = "relevance"
    main_age: str = "h06"
    viewer: str | None = "A"  # None keeps every viewer; "A" falls back to all when no row has label A
    large_root_followers: int = LARGE_ROOT_FOLLOWERS
    incivility_col: str = "incivility"
    toxicity_col: str = "toxicity"
    stance_col: str = "stance"
    pushback_col: str = "pushback"
    attacks_op_col: str = "attacks_op"
    second_language: str = "es"
    top_k: int = 10
    rude_top_k: int = 3
    bootstrap: int = 2000
    seed: int = 20261021
    alpha: float = 0.05
    include_late: bool = False
    min_confirmatory_threads: int = 100  # pre-registration section 6, "Minimum" rule
    regime_break_date: str = "2026-01-17"
    pod_window_seconds: int = 60
    pod_min_threads: int = 3
    pod_permutations: int = 200
    pod_alpha: float = 0.01

    def to_dict(self) -> dict:
        return dict(self.__dict__)


@dataclass
class Inputs:
    replies: pd.DataFrame
    codes: pd.DataFrame | None = None
    threads: pd.DataFrame | None = None
    root_codes: pd.DataFrame | None = None
    authors: pd.DataFrame | None = None
    captures: pd.DataFrame | None = None
    notes: list[str] = field(default_factory=list)


# ---------------------------------------------------------------- loading


def _read_csv_text(path: str | Path) -> pd.DataFrame:
    return pd.read_csv(path, dtype=str, keep_default_na=False, na_values=[""])


def load_codes(path: str | Path, key: str | None = None) -> pd.DataFrame:
    """Reply codes from a CSV, or the latest record per uid from a blindcode JSONL file."""
    path = Path(path)
    if path.suffix.lower() == ".jsonl":
        latest: dict[str, dict] = {}
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rec = json.loads(line)
                latest[str(rec["uid"])] = {"tweet_id": str(rec["uid"]), **rec.get("values", {})}
        df = pd.DataFrame(list(latest.values()))
    else:
        df = _read_csv_text(path)
    key = key or ("tweet_id" if "tweet_id" in df.columns else "uid")
    if key not in df.columns:
        raise ValueError(f"{path}: no '{key}' column to join codes on")
    df = df.rename(columns={key: "tweet_id"})
    df["tweet_id"] = df["tweet_id"].astype(str)
    if df["tweet_id"].duplicated().any():
        raise ValueError(f"{path}: more than one code row for some tweet ids; pass the adjudicated file")
    return _numeric_where_possible(df, keep=("tweet_id",))


def _numeric_where_possible(df: pd.DataFrame, keep=()) -> pd.DataFrame:
    for col in df.columns:
        if col in keep:
            continue
        converted = pd.to_numeric(df[col], errors="coerce")
        if converted.notna().sum() == df[col].notna().sum() and df[col].notna().any():
            df[col] = converted
    return df


def load_inputs(
    reply_paths: list[str | Path],
    codes: str | Path | None = None,
    codes_key: str | None = None,
    threads: str | Path | None = None,
    root_codes: str | Path | None = None,
    authors: str | Path | None = None,
    captures: str | Path | None = None,
) -> Inputs:
    inp = Inputs(replies=read_reply_tables(reply_paths))
    if codes:
        inp.codes = load_codes(codes, codes_key)
    if threads:
        inp.threads = _numeric_where_possible(_read_csv_text(threads), keep=("thread_id",))
    if root_codes:
        inp.root_codes = _numeric_where_possible(_read_csv_text(root_codes), keep=("thread_id",))
    if authors:
        inp.authors = _numeric_where_possible(_read_csv_text(authors), keep=("author_id_hash",))
    if captures:
        inp.captures = _read_csv_text(captures)
    return inp


# ---------------------------------------------------------------- derived columns


def _rank_height(rank: pd.Series, n: pd.Series) -> pd.Series:
    """Rank as a percentile of height: 100 = top of the list, 0 = bottom."""
    out = 100.0 * (1.0 - (rank - 1) / (n - 1))
    return out.where(n > 1)


def annotate(inp: Inputs, cfg: AnalysisConfig) -> pd.DataFrame:
    """All rows, with study ids, module ids, rank percentiles and joined labels."""
    df = inp.replies.copy()
    parsed = df["capture_id"].astype(str).str.extract(CAPTURE_ID_RE)
    df["study_thread_id"] = parsed["thread"].fillna(df["focal_tweet_id"].astype(str))
    df["age_bucket"] = df["age_bucket"].fillna(parsed["age"])
    df["viewer_label"] = df["viewer_label"].fillna(parsed["viewer"])
    df["session_key"] = df["capture_id"].astype(str) + "#" + df["capture_session"].astype(str)

    df = df.sort_values(["session_key", "display_index"]).reset_index(drop=True)
    df["module_id"] = df["session_key"] + ":" + (df["module_position"] == 0).groupby(df["session_key"]).cumsum().astype(str)

    nested_op = df[(df["row_type"] == "nested_reply") & df["author_is_focal_author"].fillna(False)]
    df["op_replied"] = df["module_id"].isin(set(nested_op["module_id"])).astype(int)

    df["premium"] = df["author_is_blue_verified"].astype("Float64")
    df["org_verified"] = df["author_verified_type"].notna().astype(int)
    age_h = (df["capture_time_utc"] - df["created_at_utc"]).dt.total_seconds() / 3600.0
    df["reply_age_h"] = age_h
    df["log_age"] = np.log(age_h.clip(lower=0.05))
    df["log_likes"] = np.log1p(df["like_count"].astype("Float64"))
    df["log_views"] = np.log1p(df["view_count"].astype("Float64"))
    df["log_followers"] = np.log1p(df["author_followers"].astype("Float64"))
    if df["text"].notna().any():
        df["log_text_len"] = np.log1p(df["text"].str.len().astype("Float64"))
    df["large_root"] = (df["focal_author_followers"] >= cfg.large_root_followers).astype("Float64")
    df["second_lang"] = (df["lang"] == cfg.second_language).astype("Float64")
    # X: LowQuality / AbusiveQuality; Bluesky: the "other replies" fold.
    df["below_fold"] = df["conversation_section"].isin(
        ["LowQuality", "AbusiveQuality", "OtherReplies", "HiddenByAuthor"]).astype(int)

    if inp.codes is not None:
        clash = [c for c in inp.codes.columns if c in df.columns and c != "tweet_id"]
        codes = inp.codes.rename(columns={c: f"code_{c}" for c in clash})
        df = df.merge(codes, on="tweet_id", how="left")
        if clash:
            inp.notes.append(f"code columns renamed to avoid clashes with the reply table: {clash}")
    if inp.authors is not None:
        df = df.merge(inp.authors, on="author_id_hash", how="left", suffixes=("", "_author"))

    # Within-session rank percentiles, top-level organic replies only.
    top = df["row_type"] == "reply"
    grp = df[top].groupby("session_key")
    df.loc[top, "n_in_session"] = grp["display_rank"].transform("count")
    df.loc[top, "rank_pct"] = _rank_height(df.loc[top, "display_rank"], df.loc[top, "n_in_session"])
    tier = df[top & df["premium"].notna()]
    tier_rank = tier.groupby(["session_key", "premium"])["display_rank"].rank(method="first")
    tier_n = tier.groupby(["session_key", "premium"])["display_rank"].transform("count")
    df.loc[tier.index, "tier_rank_pct"] = _rank_height(tier_rank, tier_n)
    return df


def select_sessions(df: pd.DataFrame, inp: Inputs, cfg: AnalysisConfig) -> tuple[pd.DataFrame, dict]:
    """One session per capture: the first that starts at the top of the thread."""
    info: dict = {"platform": cfg.platform}
    other = df["platform"] != cfg.platform
    if other.any():
        info["rows_from_other_platforms_set_aside"] = int(other.sum())
        df = df[~other]
    if df.empty:
        raise ValueError(f"no rows with platform = {cfg.platform}")
    absolute = df[df["rank_is_absolute"].fillna(False)]
    info["sessions_total"] = int(df["session_key"].nunique())
    info["sessions_not_absolute"] = int(info["sessions_total"] - absolute["session_key"].nunique())
    first = absolute.groupby("capture_id")["capture_session"].transform("min")
    out = absolute[absolute["capture_session"] == first]
    info["sessions_used"] = int(out["session_key"].nunique())

    if inp.captures is not None and "status" in inp.captures.columns and not cfg.include_late:
        late = set(inp.captures.loc[inp.captures["status"] == "late", "capture_id"].astype(str))
        before = out["capture_id"].nunique()
        out = out[~out["capture_id"].isin(late)]
        info["late_captures_set_aside"] = int(before - out["capture_id"].nunique())

    if cfg.viewer is not None:
        if (out["viewer_label"] == cfg.viewer).any():
            out = out[out["viewer_label"] == cfg.viewer]
            info["viewer"] = cfg.viewer
        else:
            info["viewer"] = "all (no rows carry the configured viewer label)"
    else:
        info["viewer"] = "all"
    return out, info


def main_frame(sessions: pd.DataFrame, cfg: AnalysisConfig, sort: str | None = None, age: str | None = None) -> pd.DataFrame:
    """Top-level organic replies in one sort and age bucket (default: the pre-registered 6h Relevance)."""
    sort = sort or cfg.main_sort
    age = age or cfg.main_age
    m = sessions[(sessions["row_type"] == "reply") & (sessions["sort_order"] == sort) & (sessions["age_bucket"] == age)]
    return m.copy()


def thread_frame(sessions: pd.DataFrame, inp: Inputs, cfg: AnalysisConfig) -> pd.DataFrame:
    """One row per study thread for the poster-level tests (O1, O2, T9), from the 24h capture."""
    h24 = sessions[sessions["age_bucket"] == "h24"].copy()
    if h24.empty:
        return pd.DataFrame()
    order = {cfg.main_sort: 0, "likes": 1, "recent": 2}
    h24["_pref"] = h24["sort_order"].map(order).fillna(9)
    h24 = h24.sort_values(["study_thread_id", "_pref", "capture_time_utc"])
    t = h24.groupby("study_thread_id").first()[
        ["focal_view_count", "focal_author_followers", "focal_author_is_blue_verified", "focal_author_affiliate_label", "lang"]
    ].reset_index()
    t = t.rename(columns={"study_thread_id": "thread_id", "lang": "first_reply_lang"})
    t["thread_id"] = t["thread_id"].astype(str)
    views = t["focal_view_count"].astype("Float64")
    foll = t["focal_author_followers"].astype("Float64")
    t["log_views_per_follower"] = np.log(views.where(views > 0) / foll.where(foll > 0)).astype(float)
    t["log_root_followers"] = np.log1p(foll).astype(float)
    t["large_account"] = (foll >= cfg.large_root_followers).astype(float)
    t["poster_premium"] = t["focal_author_is_blue_verified"].astype("Float64").astype(float)
    if inp.threads is not None:
        meta = inp.threads.copy()
        meta["thread_id"] = meta["thread_id"].astype(str)
        if "posted_utc" in meta.columns:
            hour = pd.to_datetime(meta["posted_utc"], utc=True, errors="coerce").dt.hour
            meta["time_of_day"] = pd.cut(hour, [-1, 5, 11, 17, 23], labels=["00-06", "06-12", "12-18", "18-24"]).astype(str)
        t = t.merge(meta, on="thread_id", how="left", suffixes=("", "_tracker"))
    if inp.root_codes is not None:
        rc = inp.root_codes.copy()
        rc["thread_id"] = rc["thread_id"].astype(str)
        t = t.merge(rc, on="thread_id", how="left", suffixes=("", "_root"))
    return t
