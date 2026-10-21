"""Turn TweetDetail responses into reply table rows (schema v1)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime, timezone

from twitterdata.capture.safe_har import CaptureResponse, load_capture
from twitterdata.capture.tweetdetail import parse_page, tweet_fields, tweet_id, user_fields
from twitterdata.privacy import pseudonym, scrub_rows
from twitterdata.schema import COLUMN_NAMES, SCHEMA_VERSION

PLATFORM = "x"
RANKING_MODES = {"relevance": "relevance", "recency": "recent", "recent": "recent", "likes": "likes"}


@dataclass
class CaptureMeta:
    """Per-capture settings supplied by the person running the parser."""

    viewer_type: str = "unknown"
    viewer_label: str | None = None
    capture_id: str | None = None
    sort_order: str | None = None  # overrides the request's rankingMode
    age_bucket: str | None = None
    focal_tweet_id: str | None = None  # needed only for raw JSON input without a focal entry
    capture_time: datetime | None = None  # raw JSON input only
    include_text: bool = False


@dataclass
class _Session:
    number: int
    focal_id: str
    sort_order: str
    sort_source: str
    started: datetime | None
    rank_is_absolute: bool
    focal: dict | None = None
    conversation_id: str | None = None  # from the replies, for captures without the focal tweet
    page_index: int = -1
    display_index: int = 0
    display_rank: int = 0
    seen: set = field(default_factory=set)
    # module entryId -> [next module_position, sort_index, section]
    modules: dict = field(default_factory=dict)


@dataclass
class ParseResult:
    rows: list[dict]
    stats: dict


def iso_utc(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def _sort_order(resp: CaptureResponse, meta: CaptureMeta) -> tuple[str, str]:
    if meta.sort_order:
        return meta.sort_order, "flag"
    if resp.ranking_mode:
        return RANKING_MODES.get(resp.ranking_mode.lower(), "unknown"), "request"
    if resp.has_cursor is None:
        return "unknown", "unknown"
    return "relevance", "default"


def _focal_columns(salt: bytes, focal: dict | None) -> dict:
    if focal is None:
        return {"thread_id": None, "focal_author_id_hash": None, "focal_author_followers": None,
                "focal_author_is_blue_verified": None, "focal_author_verified_type": None,
                "focal_author_affiliate_label": None, "focal_view_count": None,
                "focal_like_count": None, "focal_reply_count": None}
    t, u = tweet_fields(focal), user_fields(focal)
    return {
        "thread_id": t["conversation_id"] or t["id"],
        "focal_author_id_hash": pseudonym(salt, PLATFORM, "user", u["id"]),
        "focal_author_followers": u["followers"],
        "focal_author_is_blue_verified": u["is_blue_verified"],
        "focal_author_verified_type": u["verified_type"],
        "focal_author_affiliate_label": u["affiliate_label"],
        "focal_view_count": t["views"],
        "focal_like_count": t["likes"],
        "focal_reply_count": t["replies"],
    }


def _place_in_module(session: _Session, item) -> None:
    """Give items appended by "Show replies" positions after the module's
    existing items, and the module's sort index and section."""
    if item.module_id is None:
        return
    state = session.modules.get(item.module_id)
    if not item.appended:
        if state is None:
            session.modules[item.module_id] = [item.module_position + 1, item.sort_index, item.section]
        else:
            state[0] = max(state[0], item.module_position + 1)
        return
    if state is None:
        state = session.modules[item.module_id] = [1, None, None]
    item.module_position = state[0]
    state[0] += 1
    item.sort_index = item.sort_index or state[1]
    item.section = item.section or state[2]


