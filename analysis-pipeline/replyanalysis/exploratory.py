"""Exploratory tests A1 to A9 from the synthesis build plan, plus descriptives.

None of these can confirm or refute H1 to H3 (pre-registration section 5.6);
the report labels them exploratory. A5 needs human participants and A8 needs
historical data, so both are written as ready-to-use tools that say plainly
when the data is not there.

| Id | Question |
| --- | --- |
| A1 | Top-10 vs all-replies stance gap across threads |
| A2 | Rudeness contagion after a rude Premium reply reaches the top |
| A3 | Follower gains for Premium pile-on repliers |
| A4 | Silencing: do people who push back and get piled on post less afterwards? |
| A5 | Perceived-consensus experiment (stimulus export only; needs participants) |
| A6 | "About this account" country vs claimed location |
| A7 | Reply-pod timing: the same accounts replying within seconds across threads |
| A8 | Before vs after the 17 Jan 2026 payout change (needs historical data) |
| A9 | Farmer vs ideologue repliers and posters |
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from itertools import combinations

import numpy as np
import pandas as pd
import statsmodels.formula.api as smf

from . import exposure
from .models import Estimate, NotEstimable, bootstrap_ci, mixed_lm, ols
from .prepare import AnalysisConfig


def _not_run(aid: str, title: str, why: str) -> dict:
    return {"id": aid, "title": title, "status": "not run", "reason": why}


def _has(df: pd.DataFrame, col: str) -> bool:
    return col in df.columns and df[col].notna().any()


# ---------------------------------------------------------------- descriptives


def descriptives(sessions: pd.DataFrame, main: pd.DataFrame, cfg: AnalysisConfig) -> dict:
    out = {
        "threads": int(sessions["study_thread_id"].nunique()),
        "captures": int(sessions["capture_id"].nunique()),
        "top_level_replies_main": int(len(main)),
        "threads_main": int(main["study_thread_id"].nunique()),
        "premium_share_main": float(main["premium"].mean()) if len(main) else None,
        "captures_by_sort_age": sessions.drop_duplicates("capture_id").groupby(["sort_order", "age_bucket"]).size()
        .rename("captures").reset_index().to_dict("records"),
    }
    inc = cfg.incivility_col
    if _has(main, inc):
        d = main.dropna(subset=[inc])
        out["incivility_rate"] = float(d[inc].mean())
        out["incivility_rate_by_premium"] = {str(int(k)): float(v) for k, v in d.groupby("premium")[inc].mean().items()}
        amp = exposure.summarize(d, inc, cfg.bootstrap, cfg.seed, cfg.alpha)
        out["incivility_exposure"] = {k: v for k, v in amp.items() if k != "per_thread"}
        try:
            d = d.assign(_inc=d[inc].astype(float))
            est = mixed_lm(d, "log_views ~ _inc + premium + log_followers + log_age", "study_thread_id", "_inc",
                           cfg.alpha, "log views")
            out["uncivil_view_multiplier"] = {"multiplier": float(np.exp(est.estimate)),
                                              "ci": [float(np.exp(est.ci_low)), float(np.exp(est.ci_high))],
                                              "method": est.method}
        except NotEstimable:
            pass
    return out


# ---------------------------------------------------------------- A1


def a1_stance_gap(main: pd.DataFrame, cfg: AnalysisConfig) -> dict:
    title = "Top-10 vs all-replies stance gap"
    col = cfg.stance_col
    if not _has(main, col):
        return _not_run("A1", title, f"no '{col}' codes joined to the replies")
    d = main.dropna(subset=[col])
    rows = []
    for key, g in d.groupby("session_key"):
        top = g.nsmallest(cfg.top_k, "display_rank")
        for value in d[col].unique():
            rows.append({"session_key": key, "thread": g["study_thread_id"].iloc[0], "stance": value,
                         "share_all": float((g[col] == value).mean()), "share_top": float((top[col] == value).mean())})
    t = pd.DataFrame(rows)
    t["gap_pp"] = 100 * (t["share_top"] - t["share_all"])
    summary = []
    for value, g in t.groupby("stance"):
        per_thread = g.groupby("thread")["gap_pp"].mean().to_numpy()
        mean, lo, hi = bootstrap_ci(per_thread, np.mean, cfg.bootstrap, cfg.seed, cfg.alpha)
        summary.append({"stance": value, "mean_gap_pp": mean, "ci": [lo, hi], "threads": len(per_thread),
                        "mean_share_all": float(g["share_all"].mean()), "mean_share_top": float(g["share_top"].mean())})
    return {"id": "A1", "title": title, "status": "ran", "top_k": cfg.top_k,
            "by_stance": summary, "note": "Positive gap: the stance is over-represented in the visible top replies."}


# ---------------------------------------------------------------- A2


def a2_rudeness_contagion(sessions: pd.DataFrame, cfg: AnalysisConfig) -> dict:
    title = "Rudeness contagion after a rude Premium reply reaches the top"
    inc = cfg.incivility_col
    if not _has(sessions, inc):
        return _not_run("A2", title, f"no '{inc}' codes joined")
    first = sessions[(sessions["sort_order"] == cfg.main_sort) & (sessions["row_type"] == "reply")]
    if first.empty:
        return _not_run("A2", title, "no main-sort captures")
    first = first[first["capture_time_utc"] == first.groupby("study_thread_id")["capture_time_utc"].transform("min")]
    ref = first.groupby("study_thread_id").apply(
        lambda g: pd.Series({
            "t0": g["capture_time_utc"].iloc[0],
            "rude_top": int(((g["display_rank"] <= cfg.rude_top_k) & (g["premium"] == 1) & (g[inc] == 1)).any()),
        }), include_groups=False).reset_index()
    replies = (sessions[sessions["row_type"].isin(["reply", "nested_reply"])]
               .drop_duplicates(["study_thread_id", "tweet_id"])
               .dropna(subset=[inc, "created_at_utc"]))
    d = replies.merge(ref, on="study_thread_id")
    d["after"] = (d["created_at_utc"] > d["t0"]).astype(float)
    d["after_x_rude"] = d["after"] * d["rude_top"]
    d["_inc"] = d[inc].astype(float)
    if d["rude_top"].nunique() < 2 or d["after"].nunique() < 2:
        return _not_run("A2", title, "need threads with and without a rude Premium top reply, and replies after the first capture")
    try:
        res = smf.ols("_inc ~ after + after_x_rude + C(study_thread_id)", d).fit(
            cov_type="cluster", cov_kwds={"groups": pd.factorize(d["study_thread_id"])[0]})
    except Exception as exc:  # singular designs
        return _not_run("A2", title, f"model failed: {exc}")
    lo, hi = res.conf_int(cfg.alpha).loc["after_x_rude"]
    est = Estimate("after_x_rude_top", float(res.params["after_x_rude"]) * 100, float(lo) * 100, float(hi) * 100,
                   float(res.pvalues["after_x_rude"]), None, len(d), int(d["study_thread_id"].nunique()),
                   "linear probability, thread fixed effects, thread-clustered errors",
                   "percentage points of incivility")
    return {"id": "A2", "title": title, "status": "ran", "estimate": est.to_dict(),
            "threads_with_rude_top": int(ref["rude_top"].sum()), "threads": int(len(ref)),
            "note": f"Difference-in-differences: change in incivility of replies written after the first {cfg.main_sort} "
                    f"capture, in threads whose top {cfg.rude_top_k} then held an uncivil Premium reply, vs other threads."}


# ---------------------------------------------------------------- A3, A4 author panels


def _author_panel(sessions: pd.DataFrame, value: str) -> pd.DataFrame:
    """First and last observation of an author-level count across all captures."""
    d = sessions.dropna(subset=["author_id_hash", value]).sort_values("capture_time_utc")
    g = d.groupby("author_id_hash")
    p = pd.DataFrame({
        "first_value": g[value].first().astype(float), "last_value": g[value].last().astype(float),
        "first_time": g["capture_time_utc"].first(), "last_time": g["capture_time_utc"].last(),
        "first_thread": g["study_thread_id"].first(),
    })
    p["days"] = (p["last_time"] - p["first_time"]).dt.total_seconds() / 86400
    return p[p["days"] > 0]


def a3_follower_gains(sessions: pd.DataFrame, cfg: AnalysisConfig) -> dict:
    title = "Follower gains for Premium pile-on repliers"
    inc, op = cfg.incivility_col, cfg.attacks_op_col
    if not _has(sessions, inc):
        return _not_run("A3", title, f"no '{inc}' codes joined")
    panel = _author_panel(sessions, "author_followers")
    if len(panel) < 10:
        return _not_run("A3", title, "fewer than 10 authors seen at two capture times")
    replies = sessions.dropna(subset=[inc])
    pile = replies[inc] == 1
    if _has(replies, op):
        pile &= replies[op] == 1
    authors = replies.assign(_pile=pile.astype(float)).groupby("author_id_hash").agg(
        pileon=("_pile", "max"), premium=("premium", "max"))
    d = panel.join(authors, how="inner").dropna(subset=["premium"])
    d["growth"] = (np.log1p(d["last_value"]) - np.log1p(d["first_value"])) / d["days"] * 100
    d["log_first"] = np.log1p(d["first_value"])
    d["premium_pileon"] = d["premium"].astype(float) * d["pileon"]
    try:
        est = ols(d, "growth ~ premium_pileon + premium + pileon + log_first", "premium_pileon", cfg.alpha,
                  cluster="first_thread", scale="log-points of followers per day x100 (about % per day)")
    except NotEstimable as exc:
        return _not_run("A3", title, str(exc))
    return {"id": "A3", "title": title, "status": "ran", "estimate": est.to_dict(), "authors": int(len(d)),
            "median_window_days": float(d["days"].median()),
            "note": "Extra daily follower growth for Premium repliers who joined a pile-on, beyond Premium and pile-on alone. "
                    "The window is the span between an author's first and last capture; follow-up captures lengthen it."}


def a4_silencing(sessions: pd.DataFrame, cfg: AnalysisConfig) -> dict:
    title = "Silencing: posting rate of pushback repliers who were piled on"
    inc, pb = cfg.incivility_col, cfg.pushback_col
    if not _has(sessions, pb) or not _has(sessions, inc):
        return _not_run("A4", title, f"needs '{pb}' and '{inc}' codes")
    panel = _author_panel(sessions, "author_statuses")
    pushers = sessions[(sessions["row_type"] == "reply") & (sessions[pb] == 1)]
    nested = sessions[(sessions["row_type"] == "nested_reply") & (sessions[inc] == 1)]
    mod_author = sessions[sessions["row_type"] == "reply"].set_index("module_id")["author_id_hash"]
    nested = nested[nested["author_id_hash"].values != mod_author.reindex(nested["module_id"]).values]
    piled_modules = set(nested["module_id"])
    a = pushers.assign(_piled=pushers["module_id"].isin(piled_modules).astype(float)).groupby("author_id_hash").agg(
        piled_on=("_piled", "max"), premium=("premium", "max"))
    d = panel.join(a, how="inner")
    if len(d) < 10 or d["piled_on"].nunique() < 2:
        return _not_run("A4", title, "too few pushback repliers seen twice, or none were piled on")
    d["log_rate"] = np.log1p((d["last_value"] - d["first_value"]).clip(lower=0) / d["days"])
    d["log_first"] = np.log1p(d["first_value"])
    try:
        est = ols(d, "log_rate ~ piled_on + premium + log_first", "piled_on", cfg.alpha, cluster="first_thread",
                  scale="log(1 + posts per day)")
    except NotEstimable as exc:
        return _not_run("A4", title, str(exc))
    return {"id": "A4", "title": title, "status": "ran", "estimate": est.to_dict(), "authors": int(len(d)),
            "median_window_days": float(d["days"].median()),
            "note": "Weeks-long silencing needs the same authors captured again later (any later capture with the same salt counts)."}


# ---------------------------------------------------------------- A5


def a5_stimuli(main: pd.DataFrame) -> pd.DataFrame:
    """Two orderings per capture for a perceived-consensus experiment: as X showed it, and chronological."""
    rows = []
    for key, g in main.groupby("session_key"):
        shown = g.sort_values("display_rank")["tweet_id"].tolist()
        chrono = g.sort_values("created_at_utc")["tweet_id"].tolist()
        rows.append({"session_key": key, "thread": g["study_thread_id"].iloc[0], "condition": "as_shown", "tweet_ids": " ".join(shown)})
        rows.append({"session_key": key, "thread": g["study_thread_id"].iloc[0], "condition": "chronological", "tweet_ids": " ".join(chrono)})
    return pd.DataFrame(rows)


def a5_consensus_experiment(main: pd.DataFrame) -> dict:
    return {"id": "A5", "title": "Perceived-consensus experiment (Premium-first vs chronological)", "status": "stub",
            "reason": "Needs human participants. The pipeline exports the two orderings per capture "
                      "(a5_stimuli.csv) so an experiment can show them; analysing responses is out of scope until "
                      "participants exist.", "captures_exported": int(main["session_key"].nunique())}


# ---------------------------------------------------------------- A6


def _norm_place(x) -> str | None:
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return None
    t = re.sub(r"[^a-z ]", " ", str(x).lower())
    t = re.sub(r"\s+", " ", t).strip()
    return t or None


def _contains_phrase(text: str, phrase: str) -> bool:
    """Whole-word containment, so 'us' does not match 'russia' and 'niger' does not match 'nigeria'."""
    return re.search(rf"\b{re.escape(phrase)}\b", text) is not None


def a6_location_mismatch(sessions: pd.DataFrame, cfg: AnalysisConfig) -> dict:
    title = "'About this account' country vs claimed location"
    if not _has(sessions, "account_based_in") or not _has(sessions, "claimed_location"):
        return _not_run("A6", title, "Reply table v1 has no 'About this account' country or profile location. "
                                     "Supply an author file with account_based_in and claimed_location "
                                     "(or add them to the parser as nullable columns, a minor schema change).")
    a = sessions.drop_duplicates("author_id_hash").copy()
    a["based"] = a["account_based_in"].map(_norm_place)
    a["claimed"] = a["claimed_location"].map(_norm_place)
    a = a.dropna(subset=["based", "claimed"])
    a["mismatch"] = [float(not (_contains_phrase(c, b) or _contains_phrase(b, c))) for b, c in zip(a["based"], a["claimed"])]
    out = {"id": "A6", "title": title, "status": "ran", "authors": int(len(a)),
           "mismatch_rate": float(a["mismatch"].mean()) if len(a) else None,
           "by_premium": {str(k): float(v) for k, v in a.groupby("premium")["mismatch"].mean().items()}}
    if _has(a, cfg.incivility_col):
        inc = sessions.groupby("author_id_hash")[cfg.incivility_col].max()
        a = a.join(inc.rename("ever_uncivil"), on="author_id_hash")
        out["by_ever_uncivil"] = {str(k): float(v) for k, v in a.groupby("ever_uncivil")["mismatch"].mean().items()}
    out["note"] = ("Whole-word match on normalised place names; a claimed city that does not name its country "
                   "counts as a mismatch. Hand-check flagged accounts.")
    return out


# ---------------------------------------------------------------- A7


def _pair_counts(d: pd.DataFrame, window: float) -> Counter:
    counts: Counter = Counter()
    for _, g in d.groupby("study_thread_id"):
        g = g.sort_values("t")
        t, a = g["t"].to_numpy(), g["author_id_hash"].to_numpy()
        seen = set()
        j = 0
        for i in range(len(t)):
            while t[i] - t[j] > window:
                j += 1
            for k in range(j, i):
                if a[k] != a[i]:
                    seen.add(tuple(sorted((a[k], a[i]))))
        counts.update(seen)
    return counts


def a7_reply_pods(sessions: pd.DataFrame, cfg: AnalysisConfig) -> dict:
    title = "Reply-pod timing across threads"
    d = (sessions[sessions["row_type"].isin(["reply", "nested_reply"])]
         .drop_duplicates(["study_thread_id", "tweet_id"]).dropna(subset=["created_at_utc", "author_id_hash"]))
    if d["study_thread_id"].nunique() < cfg.pod_min_threads:
        return _not_run("A7", title, f"fewer than {cfg.pod_min_threads} threads")
    epoch = pd.Timestamp("1970-01-01", tz="UTC")
    d = d.assign(t=(d["created_at_utc"] - epoch).dt.total_seconds())[["study_thread_id", "author_id_hash", "t"]]
    observed = _pair_counts(d, cfg.pod_window_seconds)
    candidates = {p: c for p, c in observed.items() if c >= cfg.pod_min_threads}
    rng = np.random.default_rng(cfg.seed)
    exceed = Counter()
    null_max = []
    for _ in range(cfg.pod_permutations):
        # Shuffle who wrote which reply inside each thread: keeps every thread's timing and every author's activity.
        perm = d.copy()
        perm["author_id_hash"] = perm.groupby("study_thread_id")["author_id_hash"].transform(lambda s: rng.permutation(s.to_numpy()))
        pc = _pair_counts(perm, cfg.pod_window_seconds)
        null_max.append(max(pc.values(), default=0))
        for p, c in candidates.items():
            if pc.get(p, 0) >= c:
                exceed[p] += 1
    pairs = []
    for p, c in sorted(candidates.items(), key=lambda kv: -kv[1]):
        pval = (exceed[p] + 1) / (cfg.pod_permutations + 1)
        pairs.append({"author_a": p[0], "author_b": p[1], "threads_together": c, "p_perm": pval})
    flagged = [p for p in pairs if p["p_perm"] <= cfg.pod_alpha]
    # Connected components of flagged pairs are candidate pods.
    parent: dict = {}

    def find(x):
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for p in flagged:
        parent[find(p["author_a"])] = find(p["author_b"])
    pods = defaultdict(set)
    for p in flagged:
        pods[find(p["author_a"])].update([p["author_a"], p["author_b"]])
    return {"id": "A7", "title": title, "status": "ran", "window_seconds": cfg.pod_window_seconds,
            "min_threads": cfg.pod_min_threads, "permutations": cfg.pod_permutations,
            "candidate_pairs": len(pairs), "flagged_pairs": flagged[:200],
            "pods": [sorted(v) for v in sorted(pods.values(), key=len, reverse=True)],
            "null_max_pair_count_95pct": float(np.quantile(null_max, 0.95)) if null_max else None,
            "warning": (f"{cfg.pod_permutations} permutations cannot reach p <= {cfg.pod_alpha}; use at least "
                        f"{int(1 / cfg.pod_alpha)} permutations" if 1 / (cfg.pod_permutations + 1) > cfg.pod_alpha else None),
            "note": "Author hashes only. A pod is a set of accounts that reply within the window of each other in "
                    "more threads than chance (author labels shuffled within thread). Hand-check before calling it coordination."}


def near_duplicates(sessions: pd.DataFrame, threshold: float = 0.7, min_chars: int = 25) -> dict:
    """Near-identical reply texts within a thread (character 5-gram Jaccard), the brigade.py check."""
    if not _has(sessions, "text"):
        return {"status": "not run", "reason": "reply text not captured (parser ran without --include-text)"}
    d = sessions[sessions["row_type"].isin(["reply", "nested_reply"])].drop_duplicates(["study_thread_id", "tweet_id"])
    d = d.dropna(subset=["text"])
    clean = d["text"].str.replace(r"@\w+", "", regex=True).str.replace(r"https?://\S+", "", regex=True).str.lower().str.strip()
    d = d.assign(clean=clean)
    d = d[d["clean"].str.len() >= min_chars]
    per_thread, examples = [], []
    for t, g in d.groupby("study_thread_id"):
        sh = [set(s[i:i + 5] for i in range(len(s) - 4)) for s in g["clean"]]
        authors = g["author_id_hash"].to_numpy()
        n = 0
        for i, j in combinations(range(len(sh)), 2):
            if authors[i] == authors[j]:
                continue
            inter = len(sh[i] & sh[j])
            if inter and inter / len(sh[i] | sh[j]) >= threshold:
                n += 1
                if len(examples) < 20:
                    examples.append({"thread": t, "tweet_a": g["tweet_id"].iloc[i], "tweet_b": g["tweet_id"].iloc[j]})
        per_thread.append({"thread": t, "replies": len(g), "near_duplicate_pairs": n})
    return {"status": "ran", "threshold": threshold, "per_thread": per_thread, "examples": examples}


# ---------------------------------------------------------------- A8


def a8_regime_break(sessions: pd.DataFrame, cfg: AnalysisConfig, min_weeks_each_side: int = 4) -> dict:
    """Segmented regression on weekly reply series around a payout rule change."""
    title = f"Before vs after the {cfg.regime_break_date} payout change"
    d = (sessions[sessions["row_type"].isin(["reply", "nested_reply"])]
         .drop_duplicates(["study_thread_id", "tweet_id"]).dropna(subset=["created_at_utc"]))
    brk = pd.Timestamp(cfg.regime_break_date, tz="UTC")
    week = (d["created_at_utc"] - brk).dt.days // 7
    weeks_before = int(week[week < 0].nunique())
    weeks_after = int(week[week >= 0].nunique())
    if weeks_before < min_weeks_each_side or weeks_after < min_weeks_each_side:
        return {"id": "A8", "title": title, "status": "stub",
                "reason": f"Needs historical data: replies span {int(weeks_before)} weeks before and {int(weeks_after)} after "
                          f"the break; at least {min_weeks_each_side} each side are required. Runs unchanged once older "
                          "captures exist."}
    d = d.assign(week=((d["created_at_utc"] - brk).dt.days // 7).astype(int))
    series = {"premium_share": ("premium", d)}
    if _has(d, cfg.incivility_col):
        series["incivility_rate"] = (cfg.incivility_col, d.dropna(subset=[cfg.incivility_col]))
    if _has(d, cfg.incivility_col):
        prem = d[(d["premium"] == 1)].dropna(subset=[cfg.incivility_col])
        series["premium_incivility_rate"] = (cfg.incivility_col, prem)
    out = {"id": "A8", "title": title, "status": "ran", "series": {}}
    for name, (col, frame) in series.items():
        w = frame.groupby("week")[col].mean().astype(float).rename("y").reset_index()
        w["post"] = (w["week"] >= 0).astype(float)
        w["week_post"] = w["week"] * w["post"]
        if len(w) < 2 * min_weeks_each_side:
            continue
        res = smf.ols("y ~ week + post + week_post", w).fit(cov_type="HAC", cov_kwds={"maxlags": 2})
        lo, hi = res.conf_int(cfg.alpha).loc["post"]
        out["series"][name] = {"level_change_pp": float(res.params["post"]) * 100, "ci_pp": [float(lo) * 100, float(hi) * 100],
                               "slope_change_pp_per_week": float(res.params["week_post"]) * 100, "weeks": int(len(w))}
    out["note"] = "Interrupted time series on weekly means, Newey-West errors. Composition of captured threads can change with time; read with care."
    return out


# ---------------------------------------------------------------- A9


def a9_farmer_ideologue(sessions: pd.DataFrame, main: pd.DataFrame, threads: pd.DataFrame, cfg: AnalysisConfig) -> dict:
    title = "Farmer vs ideologue repliers and posters"
    out = {"id": "A9", "title": title, "status": "not run"}
    if _has(main, "motive"):
        d = main.dropna(subset=["motive"])
        rows = []
        for m, g in d.groupby("motive"):
            row = {"motive": m, "replies": int(len(g)), "reply_share": float(len(g) / len(d)),
                   "view_share": float(g["view_count"].sum() / d["view_count"].sum()) if d["view_count"].sum() else None,
                   "premium_share": float(g["premium"].mean())}
            if _has(g, cfg.incivility_col):
                row["incivility_rate"] = float(g[cfg.incivility_col].mean())
            rows.append(row)
        out.update(status="ran", repliers=rows)
        flags = d.assign(_farmer=(d["motive"] == "farmer").astype(float))
        if flags["_farmer"].nunique() == 2:
            amp = exposure.summarize(flags, "_farmer", cfg.bootstrap, cfg.seed, cfg.alpha)
            out["farmer_exposure"] = {k: v for k, v in amp.items() if k != "per_thread"}
    if not threads.empty and _has(threads, "poster_motive"):
        t = threads.dropna(subset=["poster_motive"])
        out["posters"] = t.groupby("poster_motive").agg(
            threads=("thread_id", "size"),
            median_log_views_per_follower=("log_views_per_follower", "median"),
        ).reset_index().to_dict("records")
        if "outrage_framing" in t.columns:
            for rec in out["posters"]:
                rec["outrage_rate"] = float(t.loc[t.poster_motive == rec["poster_motive"], "outrage_framing"].mean())
        out["status"] = "ran"
    if out["status"] == "not run":
        out["reason"] = "needs a 'motive' column (farmer / ideologue / other) in the author file, or 'poster_motive' in root codes"
    return out


def run_all(sessions: pd.DataFrame, main: pd.DataFrame, threads: pd.DataFrame, cfg: AnalysisConfig) -> dict:
    return {
        "descriptives": descriptives(sessions, main, cfg),
        "A1": a1_stance_gap(main, cfg),
        "A2": a2_rudeness_contagion(sessions, cfg),
        "A3": a3_follower_gains(sessions, cfg),
        "A4": a4_silencing(sessions, cfg),
        "A5": a5_consensus_experiment(main),
        "A6": a6_location_mismatch(sessions, cfg),
        "A7": a7_reply_pods(sessions, cfg),
        "A8": a8_regime_break(sessions, cfg),
        "A9": a9_farmer_ideologue(sessions, main, threads, cfg),
        "near_duplicates": near_duplicates(sessions),
    }
