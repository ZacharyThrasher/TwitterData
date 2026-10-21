"""Agreement statistics: Krippendorff's alpha (nominal), pass rules, F1.

Data shape used throughout: codes[coder][uid] = value (string). Missing or
empty values are skipped, as Krippendorff's alpha allows.
"""
from __future__ import annotations

import math
import random
from collections import Counter
from dataclasses import dataclass
from itertools import combinations

PASS_ALPHA = 0.67  # pre-registered pass rule (Krippendorff: lowest level for tentative conclusions)
AI_MARGIN = 0.05    # pre-registered: AI alpha must be >= human alpha - 0.05

Codes = dict[str, dict[str, str]]


def _units(codes: Codes, coders: list[str]) -> list[Counter]:
    """Per-unit value counts across the given coders; only units with 2+ values."""
    uids = set()
    for c in coders:
        uids |= set(codes.get(c, {}))
    out = []
    for uid in sorted(uids):
        vals = [codes[c][uid] for c in coders if codes.get(c, {}).get(uid, "") not in ("", None)]
        if len(vals) >= 2:
            out.append(Counter(vals))
    return out


def _unit_contrib(cnt: Counter) -> tuple[float, dict[str, float]]:
    """(observed disagreement, per-value pairable counts) for one unit."""
    m = sum(cnt.values())
    same = sum(v * (v - 1) for v in cnt.values())
    do = (m * (m - 1) - same) / (m - 1)
    return do, {k: float(v) for k, v in cnt.items()}


def _alpha_from(contribs: list[tuple[float, dict[str, float]]]) -> float | None:
    n_c: Counter = Counter()
    do = 0.0
    for d, nc in contribs:
        do += d
        n_c.update(nc)
    n = sum(n_c.values())
    if n <= 1:
        return None
    de = (n * n - sum(v * v for v in n_c.values())) / (n - 1)
    if de == 0:
        return None  # no variation at all: alpha undefined
    return 1.0 - do / de


def krippendorff_alpha(codes: Codes, coders: list[str]) -> float | None:
    """Nominal Krippendorff's alpha over the given coders. None when undefined."""
    return _alpha_from([_unit_contrib(u) for u in _units(codes, coders)])


@dataclass
class AlphaResult:
    coders: tuple[str, ...]
    alpha: float | None
    ci_low: float | None
    ci_high: float | None
    n_units: int
    value_counts: dict[str, int]

    @property
    def minority_count(self) -> int:
        return min(self.value_counts.values()) if len(self.value_counts) > 1 else 0


def alpha_with_ci(codes: Codes, coders: list[str], *, n_boot: int = 1000, seed: int = 0) -> AlphaResult:
    """Alpha plus a unit-level bootstrap 95% percentile interval."""
    units = _units(codes, coders)
    contribs = [_unit_contrib(u) for u in units]
    vc: Counter = Counter()
    for u in units:
        vc.update(u)
    a = _alpha_from(contribs)
    lo = hi = None
    if a is not None and n_boot and len(contribs) > 1:
        rng = random.Random(seed)
        boots = []
        for _ in range(n_boot):
            b = _alpha_from([contribs[rng.randrange(len(contribs))] for _ in contribs])
            if b is not None:
                boots.append(b)
        if boots:
            boots.sort()
            lo = boots[int(0.025 * (len(boots) - 1))]
            hi = boots[int(math.ceil(0.975 * (len(boots) - 1)))]
    return AlphaResult(tuple(coders), a, lo, hi, len(units), dict(vc))


def pairwise(codes: Codes, coders: list[str], **kw) -> dict[tuple[str, str], AlphaResult]:
    return {(a, b): alpha_with_ci(codes, [a, b], **kw) for a, b in combinations(coders, 2)}


def consensus(codes: Codes, coders: list[str]) -> dict[str, str]:
    """Value per uid where every coder who coded it agrees (2+ coders)."""
    out = {}
    uids = set().union(*(codes.get(c, {}).keys() for c in coders)) if coders else set()
    for uid in uids:
        vals = {codes[c][uid] for c in coders if codes.get(c, {}).get(uid, "") != ""}
        n = sum(1 for c in coders if codes.get(c, {}).get(uid, "") != "")
        if n >= 2 and len(vals) == 1:
            out[uid] = vals.pop()
    return out


@dataclass
class ClassScore:
    label: str
    precision: float | None
    recall: float | None
    f1: float | None
    support: int


def per_class_f1(pred: dict[str, str], ref: dict[str, str], labels: list[str] | None = None) -> list[ClassScore]:
    """Precision/recall/F1 of pred against ref on shared uids."""
    uids = [u for u in ref if pred.get(u, "") != "" and ref[u] != ""]
    labels = labels or sorted({ref[u] for u in uids} | {pred[u] for u in uids})
    out = []
    for lab in labels:
        tp = sum(1 for u in uids if pred[u] == lab and ref[u] == lab)
        fp = sum(1 for u in uids if pred[u] == lab and ref[u] != lab)
        fn = sum(1 for u in uids if pred[u] != lab and ref[u] == lab)
        p = tp / (tp + fp) if tp + fp else None
        r = tp / (tp + fn) if tp + fn else None
        f = 2 * p * r / (p + r) if p and r else (0.0 if tp + fn else None)
        out.append(ClassScore(lab, p, r, f, tp + fn))
    return out


def confusion(pred: dict[str, str], ref: dict[str, str]) -> dict[tuple[str, str], int]:
    """(ref, pred) -> count on shared uids."""
    c: Counter = Counter()
    for u, r in ref.items():
        p = pred.get(u, "")
        if p != "" and r != "":
            c[(r, p)] += 1
    return dict(c)


def human_verdict(alpha: float | None) -> str:
    if alpha is None:
        return "N/A"
    return "PASS" if alpha >= PASS_ALPHA else "FAIL"


def ai_verdict(ai_alphas: list[float | None], human_alpha: float | None) -> str:
    """Pre-registered rule: worst AI-vs-human alpha >= human-vs-human alpha - 0.05.

    Only meaningful once humans themselves pass.
    """
    if human_alpha is None or any(a is None for a in ai_alphas) or not ai_alphas:
        return "N/A"
    if human_verdict(human_alpha) != "PASS":
        return "BLOCKED"
    return "PASS" if min(ai_alphas) >= human_alpha - AI_MARGIN - 1e-9 else "FAIL"
