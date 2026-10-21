"""Model wrappers that return one estimate with its interval, never a bare p-value."""

from __future__ import annotations

import warnings
from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd
import statsmodels.formula.api as smf
from scipy import optimize, stats


@dataclass
class Estimate:
    term: str
    estimate: float
    ci_low: float
    ci_high: float
    p: float | None = None
    se: float | None = None
    n_obs: int | None = None
    n_groups: int | None = None
    method: str = ""
    scale: str = ""
    note: str = ""

    def to_dict(self) -> dict:
        return {k: (None if isinstance(v, float) and not np.isfinite(v) else v) for k, v in asdict(self).items()}

    @property
    def ci_above_zero(self) -> bool:
        return self.ci_low > 0

    @property
    def ci_below_zero(self) -> bool:
        return self.ci_high < 0


class NotEstimable(RuntimeError):
    """The data cannot support the model (too few groups, no variation, missing columns)."""


def _z(alpha: float) -> float:
    return float(stats.norm.ppf(1 - alpha / 2))


def _needed_columns(formula: str, df: pd.DataFrame) -> list[str]:
    return [c for c in df.columns if c in formula.replace("C(", " ").replace(")", " ").replace("*", " ").replace(":", " ").replace("+", " ").replace("~", " ").split()]


def _clean(df: pd.DataFrame, formula: str, extra: list[str] | tuple = ()) -> pd.DataFrame:
    cols = list(dict.fromkeys(_needed_columns(formula, df) + list(extra)))
    d = df[cols].copy()
    for c in cols:
        if pd.api.types.is_bool_dtype(d[c]) or str(d[c].dtype) in ("Float64", "Int64", "boolean"):
            d[c] = d[c].astype(float)
    return d.dropna()


def _check_variation(d: pd.DataFrame, terms: list[str]) -> None:
    for t in terms:
        for part in t.split(":"):
            if part in d.columns and d[part].nunique() < 2:
                raise NotEstimable(f"no variation in {part}")


def mixed_lm(df: pd.DataFrame, formula: str, group: str, term: str, alpha: float = 0.05, scale: str = "") -> Estimate:
    """Linear mixed model with a random intercept per group (thread).

    Falls back to OLS with cluster-robust errors when the mixed model cannot be
    fitted (for example a zero random-effect variance with few threads); the
    fallback is named in `method`.
    """
    d = _clean(df, formula, [group])
    if len(d) < 10 or d[group].nunique() < 2:
        raise NotEstimable(f"{len(d)} rows in {d[group].nunique()} groups")
    _check_variation(d, [term])
    z = _z(alpha)
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            res = smf.mixedlm(formula, d, groups=d[group]).fit(reml=True, method=["lbfgs", "powell"])
        if not res.converged or not np.isfinite(res.bse[term]):
            raise RuntimeError("did not converge")
        b, se = float(res.params[term]), float(res.bse[term])
        method = "linear mixed model, random intercept per thread (REML)"
    except (RuntimeError, np.linalg.LinAlgError, ValueError) as exc:
        res = smf.ols(formula, d).fit(cov_type="cluster", cov_kwds={"groups": pd.factorize(d[group])[0]})
        b, se = float(res.params[term]), float(res.bse[term])
        method = f"OLS, thread-clustered errors (mixed model failed: {exc})"
    p = float(2 * stats.norm.sf(abs(b / se))) if se > 0 else None
    return Estimate(term, b, b - z * se, b + z * se, p, se, len(d), int(d[group].nunique()), method, scale)


def ols(df: pd.DataFrame, formula: str, term: str, alpha: float = 0.05, cluster: str | None = None, scale: str = "",
        droppable: list[str] | tuple = ()) -> Estimate:
    """OLS with HC3 errors, or cluster-robust errors when `cluster` is given.

    With few threads, controls can be collinear (for example every large
    account in one topic). Terms listed in `droppable` are removed from the
    end, one at a time, until the design has full rank; the note says which.
    """
    lhs, rhs = (x.strip() for x in formula.split("~"))
    terms = [t.strip() for t in rhs.split("+")]
    dropped: list[str] = []
    d = _clean(df, formula, [cluster] if cluster else [])
    if len(d) < 5:
        raise NotEstimable(f"only {len(d)} complete rows")
    _check_variation(d, [term])
    while True:
        f = f"{lhs} ~ {' + '.join(terms)}"
        model = smf.ols(f, d)
        exog = model.exog
        if np.linalg.matrix_rank(exog) == exog.shape[1] and exog.shape[0] > exog.shape[1]:
            break
        left = [t for t in droppable if t in terms]
        if not left:
            raise NotEstimable("design matrix is rank-deficient")
        terms.remove(left[-1])
        dropped.append(left[-1])
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        if cluster:
            res = model.fit(cov_type="cluster", cov_kwds={"groups": pd.factorize(d[cluster])[0]})
            method, groups = "OLS, cluster-robust errors", int(d[cluster].nunique())
        else:
            res = model.fit(cov_type="HC3")
            method, groups = "OLS, HC3 robust errors", None
    if term not in res.params:
        raise NotEstimable(f"term {term} dropped from the model")
    lo, hi = res.conf_int(alpha).loc[term]
    note = f"dropped collinear controls: {', '.join(dropped)}" if dropped else ""
    return Estimate(term, float(res.params[term]), float(lo), float(hi), float(res.pvalues[term]), float(res.bse[term]),
                    len(d), groups, method, scale, note)


