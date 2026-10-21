"""Turn a Bluesky capture bundle into reply table rows (schema v1).

The mapping, and every field with no X equivalent, is documented in
docs/bluesky_mapping.md. In short:

- Order is the order getPostThreadV2 returned, which is the order the
  Bluesky app shows. Top-level replies (depth 1) get display_rank; their
  descendants follow them as nested_reply rows in the same module.
- Replies in the hidden "other replies" fold (getPostThreadOtherV2) come
  after the main list, the way the app shows them behind a button, with
  conversation_section = OtherReplies (or HiddenByAuthor when the thread
  author hid them with a threadgate).
- Bluesky has no paid tier, no ads and no view counts, so
  author_is_blue_verified is always false, no row is promoted and view
  counts are null. Bluesky's own (free) verification badges go into
  *_verified_type as BlueskyVerified or BlueskyTrustedVerifier.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

from twitterdata.bluesky.bundle import PROFILES, THREAD, THREAD_OTHER, Bundle
from twitterdata.capture.parser import iso_utc
from twitterdata.privacy import pseudonym, scrub_rows
from twitterdata.schema import COLUMN_NAMES, SCHEMA_VERSION

PLATFORM = "bluesky"
SORTS = {"relevance": "top", "recent": "newest"}  # reply table value -> Bluesky sort
SECTION_MAIN, SECTION_OTHER, SECTION_HIDDEN = "Main", "OtherReplies", "HiddenByAuthor"
OFFICIAL_MODERATION = "did:plc:ar7c4by46qjdydhdevvrndac"  # Bluesky Moderation Service labeler
GIF_HOSTS = ("media.tenor.com", "static.klipy.com")
POST_ITEM = "app.bsky.unspecced.defs#threadItemPost"

EXTRA_COLUMNS = (
    "capture_id", "tweet_id", "depth", "conversation_section", "indexed_at_utc", "op_thread",
    "more_replies", "hidden_by_threadgate", "post_labels", "author_labels", "author_is_labeler",
    "embed_type",
)

_TS = re.compile(r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(?:\.(\d+))?(Z|[+-]\d{2}:?\d{2})?$")


@dataclass
class MapResult:
    rows: list[dict]
    extras: list[dict]
    stats: dict


def parse_ts(value: str | None) -> datetime | None:
    """Lenient ISO 8601 parser; Bluesky createdAt is client-set and varies in precision."""
    if not value:
        return None
    m = _TS.match(value.strip())
    if not m:
        return None
    base, frac, tz = m.groups()
    micro = int((frac or "0")[:6].ljust(6, "0"))
    dt = datetime.fromisoformat(base).replace(microsecond=micro)
    if tz in (None, "Z"):
        return dt.replace(tzinfo=timezone.utc)
    sign = 1 if tz[0] == "+" else -1
    digits = tz[1:].replace(":", "")
    offset = sign * (int(digits[:2]) * 60 + int(digits[2:]))
    return (dt - timedelta(minutes=offset)).replace(tzinfo=timezone.utc)


def rkey(uri: str) -> str:
    return uri.rstrip("/").rsplit("/", 1)[-1]


def _labels(labels: list | None, self_did: str | None) -> str | None:
    """Label values joined with ';'. Prefix: bsky (official moderation), self (author-applied), other."""
    out = []
    for label in labels or []:
        if label.get("neg"):
            continue
        src = label.get("src")
        origin = "bsky" if src == OFFICIAL_MODERATION else "self" if src and src == self_did else "other"
        out.append(f"{origin}:{label.get('val')}")
    return ";".join(sorted(set(out))) or None


def _verified_type(author: dict, profile: dict | None) -> str | None:
    v = (profile or {}).get("verification") or author.get("verification") or {}
    if v.get("trustedVerifierStatus") == "valid":
        return "BlueskyTrustedVerifier"
    if v.get("verifiedStatus") == "valid":
        return "BlueskyVerified"
    return None


def _embed_flags(embed: dict | None) -> tuple[bool, bool, str | None]:
    """(is_quote, has_media, embed $type) for a post view's embed."""
    if not embed:
        return False, False, None
    kind = embed.get("$type", "")
    if kind.startswith("app.bsky.embed.recordWithMedia"):
        return True, True, kind
    if kind.startswith("app.bsky.embed.record"):
        return True, False, kind
    if kind.startswith(("app.bsky.embed.images", "app.bsky.embed.video")):
        return False, True, kind
    if kind.startswith("app.bsky.embed.external"):
        host = urlparse((embed.get("external") or {}).get("uri", "")).hostname or ""
        return False, host in GIF_HOSTS, kind
    return False, False, kind or None


def _handle_hash(salt: bytes, handle: str | None) -> str | None:
    if not handle or handle == "handle.invalid":
        return None
    return pseudonym(salt, PLATFORM, "handle", handle.lower())


def _profiles(bundle: Bundle) -> dict[str, dict]:
    out = {}
    for resp in bundle.responses_for(PROFILES):
        for p in resp["body"].get("profiles", []):
            out[p["did"]] = p
    return out


