"""Build the blind item file coders work from.

Only three columns ever leave the source: uid, text and context (which
thread the reply belongs to). Handles, verification status, metrics and
ranks never reach a coder, so they cannot bias the codes.
"""
from __future__ import annotations

import csv
import hashlib
import random
import re
from dataclasses import dataclass
from pathlib import Path

BLIND_COLUMNS = ("uid", "text", "context")

# A run of @handles at the start of a reply is the reply-to chain X adds.
_LEADING_MENTIONS = re.compile(r"^(?:\s*@\w{1,15})+\s*")


@dataclass(frozen=True)
class Item:
    uid: str
    text: str
    context: str = ""


def strip_leading_mentions(text: str) -> str:
    return _LEADING_MENTIONS.sub("", text, count=1).strip()


def build_items(source: str | Path, out: str | Path, *, id_col: str = "uid", text_col: str = "full_text",
                context_col: str | None = "thread", author_col: str | None = "screen_name",
                keep_mentions: bool = False) -> tuple[list[Item], list[str]]:
    """Write a blind items CSV from a source CSV. Returns (items, warnings)."""
    items, warnings, seen = [], [], set()
    with open(source, newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        cols = reader.fieldnames or []
        for needed in (id_col, text_col):
            if needed not in cols:
                raise ValueError(f"column {needed!r} not in source ({len(cols)} columns)")
        if context_col and context_col not in cols:
            raise ValueError(f"context column {context_col!r} not in source")
        for row in reader:
            uid = row[id_col].strip()
            if not uid:
                continue
            if uid in seen:
                raise ValueError(f"duplicate uid {uid}")
            seen.add(uid)
            text = row[text_col] if keep_mentions else strip_leading_mentions(row[text_col])
            author = (row.get(author_col) or "").strip() if author_col else ""
            if author and re.search(rf"@{re.escape(author)}\b", text, re.I):
                warnings.append(f"{uid}: text mentions its own author's handle")
            items.append(Item(uid, text, row[context_col].strip() if context_col else ""))
    write_items(items, out)
    return items, warnings


def write_items(items: list[Item], path: str | Path) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(BLIND_COLUMNS)
        for it in items:
            w.writerow([it.uid, it.text, it.context])


def load_items(path: str | Path) -> list[Item]:
    """Load a blind items file. Refuses files carrying any extra column."""
    with open(path, newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        extra = set(reader.fieldnames or []) - set(BLIND_COLUMNS)
        if extra:
            raise ValueError(f"items file is not blind; extra columns: {sorted(extra)}. Rebuild it with build-items.")
        return [Item(r["uid"], r["text"], r.get("context") or "") for r in reader]


def coder_order(items: list[Item], coder: str) -> list[Item]:
    """Stable per-coder shuffle, so coders see items in different orders."""
    seed = int(hashlib.sha256(coder.encode()).hexdigest()[:16], 16)
    out = list(items)
    random.Random(seed).shuffle(out)
    return out
