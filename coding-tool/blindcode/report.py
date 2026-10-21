"""Markdown agreement report: verdicts first, detail after."""
from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path

from . import reliability as R
from .codebook import Codebook
from .store import load_all

RARE_MINORITY = 10   # fewer minority codes than this makes alpha unstable
GROUP_GAP = 0.10     # F1 gap between groups that counts as a red flag


def _f(x: float | None) -> str:
    return "n/a" if x is None else f"{x:.3f}"


def _ci(r: R.AlphaResult) -> str:
    return "" if r.ci_low is None else f" [{r.ci_low:.2f}, {r.ci_high:.2f}]"


def _overall(verdicts: list[str]) -> str:
    """FAIL beats BLOCKED beats PASS; N/A fields neither pass nor fail."""
    if "FAIL" in verdicts:
        return "FAIL"
    if "BLOCKED" in verdicts:
        return "BLOCKED (humans must pass first)"
    return "PASS" if "PASS" in verdicts else "N/A"


def _tally(verdicts: list[str]) -> str:
    parts = [f"{verdicts.count(v)} {v}" for v in ("PASS", "FAIL", "BLOCKED", "N/A") if verdicts.count(v)]
    return f" ({', '.join(parts)} of {len(verdicts)})"


@dataclass
class FieldSummary:
    name: str
    key: bool
    human: R.AlphaResult | None
    human_verdict: str
    ai_alphas: dict[str, dict[str, R.AlphaResult]] = field(default_factory=dict)  # ai -> human -> result
    ai_verdicts: dict[str, str] = field(default_factory=dict)


def field_codes(records: dict[str, dict[str, dict]], name: str) -> R.Codes:
    return {c: {u: rec["values"].get(name, "") for u, rec in recs.items()} for c, recs in records.items()}


def split_coders(records: dict[str, dict[str, dict]]) -> tuple[list[str], list[str]]:
    humans, ais = [], []
    for c, recs in records.items():
        kinds = {r.get("kind", "human") for r in recs.values()}
        (ais if kinds == {"ai"} else humans).append(c)
    return sorted(humans), sorted(ais)


def load_groups(path: str | Path, col: str) -> dict[str, str]:
    with open(path, newline="", encoding="utf-8") as fh:
        return {r["uid"]: r[col] for r in csv.DictReader(fh) if r.get(col, "") != ""}


