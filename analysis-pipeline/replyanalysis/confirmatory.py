"""The seven pre-registered tests (docs/preregistration.md sections 2 and 5).

T1, T2, T3 and T9 are mechanics tests from research/mechanics.md section 9;
T10, O1 and O2 complete the confirmatory family. Every result carries an
effect size and a 95% interval; p-values are only used for the Holm
correction across the family.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from . import exposure
from .models import Estimate, NotEstimable, holm, logit_or, mixed_lm, ols, rank_ordered_logit
from .prepare import AnalysisConfig

# Smallest effects of interest (pre-registration section 2).
SESOI_RANK_PP = 5.0
SESOI_RATIO = 1.5
SESOI_REACH = 0.20


@dataclass
class TestResult:
    id: str
    prediction: str
    status: str = "not run"  # pass | fail | not run
    primary: Estimate | None = None
    supporting: dict[str, Estimate | dict] = field(default_factory=dict)
    p_for_family: float | None = None
    p_holm: float | None = None
    direction_ok: bool | None = None
    meets_sesoi: bool | None = None
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        def conv(v):
            if isinstance(v, Estimate):
                return v.to_dict()
            if isinstance(v, dict):
                return {k: conv(x) for k, x in v.items() if not isinstance(x, pd.DataFrame)}
            return v
        return {
            "id": self.id, "prediction": self.prediction, "status": self.status,
            "primary": conv(self.primary), "supporting": conv(self.supporting),
            "p_for_family": self.p_for_family, "p_holm": self.p_holm,
            "direction_ok": self.direction_ok, "meets_sesoi": self.meets_sesoi, "notes": self.notes,
        }


def _controls(df: pd.DataFrame) -> list[str]:
    ctl = ["log_likes", "log_followers", "log_age", "op_replied"]
    if "log_text_len" in df.columns and df["log_text_len"].notna().any():
        ctl.append("log_text_len")
    return [c for c in ctl if df[c].notna().any() and df[c].nunique() > 1]


def _rhs(terms: list[str]) -> str:
    return " + ".join(terms) if terms else "1"


# ---------------------------------------------------------------- T1


def wall_share(sessions: pd.DataFrame) -> pd.DataFrame:
    """Per sort: share of captures where every Premium reply sits above every non-Premium reply, within a section."""
    top = sessions[(sessions["row_type"] == "reply") & sessions["premium"].notna()]
    rows = []
    for (sort, key), g in top.groupby(["sort_order", "session_key"]):
        walls = []
        for _, s in g.groupby(g["conversation_section"].fillna("none")):
            if s["premium"].nunique() < 2:
                continue
            walls.append(s.loc[s.premium == 1, "display_rank"].max() < s.loc[s.premium == 0, "display_rank"].min())
        if walls:
            rows.append({"sort_order": sort, "session_key": key, "wall": all(walls)})
    if not rows:
        return pd.DataFrame(columns=["sort_order", "captures", "wall_share"])
    w = pd.DataFrame(rows)
    return w.groupby("sort_order").agg(captures=("wall", "size"), wall_share=("wall", "mean")).reset_index()


def sort_contrast(sessions: pd.DataFrame, cfg: AnalysisConfig, other: str = "likes") -> Estimate:
    """Rank percentile under the main sort minus under `other`, for replies seen in both, on Premium."""
    top = sessions[(sessions["row_type"] == "reply") & (sessions["age_bucket"] == cfg.main_age)]
    key = ["study_thread_id", "viewer_label", "tweet_id"]
    a = top[top["sort_order"] == cfg.main_sort][key + ["rank_pct", "premium"]]
    b = top[top["sort_order"] == other][key + ["rank_pct"]]
    pair = a.merge(b, on=key, suffixes=("_main", "_other"))
    pair["rank_gain"] = pair["rank_pct_main"] - pair["rank_pct_other"]
    return mixed_lm(pair, "rank_gain ~ premium", "study_thread_id", "premium", cfg.alpha,
                    f"percentile points gained under {cfg.main_sort} vs {other}")


def test_t1(main: pd.DataFrame, sessions: pd.DataFrame, cfg: AnalysisConfig) -> TestResult:
    r = TestResult("T1", "In Relevance sort, Premium replies are placed above non-Premium replies regardless of likes.")
    ctl = _controls(main)
    try:
        r.primary = mixed_lm(main, f"rank_pct ~ premium + {_rhs(ctl)}", "study_thread_id", "premium", cfg.alpha,
                             "percentile points of rank height")
    except NotEstimable as exc:
        r.notes.append(f"rank model not estimable: {exc}")
        return r
    try:
        r.supporting["rank_ordered_logit"] = rank_ordered_logit(
            main, "session_key", "display_rank", ["premium"] + ctl, "study_thread_id", "premium", cfg.alpha)
    except (NotEstimable, np.linalg.LinAlgError) as exc:
        r.notes.append(f"rank-ordered logit sensitivity not estimable: {exc}")
    walls = wall_share(sessions)
    r.supporting["premium_wall_share"] = {"by_sort": walls.to_dict("records")}
    amp = exposure.summarize(main, "premium", cfg.bootstrap, cfg.seed, cfg.alpha)
    r.supporting["amplification"] = {k: v for k, v in amp.items() if k != "per_thread"}
    contrast = None
    try:
        contrast = sort_contrast(sessions, cfg, "likes")
        r.supporting["likes_contrast"] = contrast
    except NotEstimable as exc:
        r.notes.append(f"Likes sort contrast not available: {exc}")
    try:
        r.supporting["recent_contrast"] = sort_contrast(sessions, cfg, "recent")
    except NotEstimable:
        pass

    ratio, (rlo, _rhi) = amp["median_ratio"], amp["median_ratio_ci"]
    model_ok = r.primary.ci_above_zero
    ratio_ok = bool(np.isfinite(ratio) and ratio > SESOI_RATIO and rlo > 1)
    # The pre-registered fail rule needs the Likes contrast; without it T1 cannot pass.
    contrast_ok = contrast is not None and contrast.ci_above_zero
    r.direction_ok = model_ok and ratio_ok and contrast_ok
    r.meets_sesoi = ratio_ok
    # Intersection-union rule: every component must hold, so the family p is the largest component p.
    ps = [p for p in [r.primary.p] + ([contrast.p] if contrast is not None else []) if p is not None]
    r.p_for_family = max(ps) if ps else None
    if not model_ok:
        r.notes.append("Premium rank coefficient interval does not sit above zero.")
    if not ratio_ok:
        r.notes.append(f"Amplification ratio {ratio:.2f} (CI low {rlo:.2f}) misses the >1.5 with CI above 1 rule.")
    if contrast is None:
        r.notes.append("Without Likes captures the 'regardless of likes' part of T1 cannot be checked, so T1 cannot pass.")
    elif not contrast.ci_above_zero:
        r.notes.append("Premium advantage disappears in the Likes sort contrast.")
    return r


# ---------------------------------------------------------------- T2, T3, T10


def _incivility_model(main: pd.DataFrame, cfg: AnalysisConfig, col: str, interaction: str | None) -> Estimate:
    if col not in main.columns or main[col].notna().sum() == 0:
        raise NotEstimable(f"no '{col}' labels joined to the replies")
    d = main.copy()
    d["_x"] = d[col].astype(float)
    ctl = _controls(d) + ["premium"]
    if interaction:
        formula = f"tier_rank_pct ~ _x * {interaction} + {_rhs(ctl)}"
        term = f"_x:{interaction}"
    else:
        formula = f"tier_rank_pct ~ _x + {_rhs(ctl)}"
        term = "_x"
    est = mixed_lm(d, formula, "study_thread_id", term, cfg.alpha, "percentile points of within-tier rank height")
    est.term = term.replace("_x", col)
    return est


def _rank_test(rid: str, text: str, main: pd.DataFrame, cfg: AnalysisConfig, interaction: str | None,
               want_negative: bool) -> TestResult:
    r = TestResult(rid, text)
    try:
        r.primary = _incivility_model(main, cfg, cfg.incivility_col, interaction)
    except NotEstimable as exc:
        r.notes.append(f"not estimable: {exc}")
        return r
    try:
        r.supporting["toxicity_score"] = _incivility_model(main, cfg, cfg.toxicity_col, interaction)
    except NotEstimable:
        r.notes.append(f"secondary model with '{cfg.toxicity_col}' not run (no scores joined).")
    r.direction_ok = r.primary.ci_below_zero if want_negative else r.primary.ci_above_zero
    r.meets_sesoi = abs(r.primary.estimate) >= SESOI_RANK_PP
    r.p_for_family = r.primary.p
    return r


def test_t2(main, cfg):
    return _rank_test("T2", "Within a payment tier, more uncivil replies rank lower in Relevance sort.", main, cfg, None, True)


def test_t3(main, cfg):
    return _rank_test("T3", "The T2 penalty is stronger under roots whose author has 250k or more followers.",
                      main, cfg, "large_root", True)


def test_t10(main, cfg):
    d = main[main["lang"].isin(["en", cfg.second_language])]
    return _rank_test("T10", f"The T2 penalty is weaker for '{cfg.second_language}' replies than for English replies.",
                      d, cfg, "second_lang", False)


# ---------------------------------------------------------------- poster level


def _poster_controls(t: pd.DataFrame, exclude: tuple = ()) -> list[str]:
    out = []
    for col, term in [("log_root_followers", "log_root_followers"), ("topic", "C(topic)"),
                      ("account_type", "C(account_type)"), ("poster_politics", "C(poster_politics)"),
                      ("poster_premium", "poster_premium"), ("time_of_day", "C(time_of_day)")]:
        if col in exclude or col not in t.columns:
            continue
        if t[col].notna().sum() and t[col].dropna().nunique() > 1:
            out.append(term)
    return out


def test_o1(t: pd.DataFrame, cfg: AnalysisConfig) -> TestResult:
    r = TestResult("O1", "Outrage-framed root posts get more views per follower at 24h than non-outrage posts.")
    if t.empty or "outrage_framing" not in t.columns:
        r.notes.append("needs 24h captures and root codes with outrage_framing")
        return r
    try:
        ctl = _poster_controls(t)
        r.primary = ols(t, f"log_views_per_follower ~ outrage_framing + {_rhs(ctl)}",
                        "outrage_framing", cfg.alpha, scale="log views per follower", droppable=ctl)
    except NotEstimable as exc:
        r.notes.append(f"not estimable: {exc}")
        return r
    r.direction_ok = r.primary.ci_above_zero
    r.meets_sesoi = abs(np.expm1(r.primary.estimate)) >= SESOI_REACH
    r.p_for_family = r.primary.p
    if r.primary.note:
        r.notes.append(r.primary.note)
    r.notes.append(f"Effect as a reach change: {np.expm1(r.primary.estimate):+.0%}.")
    return r


def test_t9(t: pd.DataFrame, cfg: AnalysisConfig) -> TestResult:
    r = TestResult("T9", "Targeted-insult posts from very large accounts keep their reach; similar posts from small accounts lose reach.")
    if t.empty or "targeted_insult" not in t.columns:
        r.notes.append("needs 24h captures and root codes with targeted_insult")
        return r
    ctl = _poster_controls(t)
    try:
        r.primary = ols(t, f"log_views_per_follower ~ targeted_insult * large_account + {_rhs(ctl)}",
                        "targeted_insult:large_account", cfg.alpha, scale="log views per follower", droppable=ctl)
    except NotEstimable as exc:
        r.notes.append(f"not estimable: {exc}")
        return r
    r.direction_ok = r.primary.ci_above_zero
    r.meets_sesoi = abs(np.expm1(r.primary.estimate)) >= SESOI_REACH
    r.p_for_family = r.primary.p
    if r.primary.note:
        r.notes.append(r.primary.note)
    return r


def test_o2(t: pd.DataFrame, cfg: AnalysisConfig) -> TestResult:
    r = TestResult("O2", "Paid-clipper root posts are more often outrage-framed than organic-creator root posts on the same topics.")
    if t.empty or "outrage_framing" not in t.columns or "account_type" not in t.columns:
        r.notes.append("needs root codes with outrage_framing and tracker threads with account_type")
        return r
    d = t[t["account_type"].isin(["paid_clipper", "organic_creator"])].copy()
    d["clipper"] = (d["account_type"] == "paid_clipper").astype(float)
    topic = " + C(topic)" if "topic" in d.columns and d["topic"].nunique() > 1 else ""
    try:
        r.primary = logit_or(d, f"outrage_framing ~ clipper{topic}", "clipper", cfg.alpha)
    except NotEstimable as exc:
        if not topic:
            r.notes.append(f"not estimable: {exc}")
            return r
        try:
            r.primary = logit_or(d, "outrage_framing ~ clipper", "clipper", cfg.alpha)
            r.notes.append(f"Topic fixed effects dropped ({exc}); deviation from the pre-registered model.")
        except NotEstimable as exc2:
            r.notes.append(f"not estimable: {exc2}")
            return r
    r.direction_ok = r.primary.ci_low > 1
    r.meets_sesoi = None
    r.p_for_family = r.primary.p
    return r


# ---------------------------------------------------------------- family


def run_all(main: pd.DataFrame, sessions: pd.DataFrame, threads: pd.DataFrame, cfg: AnalysisConfig) -> list[TestResult]:
    results = [
        test_t1(main, sessions, cfg),
        test_t2(main, cfg),
        test_t3(main, cfg),
        test_t9(threads, cfg),
        test_t10(main, cfg),
        test_o1(threads, cfg),
        test_o2(threads, cfg),
    ]
    adjusted = holm({r.id: r.p_for_family for r in results}, cfg.alpha)
    for r in results:
        r.p_holm = adjusted[r.id]
        if r.primary is None:
            r.status = "not run"
        elif r.direction_ok and r.p_holm is not None and r.p_holm < cfg.alpha:
            r.status = "pass"
        else:
            r.status = "fail"
            if r.direction_ok:
                r.notes.append("Interval rule met, but not significant after Holm correction across the family.")
        if r.status == "pass" and r.meets_sesoi is False:
            r.notes.append("Statistically clear but below the smallest effect of interest: report as too small to matter.")
    return results
