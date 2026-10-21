"""Draw a coding sample (pilot or gold set) that oversamples rare classes.

Rare classes (hate speech, threats, slurs) barely occur in a random sample,
which leaves alpha unstable. With --enrich-coder, items an existing coder
(usually a free AI pre-pass) marked positive on a field are drawn first, up
to --min-per-field each; the rest of the sample is random. Pre-labels only
steer selection; coders never see them.
"""
from __future__ import annotations

import random

from .items import Item


def draw_sample(items: list[Item], n: int, *, seed: int = 0, prelabels: dict[str, dict[str, str]] | None = None,
                fields: list[str] | None = None, min_per_field: int = 50, exclude: set[str] | None = None) -> tuple[list[Item], dict]:
    rng = random.Random(seed)
    pool = [it for it in items if not exclude or it.uid not in exclude]
    if n > len(pool):
        raise ValueError(f"asked for {n} items but only {len(pool)} are available")
    chosen: dict[str, Item] = {}
    report = {}
    for field in fields or []:
        positives = [it for it in pool if (prelabels or {}).get(it.uid, {}).get(field) == "1" and it.uid not in chosen]
        rng.shuffle(positives)
        take = positives[: max(0, min(min_per_field, n - len(chosen)))]
        for it in take:
            chosen[it.uid] = it
        report[field] = {"flagged": len(positives), "taken": len(take)}
    rest = [it for it in pool if it.uid not in chosen]
    rng.shuffle(rest)
    for it in rest[: n - len(chosen)]:
        chosen[it.uid] = it
    out = list(chosen.values())
    rng.shuffle(out)
    return out, report