def build_report(store_root: str | Path, codebook: Codebook, *, humans: list[str] | None = None,
                 ais: list[str] | None = None, reference: str | None = None, groups: dict[str, str] | None = None,
                 group_label: str = "group", n_boot: int = 1000) -> tuple[str, list[FieldSummary]]:
    records = load_all(store_root)
    auto_h, auto_a = split_coders(records)
    humans = humans if humans is not None else [c for c in auto_h if c != reference]
    ais = ais if ais is not None else auto_a
    missing = [c for c in humans + ais + ([reference] if reference else []) if c not in records]
    if missing:
        raise ValueError(f"no stored codes for: {missing}")

    summaries: list[FieldSummary] = []
    for f in codebook.coded_fields:
        codes = field_codes(records, f.name)
        h = R.alpha_with_ci(codes, humans, n_boot=n_boot) if len(humans) >= 2 else None
        fs = FieldSummary(f.name, f.key, h, R.human_verdict(h.alpha if h else None))
        for ai in ais:
            fs.ai_alphas[ai] = {hu: R.alpha_with_ci(codes, [ai, hu], n_boot=n_boot) for hu in humans}
            fs.ai_verdicts[ai] = R.ai_verdict([r.alpha for r in fs.ai_alphas[ai].values()], h.alpha if h else None)
        summaries.append(fs)

    L: list[str] = []
    L += [f"# Coding agreement report ({codebook.id})", ""]
    L += [f"- Human coders: {', '.join(humans) or 'none'}", f"- AI coders: {', '.join(ais) or 'none'}"]
    ref_label = reference or "human consensus (items where all humans agree)"
    L += [f"- Reference for F1: {ref_label}", f"- Pass rule: humans alpha >= {R.PASS_ALPHA}; AI worst alpha vs any human >= human alpha - {R.AI_MARGIN}", ""]

    # 1. Verdicts
    keys = [s for s in summaries if s.key]
    L += ["## 1. Verdict", ""]
    if len(humans) < 2:
        L += ["Not enough human coders yet: at least two are needed before any verdict.", ""]
    else:
        hvs = [s.human_verdict for s in keys]
        L.append(f"- **Humans: {_overall(hvs)}** on key fields{_tally(hvs)}")
        for ai in ais:
            avs = [s.ai_verdicts[ai] for s in keys]
            L.append(f"- **AI `{ai}`: {_overall(avs)}** on key fields{_tally(avs)}")
        if any(v == "N/A" for s in keys for v in [s.human_verdict, *s.ai_verdicts.values()]):
            L.append("- N/A means alpha is undefined for that field (no variation), so it cannot pass or fail yet.")
        L.append("")

    # 2. Field table
    L += ["## 2. Alpha by field", ""]
    head = "| Field | Key | Humans alpha [95% CI] | Verdict |" + "".join(f" {ai} worst | {ai} rule |" for ai in ais)
    L += [head, "|" + "---|" * (4 + 2 * len(ais))]
    for s in summaries:
        row = f"| {s.name} | {'yes' if s.key else 'no'} | {(_f(s.human.alpha) + _ci(s.human)) if s.human else 'n/a'} | {s.human_verdict} |"
        for ai in ais:
            al = [r.alpha for r in s.ai_alphas[ai].values()]
            worst = None if not al or any(a is None for a in al) else min(al)
            row += f" {_f(worst)} | {s.ai_verdicts[ai]} |"
        L.append(row)
    L.append("")

    # 3. Warnings
    warn = []
    shas = {rec.get("codebook_sha256") for c in humans + ais for rec in records[c].values()}
    if len(shas) > 1:
        warn.append(f"Coders used {len(shas)} different codebook versions. Freeze the codebook and recode.")
    if codebook.sha256 not in shas and shas:
        warn.append("Stored codes were made with a different codebook file than the one this report loaded.")
    for s in summaries:
        if codebook.field(s.name).type == "binary" and s.human and s.human.n_units and 0 < s.human.minority_count < RARE_MINORITY:
            warn.append(f"`{s.name}`: only {s.human.minority_count} codes in the rarest class across {s.human.n_units} items; alpha is unstable. Oversample this class.")
        if s.human and s.human.alpha is None and s.human.n_units:
            warn.append(f"`{s.name}`: every coder gave the same value to every item, so alpha is undefined.")
    L += ["## 3. Warnings", ""] + ([f"- {w}" for w in warn] or ["- None."]) + [""]

    # 4. Pairwise
    L += ["## 4. Pairwise alpha", ""]
    pairs = [(a, b) for i, a in enumerate(humans + ais) for b in (humans + ais)[i + 1:]]
    if pairs:
        L += ["| Field | " + " | ".join(f"{a} vs {b}" for a, b in pairs) + " |", "|---|" + "---|" * len(pairs)]
        for f in codebook.coded_fields:
            codes = field_codes(records, f.name)
            L.append(f"| {f.name} | " + " | ".join(_f(R.krippendorff_alpha(codes, [a, b])) for a, b in pairs) + " |")
        L.append("")

    # 5. AI vs reference
    if ais:
        L += ["## 5. AI vs reference: precision, recall, F1", ""]
        for ai in ais:
            L += [f"### {ai}", "", "| Field | Class | Precision | Recall | F1 | Support |", "|---|---|---|---|---|---|"]
            for f in codebook.coded_fields:
                codes = field_codes(records, f.name)
                ref = codes[reference] if reference else R.consensus(codes, humans)
                labels = ["1"] if f.type == "binary" else list(f.options)
                for cs in R.per_class_f1(codes[ai], ref, labels):
                    if cs.support or f.type == "binary":
                        L.append(f"| {f.name} | {cs.label} | {_f(cs.precision)} | {_f(cs.recall)} | {_f(cs.f1)} | {cs.support} |")
            L.append("")

    # 6. Bias check
    if ais and groups:
        L += [f"## 6. Bias check by {group_label}", "",
              f"F1 for the positive class, split by {group_label}. A gap above {GROUP_GAP:.2f} is flagged.", ""]
        names = sorted(set(groups.values()))
        for ai in ais:
            L += [f"### {ai}", "", "| Field | " + " | ".join(names) + " | Gap | Flag |", "|---|" + "---|" * (len(names) + 2)]
            for f in codebook.coded_fields:
                if f.type != "binary":
                    continue
                codes = field_codes(records, f.name)
                ref = codes[reference] if reference else R.consensus(codes, humans)
                f1s = []
                for g in names:
                    sub = {u: v for u, v in ref.items() if groups.get(u) == g}
                    f1s.append(R.per_class_f1(codes[ai], sub, ["1"])[0].f1)
                known = [x for x in f1s if x is not None]
                gap = max(known) - min(known) if len(known) >= 2 else None
                flag = "RED FLAG" if gap is not None and gap > GROUP_GAP else ""
                L.append(f"| {f.name} | " + " | ".join(_f(x) for x in f1s) + f" | {_f(gap)} | {flag} |")
            L.append("")

    return "\n".join(L), summaries
