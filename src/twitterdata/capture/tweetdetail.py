"""Read items out of one X TweetDetail GraphQL response body.

X has shipped two user-object layouts in 2025-2026 (counts under `legacy`,
or under `relationship_counts` / `tweet_counts` with names under `core`), so
every field lookup tries both.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from twitterdata.timeutil import parse_iso_utc

TWITTER_EPOCH_MS = 1288834974657


@dataclass
class Item:
    """One tweet shown on the page, before session bookkeeping."""

    row_type: str  # reply | nested_reply | promoted
    module_position: int
    section: str | None
    sort_index: str | None
    tweet: dict
    module_id: str | None = None  # entryId of the reply module the item sits in
    appended: bool = False  # added later by "Show replies" (TimelineAddToModule)


@dataclass
class Page:
    focal: dict | None  # focal tweet object when this page carries it
    items: list[Item]
    unavailable: int  # tombstones and withheld tweets skipped


def _get(d, *path, default=None):
    for key in path:
        if not isinstance(d, dict):
            return default
        d = d.get(key)
    return default if d is None else d


def _first(*values):
    for v in values:
        if v is not None:
            return v
    return None


def _int(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def unwrap_tweet(result) -> dict | None:
    if not isinstance(result, dict):
        return None
    if result.get("__typename") == "TweetWithVisibilityResults":
        result = result.get("tweet")
    if not isinstance(result, dict) or "legacy" not in result:
        return None
    return result


def snowflake_time(tweet_id) -> datetime | None:
    value = _int(tweet_id)
    if value is None or value < 10**14:
        return None
    return datetime.fromtimestamp(((value >> 22) + TWITTER_EPOCH_MS) / 1000, tz=timezone.utc)


def parse_x_time(value) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.strptime(value, "%a %b %d %H:%M:%S %z %Y").astimezone(timezone.utc)
    except ValueError:
        return parse_iso_utc(value)


def tweet_id(tweet: dict) -> str | None:
    tid = _first(tweet.get("rest_id"), _get(tweet, "legacy", "id_str"))
    return str(tid) if tid is not None else None


def user_fields(tweet: dict) -> dict:
    user = _get(tweet, "core", "user_results", "result", default={})
    legacy = user.get("legacy") or {}
    core = user.get("core") or {}
    uid = _first(user.get("rest_id"), legacy.get("id_str"), _get(tweet, "legacy", "user_id_str"))
    created = parse_x_time(_first(core.get("created_at"), legacy.get("created_at")))
    return {
        "id": str(uid) if uid is not None else None,
        "handle": _first(core.get("screen_name"), legacy.get("screen_name")),
        "created_at": created,
        "followers": _int(_first(legacy.get("followers_count"), _get(user, "relationship_counts", "followers"))),
        "following": _int(_first(legacy.get("friends_count"), _get(user, "relationship_counts", "following"))),
        "statuses": _int(_first(legacy.get("statuses_count"), _get(user, "tweet_counts", "tweets"))),
        "is_blue_verified": user.get("is_blue_verified") if isinstance(user.get("is_blue_verified"), bool) else None,
        "verified_type": _first(_get(user, "verification", "verified_type"), legacy.get("verified_type"),
                                user.get("verified_type")),
        "affiliate_label": _get(user, "affiliates_highlighted_label", "label", "description"),
        "professional_type": _get(user, "professional", "professional_type"),
    }


def tweet_fields(tweet: dict) -> dict:
    legacy = tweet.get("legacy") or {}
    tid = tweet_id(tweet)
    media = _get(legacy, "extended_entities", "media") or _get(legacy, "entities", "media") or []
    text = _first(_get(tweet, "note_tweet", "note_tweet_results", "result", "text"), legacy.get("full_text"))
    return {
        "id": tid,
        "conversation_id": legacy.get("conversation_id_str"),
        "in_reply_to": legacy.get("in_reply_to_status_id_str"),
        "created_at": parse_x_time(legacy.get("created_at")) or snowflake_time(tid),
        "lang": legacy.get("lang"),
        "is_quote": bool(legacy.get("is_quote_status")),
        "has_media": bool(media),
        "views": _int(_get(tweet, "views", "count")),
        "likes": _int(legacy.get("favorite_count")),
        "replies": _int(legacy.get("reply_count")),
        "reposts": _int(legacy.get("retweet_count")),
        "quotes": _int(legacy.get("quote_count")),
        "bookmarks": _int(legacy.get("bookmark_count")),
        "text": text,
    }


def _section(*client_event_infos) -> str | None:
    for info in client_event_infos:
        value = _get(info, "details", "conversationDetails", "conversationSection")
        if value:
            return value
    return None


def _module_item(item_wrap: dict, position: int, entry_sort_index, entry_info,
                 module_id: str | None) -> tuple[Item | None, int]:
    """Returns (item, unavailable_count) for one module item."""
    item = item_wrap.get("item") or {}
    content = item.get("itemContent") or {}
    if content.get("itemType") != "TimelineTweet":
        return None, 0
    tweet = unwrap_tweet(_get(content, "tweet_results", "result"))
    if tweet is None:
        return None, 1
    if "promotedMetadata" in content:
        row_type = "promoted"
    else:
        row_type = "reply" if position == 0 else "nested_reply"
    return Item(row_type, position, _section(item.get("clientEventInfo"), entry_info),
                entry_sort_index, tweet, module_id), 0


def _instructions(body: dict) -> list:
    data = body.get("data") or {}
    convo = data.get("threaded_conversation_with_injections_v2") or data.get(
        "threaded_conversation_with_injections") or {}
    return convo.get("instructions") or []


def parse_page(body: dict, focal_tweet_id: str | None) -> Page:
    """Split one response into the focal tweet and the reply-list items."""
    items: list[Item] = []
    unavailable = 0
    tweet_entries: list[dict] = []

    for inst in _instructions(body):
        kind = inst.get("type")
        if kind == "TimelineAddEntries":
            entries = inst.get("entries") or []
        elif kind == "TimelineReplaceEntry":
            entries = [inst.get("entry")] if inst.get("entry") else []
        elif kind == "TimelineAddToModule":
            # Expanding a reply module ("Show replies") appends items to it.
            # Positions are provisional; the parser continues them from the
            # module's existing items, which may be on an earlier page.
            for pos, wrap in enumerate(inst.get("moduleItems") or [], start=1):
                found, missing = _module_item(wrap, pos, None, None, inst.get("moduleEntryId"))
                unavailable += missing
                if found:
                    found.appended = True
                    items.append(found)
            continue
        else:
            continue

        for entry in entries:
            eid = entry.get("entryId") or ""
            sort_index = entry.get("sortIndex")
            sort_index = str(sort_index) if sort_index is not None else None
            content = entry.get("content") or {}
            entry_info = content.get("clientEventInfo")

            if content.get("entryType") == "TimelineTimelineModule" or "items" in content:
                for pos, wrap in enumerate(content.get("items") or []):
                    found, missing = _module_item(wrap, pos, sort_index, entry_info, eid)
                    unavailable += missing
                    if found:
                        items.append(found)
                continue

            item_content = content.get("itemContent") or {}
            if item_content.get("itemType") != "TimelineTweet":
                continue  # cursors, prompts, labels
            tweet = unwrap_tweet(_get(item_content, "tweet_results", "result"))
            if tweet is None:
                unavailable += 1
                continue
            if "promotedMetadata" in item_content or eid.startswith("promoted"):
                items.append(Item("promoted", 0, _section(entry_info), sort_index, tweet))
            elif eid.startswith("tweet-"):
                tweet_entries.append(tweet)  # focal tweet or one of its ancestors

    focal = None
    if focal_tweet_id:
        focal = next((t for t in tweet_entries if tweet_id(t) == focal_tweet_id), None)
    elif tweet_entries:
        focal = tweet_entries[-1]  # ancestors are listed first, the focal tweet last
    return Page(focal=focal, items=items, unavailable=unavailable)