def logit_or(df: pd.DataFrame, formula: str, term: str, alpha: float = 0.05) -> Estimate:
    """Logistic regression; the estimate and interval are odds ratios."""
    d = _clean(df, formula)
    if len(d) < 10:
        raise NotEstimable(f"only {len(d)} complete rows")
    _check_variation(d, [term, formula.split("~")[0].strip()])
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        try:
            res = smf.logit(formula, d).fit(disp=False, cov_type="HC1", maxiter=200)
        except Exception as exc:  # perfect separation and singular fits
            raise NotEstimable(f"logit failed: {exc}") from exc
    lo, hi = res.conf_int(alpha).loc[term]
    b = float(res.params[term])
    if not np.isfinite(lo) or not np.isfinite(hi) or abs(b) > 15:
        raise NotEstimable("logit estimate is unstable (likely separation)")
    return Estimate(term, float(np.exp(b)), float(np.exp(lo)), float(np.exp(hi)), float(res.pvalues[term]),
                    float(res.bse[term]), len(d), None, "logistic regression, robust errors", "odds ratio")


# ---------------------------------------------------------------- rank-ordered logit


def rank_ordered_logit(df: pd.DataFrame, stratum: str, rank: str, covariates: list[str], cluster: str,
                       term: str, alpha: float = 0.05) -> Estimate:
    """Rank-ordered (exploded, Plackett-Luce) logit, one ranking per stratum (capture).

    The item at rank 1 is chosen from everything in the list, rank 2 from the
    rest, and so on. A positive coefficient means the trait moves a reply
    toward the top. Errors are clustered by `cluster` (thread).
    """
    d = _clean(df, " ".join(covariates), [stratum, rank, cluster])
    d = d.sort_values([stratum, rank])
    _check_variation(d, [term])
    sizes = d.groupby(stratum, sort=False).size()
    d = d[d[stratum].isin(sizes[sizes > 1].index)]
    if d[stratum].nunique() < 2:
        raise NotEstimable("fewer than two rankings with more than one reply")
    X = d[covariates].to_numpy(float)
    mu, sd = X.mean(0), X.std(0)
    sd[sd == 0] = 1.0
    Xs = (X - mu) / sd
    blocks = [np.flatnonzero(d[stratum].to_numpy() == s) for s in pd.unique(d[stratum])]
    clusters = d[cluster].to_numpy()

    def parts(beta):
        ll, grad = 0.0, np.zeros_like(beta)
        hess = np.zeros((len(beta), len(beta)))
        scores = []
        for idx in blocks:
            x = Xs[idx]
            eta = x @ beta
            m = eta.max()
            w = np.exp(eta - m)
            # risk set for position k = items k..n (lower in the list); suffix sums
            s0 = np.cumsum(w[::-1])[::-1]
            s1 = np.cumsum((w[:, None] * x)[::-1], axis=0)[::-1]
            s2 = np.cumsum((w[:, None, None] * x[:, :, None] * x[:, None, :])[::-1], axis=0)[::-1]
            mean = s1 / s0[:, None]
            ll += float(np.sum(eta - m - np.log(s0)))
            sc = np.sum(x - mean, axis=0)
            grad += sc
            hess -= np.sum(s2 / s0[:, None, None] - mean[:, :, None] * mean[:, None, :], axis=0)
            scores.append(sc)
        return ll, grad, hess, np.array(scores)

    res = optimize.minimize(lambda b: -parts(b)[0], np.zeros(Xs.shape[1]), jac=lambda b: -parts(b)[1],
                            method="BFGS")
    beta = res.x
    _, _, hess, scores = parts(beta)
    bread = np.linalg.pinv(-hess)
    block_cluster = np.array([clusters[idx[0]] for idx in blocks])
    meat = np.zeros_like(bread)
    for c in np.unique(block_cluster):
        s = scores[block_cluster == c].sum(0)
        meat += np.outer(s, s)
    g = len(np.unique(block_cluster))
    cov = bread @ meat @ bread * (g / max(g - 1, 1))
    j = covariates.index(term)
    b, se = beta[j] / sd[j], np.sqrt(cov[j, j]) / sd[j]
    z = _z(alpha)
    p = float(2 * stats.norm.sf(abs(b / se))) if se > 0 else None
    return Estimate(term, float(b), float(b - z * se), float(b + z * se), p, float(se), len(d), g,
                    "rank-ordered logit per capture, thread-clustered errors", "log-odds of a higher place")


# ---------------------------------------------------------------- bootstrap


def bootstrap_ci(values: np.ndarray, stat=np.median, n: int = 2000, seed: int = 0, alpha: float = 0.05) -> tuple[float, float, float]:
    """Percentile bootstrap over threads. Returns (statistic, low, high)."""
    values = np.asarray(values, float)
    values = values[np.isfinite(values)]
    if len(values) == 0:
        return (np.nan, np.nan, np.nan)
    rng = np.random.default_rng(seed)
    draws = rng.choice(values, size=(n, len(values)), replace=True)
    boots = np.apply_along_axis(stat, 1, draws)
    return float(stat(values)), float(np.quantile(boots, alpha / 2)), float(np.quantile(boots, 1 - alpha / 2))


def holm(pvalues: dict[str, float | None], alpha: float = 0.05) -> dict[str, float | None]:
    """Holm-adjusted p-values for the tests that ran. Missing tests stay None."""
    ran = {k: v for k, v in pvalues.items() if v is not None and np.isfinite(v)}
    order = sorted(ran, key=ran.get)
    m = len(order)
    adjusted, running = {}, 0.0
    for i, k in enumerate(order):
        running = max(running, min(1.0, (m - i) * ran[k]))
        adjusted[k] = running
    return {k: adjusted.get(k) for k in pvalues}
