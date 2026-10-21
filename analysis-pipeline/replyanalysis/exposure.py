"""Exposure ratios: a group's share of reply views divided by its share of replies."""

from __future__ import annotations

import numpy as np
import pandas as pd

from .models import bootstrap_ci


def per_thread_ratios(df: pd.DataFrame, flag: str, thread: str = "study_thread_id", views: str = "view_count") -> pd.DataFrame:
    """One row per thread: reply share, view share and their ratio for rows where `flag` is 1.

    Threads where the group is absent, or is every reply, have no defined
    ratio and are left out of the summary (kept in the table with NaN).
    """
    d = df[[thread, flag, views]].dropna()
    d = d.assign(_f=d[flag].astype(float), _v=d[views].astype(float))
    rows = []
    for t, g in d.groupby(thread):
        reply_share = g["_f"].mean()
        total = g["_v"].sum()
        view_share = (g["_v"] * g["_f"]).sum() / total if total > 0 else np.nan
        ratio = view_share / reply_share if 0 < reply_share < 1 and np.isfinite(view_share) else np.nan
        rows.append({thread: t, "n_replies": len(g), "reply_share": reply_share, "view_share": view_share, "ratio": ratio})
    return pd.DataFrame(rows)


def summarize(df: pd.DataFrame, flag: str, n_boot: int = 2000, seed: int = 0, alpha: float = 0.05,
              thread: str = "study_thread_id") -> dict:
    """Median per-thread ratio and pooled ratio, each with a thread bootstrap interval."""
    table = per_thread_ratios(df, flag, thread)
    valid = table.dropna(subset=["ratio"])
    med, lo, hi = bootstrap_ci(valid["ratio"].to_numpy(), np.median, n_boot, seed, alpha)

    d = df[[thread, flag, "view_count"]].dropna()
    d = d.assign(_f=d[flag].astype(float), _v=d["view_count"].astype(float))
    sums = d.groupby(thread).apply(lambda g: pd.Series({"fv": (g._f * g._v).sum(), "v": g._v.sum(), "f": g._f.sum(), "n": len(g)}),
                                   include_groups=False)
    pooled = np.nan
    plo = phi = np.nan
    if len(sums) and sums.v.sum() > 0 and 0 < sums.f.sum() < sums.n.sum():
        def pooled_ratio(s):
            return (s.fv.sum() / s.v.sum()) / (s.f.sum() / s.n.sum())
        pooled = pooled_ratio(sums)
        rng = np.random.default_rng(seed + 1)
        boots = []
        for _ in range(n_boot):
            s = sums.iloc[rng.integers(0, len(sums), len(sums))]
            if s.v.sum() > 0 and s.f.sum() > 0 and s.f.sum() < s.n.sum():
                boots.append(pooled_ratio(s))
        if boots:
            plo, phi = np.quantile(boots, [alpha / 2, 1 - alpha / 2])
    return {
        "flag": flag,
        "threads_with_ratio": int(len(valid)),
        "threads_total": int(len(table)),
        "reply_share_mean": float(table["reply_share"].mean()) if len(table) else np.nan,
        "view_share_mean": float(table["view_share"].mean()) if len(table) else np.nan,
        "median_ratio": med, "median_ratio_ci": [lo, hi],
        "pooled_ratio": float(pooled), "pooled_ratio_ci": [float(plo), float(phi)],
        "per_thread": table,
    }