def build_rows(responses: list[CaptureResponse], meta: CaptureMeta, salt: bytes,
               capture_file: str, fallback_time: datetime | None = None) -> ParseResult:
    capture_id = meta.capture_id or os.path.splitext(capture_file)[0]
    sessions: dict[tuple[str, str], _Session] = {}
    all_sessions: list[_Session] = []
    rows: list[dict] = []
    stats = {"pages": 0, "unavailable": 0, "duplicates": 0, "no_focal_id": 0, "no_author_id": 0}
    last_focal_id = meta.focal_tweet_id

    for resp in responses:
        focal_id = resp.focal_tweet_id or meta.focal_tweet_id
        page = parse_page(resp.body, focal_id)
        if focal_id is None and page.focal is not None:
            focal_id = tweet_id(page.focal)
        focal_id = focal_id or last_focal_id
        if focal_id is None:
            stats["no_focal_id"] += 1
            continue
        last_focal_id = focal_id
        stats["pages"] += 1
        stats["unavailable"] += page.unavailable

        sort_order, sort_source = _sort_order(resp, meta)
        key = (focal_id, sort_order)
        top_of_thread = resp.has_cursor is False or (resp.has_cursor is None and page.focal is not None)
        session = sessions.get(key)
        if session is None or top_of_thread:
            started = resp.started_utc or meta.capture_time or fallback_time
            session = _Session(len(all_sessions) + 1, focal_id, sort_order, sort_source,
                               started, rank_is_absolute=top_of_thread)
            sessions[key] = session
            all_sessions.append(session)
        session.page_index += 1
        if page.focal is not None and session.focal is None:
            session.focal = page.focal

        for item in page.items:
            t = tweet_fields(item.tweet)
            u = user_fields(item.tweet)
            if t["id"] is None:
                stats["unavailable"] += 1
                continue
            if u["id"] is None:
                stats["no_author_id"] += 1
                continue
            if t["id"] in session.seen:
                stats["duplicates"] += 1
                continue
            session.seen.add(t["id"])
            if item.row_type != "promoted" and session.conversation_id is None:
                session.conversation_id = t["conversation_id"]
            _place_in_module(session, item)
            session.display_index += 1
            rank = None
            if item.row_type == "reply":
                session.display_rank += 1
                rank = session.display_rank
            rows.append({
                "_session": session,
                "schema_version": SCHEMA_VERSION,
                "platform": PLATFORM,
                "capture_id": capture_id,
                "capture_file": capture_file,
                "capture_session": session.number,
                "capture_time_utc": iso_utc(session.started),
                "page_index": session.page_index,
                "viewer_type": meta.viewer_type,
                "viewer_label": meta.viewer_label,
                "sort_order": session.sort_order,
                "sort_order_source": session.sort_source,
                "age_bucket": meta.age_bucket,
                "focal_tweet_id": session.focal_id,
                "row_type": item.row_type,
                "is_promoted": item.row_type == "promoted",
                "display_rank": rank,
                "display_index": session.display_index,
                "rank_is_absolute": session.rank_is_absolute,
                "module_position": item.module_position,
                "conversation_section": item.section,
                "sort_index": item.sort_index,
                "tweet_id": t["id"],
                "in_reply_to_tweet_id": t["in_reply_to"],
                "created_at_utc": iso_utc(t["created_at"]),
                "lang": t["lang"],
                "is_quote": t["is_quote"],
                "has_media": t["has_media"],
                "view_count": t["views"],
                "like_count": t["likes"],
                "reply_count": t["replies"],
                "repost_count": t["reposts"],
                "quote_count": t["quotes"],
                "bookmark_count": t["bookmarks"],
                "text": t["text"] if meta.include_text else None,
                "author_id_hash": pseudonym(salt, PLATFORM, "user", u["id"]),
                "author_handle_hash": pseudonym(salt, PLATFORM, "handle",
                                                u["handle"].lower() if u["handle"] else None),
                "author_is_focal_author": False,
                "author_is_blue_verified": u["is_blue_verified"],
                "author_verified_type": u["verified_type"],
                "author_affiliate_label": u["affiliate_label"],
                "author_professional_type": u["professional_type"],
                "author_followers": u["followers"],
                "author_following": u["following"],
                "author_statuses": u["statuses"],
                "author_created_at_utc": iso_utc(u["created_at"]),
            })

    # Thread columns are filled last: the focal tweet may arrive on a later
    # page of the session than the first rows (captures that began mid-thread).
    finished = []
    for row in rows:
        session = row.pop("_session")
        row.update(_focal_columns(salt, session.focal))
        if row["thread_id"] is None:
            row["thread_id"] = session.conversation_id
        row["author_is_focal_author"] = (row["focal_author_id_hash"] is not None
                                         and row["author_id_hash"] == row["focal_author_id_hash"])
        finished.append({name: row.get(name) for name in COLUMN_NAMES})

    stats["sessions"] = len(all_sessions)
    stats["rows"] = len(finished)
    stats["redacted_cells"] = scrub_rows(finished)
    return ParseResult(finished, stats)


def parse_capture(path: str, meta: CaptureMeta, salt: bytes) -> ParseResult:
    responses, load_stats = load_capture(path, meta.capture_time)
    mtime = datetime.fromtimestamp(os.path.getmtime(path), tz=timezone.utc)
    result = build_rows(responses, meta, salt, os.path.basename(path), fallback_time=mtime)
    result.stats = {**load_stats, **result.stats}
    return result
