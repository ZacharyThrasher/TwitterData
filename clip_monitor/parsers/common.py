"""Small HTML helpers shared by the site parsers (stdlib only)."""

from __future__ import annotations

import html
import json
import re
from typing import Optional

_TAG = re.compile(r"<[^>]+>")
_SCRIPT_STYLE = re.compile(r"<(script|style)\b.*?</\1>", re.S | re.I)
_FLIGHT_CHUNK = re.compile(r'self\.__next_f\.push\(\[1,"(.*?)"\]\)</script>', re.S)
_MONEY = re.compile(r"\$\s*([\d,]+(?:\.\d+)?)\s*([kKmM])?")


def text_tokens(fragment: str) -> list:
    """Visible text of an HTML fragment, split at tag boundaries, blanks dropped."""
    cleaned = _SCRIPT_STYLE.sub(" ", fragment)
    parts = _TAG.split(cleaned)
    out = []
    for part in parts:
        t = re.sub(r"\s+", " ", html.unescape(part)).strip()
        if t:
            out.append(t)
    return out


def next_flight_payload(page: str) -> str:
    """Join the Next.js React Server Components payload embedded in a page.

    Next.js App Router pages ship their server data as
    self.__next_f.push([1,"..."]) script chunks. Joining and JSON-unescaping
    them gives a text blob that contains the page's data objects.
    Returns "" when the page has no such payload (for example a browser
    "Save as" that dropped scripts).
    """
    chunks = _FLIGHT_CHUNK.findall(page)
    out = []
    for c in chunks:
        try:
            out.append(json.loads('"' + c + '"'))
        except json.JSONDecodeError:
            continue
    return "".join(out)


def balanced_json_after(blob: str, key: str) -> Optional[object]:
    """Parse the JSON object or array that follows `"key":` in blob."""
    marker = f'"{key}":'
    i = blob.find(marker)
    if i < 0:
        return None
    start = i + len(marker)
    while start < len(blob) and blob[start] in " \t\n":
        start += 1
    if start >= len(blob) or blob[start] not in "{[":
        return None
    opener = blob[start]
    closer = "}" if opener == "{" else "]"
    depth = 0
    in_str = False
    escape = False
    for k in range(start, len(blob)):
        ch = blob[k]
        if in_str:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == opener:
            depth += 1
        elif ch == closer:
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(blob[start : k + 1])
                except json.JSONDecodeError:
                    return None
    return None


def parse_money(text: str) -> Optional[float]:
    """'$2,100' -> 2100.0, '$1.5K' -> 1500.0, no match -> None."""
    m = _MONEY.search(text or "")
    if not m:
        return None
    value = float(m.group(1).replace(",", ""))
    suffix = (m.group(2) or "").lower()
    if suffix == "k":
        value *= 1_000
    elif suffix == "m":
        value *= 1_000_000
    return value


def parse_count(text: str) -> Optional[int]:
    """'100K' -> 100000, '5,000' -> 5000, '1.2M' -> 1200000."""
    m = re.search(r"([\d,]+(?:\.\d+)?)\s*([kKmM])?", text or "")
    if not m:
        return None
    value = float(m.group(1).replace(",", ""))
    suffix = (m.group(2) or "").lower()
    if suffix == "k":
        value *= 1_000
    elif suffix == "m":
        value *= 1_000_000
    return int(round(value))


def per_1k(amount: Optional[float], per_views_label: str) -> Optional[float]:
    """Convert a rate quoted 'per 1M views' / 'per 100k' / 'per 1,000' to per 1,000 views."""
    if amount is None:
        return None
    label = per_views_label.lower().replace(",", "").replace(" ", "")
    if "1m" in label or "1000000" in label:
        return amount / 1000
    if "100k" in label or "100000" in label:
        return amount / 100
    if "10k" in label or "10000" in label:
        return amount / 10
    if "1k" in label or "1000" in label:
        return amount
    return None
