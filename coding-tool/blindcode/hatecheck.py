"""Validate an AI coder's hate_speech field on HateCheck (Roettger et al., 2021).

HateCheck is 3,728 short test cases in 29 functional tests, each labelled
hateful or non-hateful. It shows *where* a coder fails (for example, flagging
counter-speech or reclaimed slurs as hate), which a single score hides.
"""
from __future__ import annotations

import csv
from collections import defaultdict
from pathlib import Path

from .items import Item
from .reliability import per_class_f1
from .store import CoderStore


def load_cases(path: str | Path, *, limit_per_functionality: int | None = None) -> tuple[list[Item], dict[str, str], dict[str, str]]:
    """Return (items, gold uid->'1'/'0', uid->functionality)."""
    items, gold, func = [], {}, {}
    per: dict[str, int] = defaultdict(int)
    with open(path, newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            f = row["functionality"]
            if limit_per_functionality and per[f] >= limit_per_functionality:
                continue
            per[f] += 1
            uid = f"hc_{row['case_id']}"
            items.append(Item(uid, row["test_case"].strip(), ""))
            gold[uid] = "1" if row["label_gold"] == "hateful" else "0"
            func[uid] = f
    return items, gold, func


def hatecheck_report(store_root: str | Path, coder: str, gold: dict[str, str], func: dict[str, str]) -> str:
    pred = {u: r["values"].get("hate_speech", "") for u, r in CoderStore(store_root, coder).latest().items()}
    pred = {u: v for u, v in pred.items() if u in gold and v != ""}
    if not pred:
        return f"No hate_speech codes from {coder} on HateCheck cases."
    (pos,) = per_class_f1(pred, gold, ["1"])
    acc = sum(pred[u] == gold[u] for u in pred) / len(pred)
    lines = [f"# HateCheck: {coder}", "",
             f"- Cases scored: {len(pred)} of {len(gold)}",
             f"- Accuracy: {acc:.3f}",
             f"- Hateful class: precision {pos.precision or 0:.3f}, recall {pos.recall or 0:.3f}, F1 {pos.f1 or 0:.3f}", "",
             "## By functional test (worst first)", "",
             "| Test | Gold | Cases | Accuracy |", "|---|---|---|---|"]
    by: dict[str, list[str]] = defaultdict(list)
    for u in pred:
        by[func[u]].append(u)
    rows = []
    for f, us in by.items():
        g = {gold[u] for u in us}
        rows.append((sum(pred[u] == gold[u] for u in us) / len(us), f, "hateful" if g == {"1"} else ("non-hateful" if g == {"0"} else "mixed"), len(us)))
    for a, f, g, n in sorted(rows):
        lines.append(f"| {f} | {g} | {n} | {a:.2f} |")
    return "\n".join(lines) + "\n"
