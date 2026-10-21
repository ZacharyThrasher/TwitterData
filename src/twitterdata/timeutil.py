"""Timestamp parsing shared by the loader, parser and CLI."""

from __future__ import annotations

import re
from datetime import datetime, timezone

_FRACTION = re.compile(r"\.(\d+)")


def parse_iso_utc(value) -> datetime | None:
    """Parse an ISO 8601 string to an aware UTC datetime, or None.

    Accepts a trailing Z and any number of fractional-second digits, which
    Python 3.10's fromisoformat does not.
    """
    if not isinstance(value, str) or not value:
        return None
    text = value.strip().replace("Z", "+00:00").replace("z", "+00:00")
    text = _FRACTION.sub(lambda m: "." + m.group(1)[:6].ljust(6, "0"), text, count=1)
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