def build_rows(bundle: Bundle, salt: bytes, capture_file: str, include_text: bool = False,
               viewer_type: str = "logged_out", capture_id: str | None = None) -> MapResult:
    capture_id = capture_id or bundle.capture_id or capture_file.rsplit(".", 1)[0]
    threads = bundle.responses_for(THREAD)
    if not threads:
        raise ValueError("bundle has no getPostThreadV2 response")
    main = threads[0]
    others = bundle.responses_for(THREAD_OTHER)
    profiles = _profiles(bundle)
    stats = {"responses": len(bundle.responses), "unavailable": 0, "duplicates": 0,
             "main_items": 0, "other_items": 0, "parents_skipped": 0}

    focal_item = next((i for i in main["body"].get("thread", []) if i.get("depth") == 0), None)
    if focal_item is None or focal_item["value"].get("$type") != POST_ITEM:
        kind = focal_item["value"].get("$type", "missing").rsplit("#", 1)[-1] if focal_item else "missing"
        raise ValueError(f"focal post is not viewable logged out ({kind})")
    focal = focal_item["value"]["post"]
    focal_did = focal["author"]["did"]
    focal_profile = profiles.get(focal_did)
    reply_ref = (focal.get("record") or {}).get("reply") or {}
    thread_cols = {
        "thread_id": (reply_ref.get("root") or {}).get("uri") or focal["uri"],
        "focal_tweet_id": focal["uri"],
        "focal_author_id_hash": pseudonym(salt, PLATFORM, "user", focal_did),
        "focal_author_followers": (focal_profile or {}).get("followersCount"),
        "focal_author_is_blue_verified": False,
        "focal_author_verified_type": _verified_type(focal["author"], focal_profile),
        "focal_author_affiliate_label": None,
        "focal_view_count": None,
        "focal_like_count": focal.get("likeCount"),
        "focal_reply_count": focal.get("replyCount"),
    }
    started = parse_ts(main["received_at"])
    capture_cols = {
        "schema_version": SCHEMA_VERSION,
        "platform": PLATFORM,
        "capture_id": capture_id,
        "capture_file": capture_file,
        "capture_session": 1,
        "capture_time_utc": iso_utc(started),
        "viewer_type": viewer_type,
        "viewer_label": bundle.viewer_label,
        "sort_order": bundle.sort_order,
        "sort_order_source": "request",
        "age_bucket": bundle.age_bucket,
    }

    pages = [(0, SECTION_MAIN, main)] + [(1 + n, SECTION_OTHER, r) for n, r in enumerate(others)]
    rows, extras, seen = [], [], set()
    display_index = display_rank = module_position = 0
    for page_index, section, resp in pages:
        for item in resp["body"].get("thread", []):
            depth = item.get("depth", 0)
            if depth <= 0:
                stats["parents_skipped"] += depth < 0
                continue
            value = item.get("value", {})
            if value.get("$type") != POST_ITEM:
                stats["unavailable"] += 1
                continue
            post = value["post"]
            if post["uri"] in seen:
                stats["duplicates"] += 1
                continue
            seen.add(post["uri"])
            stats["main_items" if page_index == 0 else "other_items"] += 1
            display_index += 1
            if depth == 1:
                display_rank += 1
                module_position = 0
            else:
                module_position += 1
            row_section = SECTION_HIDDEN if value.get("hiddenByThreadgate") else section
            author, record = post["author"], post.get("record") or {}
            profile = profiles.get(author["did"])
            is_quote, has_media, embed_type = _embed_flags(post.get("embed"))
            langs = record.get("langs") or []
            row = {
                **capture_cols,
                **thread_cols,
                "page_index": page_index,
                "row_type": "reply" if depth == 1 else "nested_reply",
                "is_promoted": False,
                "display_rank": display_rank if depth == 1 else None,
                "display_index": display_index,
                "rank_is_absolute": True,
                "module_position": module_position,
                "conversation_section": row_section,
                "sort_index": None,
                "tweet_id": post["uri"],
                "in_reply_to_tweet_id": ((record.get("reply") or {}).get("parent") or {}).get("uri"),
                "created_at_utc": iso_utc(parse_ts(record.get("createdAt"))),
                "lang": langs[0] if langs else None,
                "is_quote": is_quote,
                "has_media": has_media,
                "view_count": None,
                "like_count": post.get("likeCount"),
                "reply_count": post.get("replyCount"),
                "repost_count": post.get("repostCount"),
                "quote_count": post.get("quoteCount"),
                "bookmark_count": post.get("bookmarkCount"),
                "text": record.get("text") if include_text else None,
                "author_id_hash": pseudonym(salt, PLATFORM, "user", author["did"]),
                "author_handle_hash": _handle_hash(salt, author.get("handle")),
                "author_is_focal_author": author["did"] == focal_did,
                "author_is_blue_verified": False,
                "author_verified_type": _verified_type(author, profile),
                "author_affiliate_label": None,
                "author_professional_type": None,
                "author_followers": (profile or {}).get("followersCount"),
                "author_following": (profile or {}).get("followsCount"),
                "author_statuses": (profile or {}).get("postsCount"),
                "author_created_at_utc": iso_utc(parse_ts((profile or {}).get("createdAt") or author.get("createdAt"))),
            }
            rows.append({name: row.get(name) for name in COLUMN_NAMES})
            extras.append({
                "capture_id": capture_id,
                "tweet_id": post["uri"],
                "depth": depth,
                "conversation_section": row_section,
                "indexed_at_utc": iso_utc(parse_ts(post.get("indexedAt"))),
                "op_thread": bool(value.get("opThread")),
                "more_replies": value.get("moreReplies") or 0,
                "hidden_by_threadgate": bool(value.get("hiddenByThreadgate")),
                "post_labels": _labels(post.get("labels"), author["did"]),
                "author_labels": _labels(author.get("labels"), author["did"]),
                "author_is_labeler": bool(((profile or {}).get("associated") or {}).get("labeler")),
                "embed_type": embed_type,
            })

    stats["rows"] = len(rows)
    stats["top_level"] = display_rank
    stats["focal_reply_count"] = focal.get("replyCount")
    stats["has_other_replies"] = bool(main["body"].get("hasOtherReplies"))
    stats["other_fetched"] = bool(others)
    stats["redacted_cells"] = scrub_rows(rows)
    return MapResult(rows, extras, stats)
