"""Safe loading of browser captures.

Raw HAR files from a logged-in browser hold live session secrets: the
`auth_token`, `ct0` and `twid` cookies, the `authorization` bearer header,
the `x-csrf-token` header and `set-cookie` response headers. This module is
the only place that opens a capture file, and it is built so those values
never leave the JSON decoder:

* Every `headers`, `cookies`, `postData` and `queryString` object is dropped
  while the file is decoded, before the HAR dict exists.
* Only entries whose URL path is an X `TweetDetail` GraphQL call are kept.
* From the request URL only an allowlist of `variables` keys is read
  (focal tweet id, ranking mode, and whether a cursor was present). The URL
  itself and the cursor value are not kept.
* Nothing here prints, logs or raises with entry contents.

The result is a list of `CaptureResponse` objects holding nothing but what
the reply parser needs.
"""

from __future__ import annotations

import base64
import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlsplit

from twitterdata.timeutil import parse_iso_utc

# Keys dropped at decode time, at any depth of the HAR document.
DROPPED_HAR_KEYS = frozenset({"headers", "cookies", "postData", "queryString"})

TWEETDETAIL_PATH = re.compile(r"^/i/api/graphql/[A-Za-z0-9_-]+/TweetDetail$")
X_HOSTS = frozenset({"x.com", "twitter.com", "api.x.com", "api.twitter.com"})


class CaptureError(Exception):
    """A capture could not be read. Messages never include file contents."""


@dataclass(frozen=True)
class CaptureResponse:
    """One TweetDetail response, stripped to what the parser needs."""

    entry_index: int
    started_utc: datetime | None
    focal_tweet_id: str | None
    ranking_mode: str | None
    has_cursor: bool | None  # None when the request is unknown (raw JSON input)
    body: dict


def _drop_secret_keys(pairs):
    return {k: v for k, v in pairs if k not in DROPPED_HAR_KEYS}


def _is_tweetdetail_url(url: str) -> bool:
    try:
        parts = urlsplit(url)
    except ValueError:
        return False
    host = (parts.hostname or "").lower()
    return host in X_HOSTS and bool(TWEETDETAIL_PATH.match(parts.path))


def _allowed_variables(url: str) -> tuple[str | None, str | None, bool | None]:
    """Read focalTweetId, rankingMode and cursor presence from the URL.

    Cursor presence is None when the variables cannot be read (for example a
    POST request, whose body is dropped), so the page is not mistaken for a
    load from the top of the thread.
    """
    try:
        raw = parse_qs(urlsplit(url).query).get("variables", [None])[0]
        variables = json.loads(raw) if raw else None
    except (ValueError, TypeError):
        variables = None
    if not isinstance(variables, dict):
        return None, None, None
    focal = variables.get("focalTweetId")
    mode = variables.get("rankingMode")
    return (
        str(focal) if focal is not None else None,
        mode if isinstance(mode, str) else None,
        bool(variables.get("cursor")),
    )


def _decode_body(content: dict) -> dict | None:
    text = content.get("text")
    if not isinstance(text, str) or not text:
        return None
    try:
        if content.get("encoding") == "base64":
            text = base64.b64decode(text).decode("utf-8")
        body = json.loads(text)
    except (ValueError, UnicodeDecodeError):
        return None
    return body if isinstance(body, dict) else None


def _read_safely(path: str):
    """Decode a capture file with secret-bearing keys dropped at decode time.

    Every input goes through this, whatever its extension, so a HAR saved
    under another name gets the same protection.
    """
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return json.load(f, object_pairs_hook=_drop_secret_keys)
    except (OSError, ValueError):
        raise CaptureError(f"could not read {os.path.basename(path)} as JSON") from None


def _har_responses(har: dict) -> tuple[list[CaptureResponse], dict]:
    """Return the TweetDetail responses in a decoded HAR and skip counts."""
    entries = har.get("log", {}).get("entries", [])
    if not isinstance(entries, list):
        entries = []
    responses: list[CaptureResponse] = []
    stats = {"entries": len(entries), "tweetdetail": 0, "skipped_status": 0, "skipped_body": 0}
    for i, entry in enumerate(entries):
        if not isinstance(entry, dict):
            continue
        request = entry.get("request") or {}
        url = request.get("url")
        if not isinstance(url, str) or not _is_tweetdetail_url(url):
            continue
        stats["tweetdetail"] += 1
        response = entry.get("response") or {}
        if response.get("status") != 200:
            stats["skipped_status"] += 1
            continue
        body = _decode_body(response.get("content") or {})
        if body is None:
            stats["skipped_body"] += 1
            continue
        focal, mode, has_cursor = _allowed_variables(url)
        responses.append(CaptureResponse(
            entry_index=i,
            started_utc=parse_iso_utc(entry.get("startedDateTime")),
            focal_tweet_id=focal,
            ranking_mode=mode,
            has_cursor=has_cursor,
            body=body,
        ))
    return responses, stats


def load_capture(path: str, capture_time: datetime | None = None) -> tuple[list[CaptureResponse], dict]:
    """Load a HAR export, or a single TweetDetail response body saved as JSON.

    A saved response has no request, so focal tweet id, ranking mode and
    cursor presence are unknown and come from flags or the data (a first
    page is recognised by the focal tweet entry it contains). Its capture
    time is `capture_time`, else the file modification time.
    """
    doc = _read_safely(path)
    name = os.path.basename(path)
    if isinstance(doc, dict) and isinstance(doc.get("log"), dict):
        return _har_responses(doc)
    if not isinstance(doc, dict) or "data" not in doc:
        raise CaptureError(f"{name} is neither a HAR file nor a TweetDetail response body")
    if capture_time is None:
        capture_time = datetime.fromtimestamp(os.path.getmtime(path), tz=timezone.utc)
    resp = CaptureResponse(entry_index=0, started_utc=capture_time, focal_tweet_id=None,
                           ranking_mode=None, has_cursor=None, body=doc)
    return [resp], {"entries": 1, "tweetdetail": 1, "skipped_status": 0, "skipped_body": 0}


def load_har(path: str) -> tuple[list[CaptureResponse], dict]:
    """Load a HAR file; anything else is an error."""
    doc = _read_safely(path)
    if not isinstance(doc, dict) or not isinstance(doc.get("log"), dict):
        raise CaptureError(f"{os.path.basename(path)} is not a HAR file")
    return _har_responses(doc)
