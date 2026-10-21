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
    if d.empty:
        return pd.DataFrame(columns=[thread, "n_replies", "reply_share", "view_share", "ratio", "_fv", "_v", "_f"])
    for t, g in d.groupby(thread):
        reply_share = g["_f"].mean()
        total = g["_v"].sum()
        view_share = (g["_v"] * g["_f"]).sum() / total if total > 0 else np.nan
        ratio = view_share / reply_share if 0 < reply_share < 1 and np.isfinite(view_share) else np.nan
        rows.append({thread: t, "n_replies": len(g), "reply_share": reply_share, "view_share": view_share, "ratio": ratio,
                     "_fv": float((g["_v"] * g["_f"]).sum()), "_v": float(total), "_f": float(g["_f"].sum())})
    return pd.DataFrame(rows)


def summarize(df: pd.DataFrame, flag: str, n_boot: int = 2000, seed: int = 0, alpha: float = 0.05,
              thread: str = "study_thread_id") -> dict:
    """Median per-thread ratio and pooled ratio, each with a thread bootstrap interval."""
    table = per_thread_ratios(df, flag, thread)
    valid = table.dropna(subset=["ratio"])
    med, lo, hi = bootstrap_ci(valid["ratio"].to_numpy(float), np.median, n_boot, seed, alpha)

    # Pooled ratio (sum over threads) with a thread bootstrap, vectorised.
    fv, v, f, n = (table[c].to_numpy(float) for c in ("_fv", "_v", "_f", "n_replies"))
    pooled = plo = phi = np.nan
    if len(table) and v.sum() > 0 and 0 < f.sum() < n.sum():
        pooled = (fv.sum() / v.sum()) / (f.sum() / n.sum())
        idx = np.random.default_rng(seed + 1).integers(0, len(table), (n_boot, len(table)))
        sv, sf, sn = v[idx].sum(1), f[idx].sum(1), n[idx].sum(1)
        ok = (sv > 0) & (sf > 0) & (sf < sn)
        if ok.any():
            boots = (fv[idx].sum(1)[ok] / sv[ok]) / (sf[ok] / sn[ok])
            plo, phi = np.quantile(boots, [alpha / 2, 1 - alpha / 2])
    table = table.drop(columns=["_fv", "_v", "_f"])
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
