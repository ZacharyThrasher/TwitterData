"""Reply table schema, version 1.

This module is the single source of truth for the reply table. The Markdown
doc (docs/reply_table_schema.md) and the JSON file (schema/reply_table.v1.json)
are generated from it with `python -m twitterdata schema`, and a test keeps
them in sync.

One row is one item shown in a reply list: a top-level reply, a nested reply
inside a reply module, or a promoted post injected into the list. Rows are
pseudonymous, not anonymous: tweet ids are public and can be looked up.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

SCHEMA_NAME = "reply_table"
SCHEMA_VERSION = "1"


@dataclass(frozen=True)
class Column:
    name: str
    type: str  # string | integer | boolean | timestamp
    nullable: bool
    group: str
    description: str
    enum: tuple[str, ...] | None = None


SORT_ORDERS = ("relevance", "recent", "likes", "unknown")
VIEWER_TYPES = ("logged_out", "free", "premium", "premium_plus", "unknown")
ROW_TYPES = ("reply", "nested_reply", "promoted")
PLATFORMS = ("x", "bluesky")

COLUMNS: tuple[Column, ...] = (
    # Capture metadata: identical on every row from one capture.
    Column("schema_version", "string", False, "capture", "Reply table schema version. Always \"1\" for this version."),
    Column("platform", "string", False, "capture", "Platform the capture came from.", PLATFORMS),
    Column("capture_id", "string", False, "capture",
           "Id of the capture. Set with --capture-id (for example the sampling tracker id "
           "`{root_tweet_id}_h06_likes_A`); defaults to the input file name without extension."),
    Column("capture_file", "string", False, "capture", "Input file base name (no directory)."),
    Column("capture_session", "integer", False, "capture",
           "1-based load of one thread view inside the file. A new session starts each time the "
           "thread is loaded from the top (a request without a pagination cursor), per focal tweet "
           "and sort order."),
    Column("capture_time_utc", "timestamp", False, "capture",
           "When the first response of this session was received (HAR startedDateTime), ISO 8601 UTC. "
           "For raw JSON input, or a HAR without a readable time: --capture-time, else the file "
           "modification time."),
    Column("page_index", "integer", False, "capture",
           "0-based index of the response (page) within the session that this row arrived in."),
    Column("viewer_type", "string", False, "capture",
           "Account type of the person who captured the page. Set with --viewer-type; the parser "
           "never inspects cookies, so it cannot detect this itself.", VIEWER_TYPES),
    Column("viewer_label", "string", True, "capture",
           "Free-text label for the capturing persona (for example A or B). Set with --viewer-label."),
    Column("sort_order", "string", False, "capture",
           "Reply sort the page was shown in. Read from the request's rankingMode "
           "(Relevance -> relevance, Recency -> recent, Likes -> likes) unless --sort-order is given.",
           SORT_ORDERS),
    Column("sort_order_source", "string", False, "capture",
           "Where sort_order came from: request (rankingMode variable), flag (--sort-order), "
           "default (request sent no rankingMode, which X treats as relevance), or unknown (raw "
           "response input with no request and no flag).", ("request", "flag", "default", "unknown")),
    Column("age_bucket", "string", True, "capture",
           "Thread age bucket at capture time (for example h01, h06, h24). Set with --age-bucket."),
    # Thread (focal tweet) context: identical on every row of a session.
    Column("thread_id", "string", True, "thread", "Conversation root tweet id: conversation_id_str of the focal tweet, or of the replies "
           "when the capture began mid-thread and the focal tweet was not captured."),
    Column("focal_tweet_id", "string", False, "thread", "Tweet whose reply list was captured (focalTweetId)."),
    Column("focal_author_id_hash", "string", True, "thread", "HMAC hash of the focal tweet author's user id."),
    Column("focal_author_followers", "integer", True, "thread", "Focal author follower count at capture."),
    Column("focal_author_is_blue_verified", "boolean", True, "thread", "Focal author has a paid (blue) checkmark."),
    Column("focal_author_verified_type", "string", True, "thread",
           "Focal author verified_type (Business, Government) when present."),
    Column("focal_author_affiliate_label", "string", True, "thread",
           "Focal author affiliate badge text (the organisation name), when present."),
    Column("focal_view_count", "integer", True, "thread", "Focal tweet view count at capture."),
    Column("focal_like_count", "integer", True, "thread", "Focal tweet like count at capture."),
    Column("focal_reply_count", "integer", True, "thread", "Focal tweet reply count at capture."),
    # Display position.
    Column("row_type", "string", False, "position",
           "reply: first item of a reply module (top-level reply). nested_reply: a later item in the "
           "same module. promoted: an ad injected into the reply list.", ROW_TYPES),
    Column("is_promoted", "boolean", False, "position", "True when row_type is promoted."),
    Column("display_rank", "integer", True, "position",
           "1-based order of top-level organic replies in the session, counting each reply once. "
           "Null for nested replies and promoted rows."),
    Column("display_index", "integer", False, "position",
           "1-based order of every row in the session (replies, nested replies and ads)."),
    Column("rank_is_absolute", "boolean", False, "position",
           "True when the session's first page (no cursor) was captured, so display_rank counts from "
           "the top of the thread. False when the capture began mid-thread."),
    Column("module_position", "integer", False, "position",
           "0-based position inside the reply module. 0 for top-level replies and standalone ads."),
    Column("conversation_section", "string", True, "position",
           "X's section label for the item, for example HighQuality, LowQuality or AbusiveQuality."),
    Column("sort_index", "string", True, "position", "X timeline sortIndex of the entry (64-bit, kept as text)."),
    # The reply itself.
    Column("tweet_id", "string", False, "reply", "Reply tweet id."),
    Column("in_reply_to_tweet_id", "string", True, "reply", "Parent tweet id."),
    Column("created_at_utc", "timestamp", True, "reply", "Reply creation time, ISO 8601 UTC."),
    Column("lang", "string", True, "reply", "X language code of the reply."),
    Column("is_quote", "boolean", False, "reply", "Reply quotes another post."),
    Column("has_media", "boolean", False, "reply", "Reply carries photos, video or GIFs."),
    Column("view_count", "integer", True, "reply", "Views at capture. Null when X did not report views."),
    Column("like_count", "integer", True, "reply", "Likes at capture."),
    Column("reply_count", "integer", True, "reply", "Replies at capture."),
    Column("repost_count", "integer", True, "reply", "Reposts (retweets) at capture."),
    Column("quote_count", "integer", True, "reply", "Quotes at capture."),
    Column("bookmark_count", "integer", True, "reply", "Bookmarks at capture."),
    Column("text", "string", True, "reply",
           "Full reply text. Only filled when the parser runs with --include-text; null otherwise."),
    # Reply author.
    Column("author_id_hash", "string", False, "author",
           "HMAC-SHA256 of the author's user id with the local salt (24 hex chars). Stable across "
           "captures made with the same salt."),
    Column("author_handle_hash", "string", True, "author",
           "HMAC-SHA256 of the lower-cased handle with the local salt (24 hex chars)."),
    Column("author_is_focal_author", "boolean", False, "author", "Reply was written by the focal tweet's author."),
    Column("author_is_blue_verified", "boolean", True, "author", "Author has a paid (blue) checkmark (X Premium)."),
    Column("author_verified_type", "string", True, "author", "Author verified_type (Business, Government) when present."),
    Column("author_affiliate_label", "string", True, "author", "Author affiliate badge text, when present."),
    Column("author_professional_type", "string", True, "author", "Professional account type (Creator, Business) when present."),
    Column("author_followers", "integer", True, "author", "Author follower count at capture."),
    Column("author_following", "integer", True, "author", "Accounts the author follows, at capture."),
    Column("author_statuses", "integer", True, "author", "Author's total post count at capture."),
    Column("author_created_at_utc", "timestamp", True, "author", "Author account creation time, ISO 8601 UTC."),
)

COLUMN_NAMES: tuple[str, ...] = tuple(c.name for c in COLUMNS)

GROUP_TITLES = {
    "capture": "Capture metadata (same on every row of a capture)",
    "thread": "Thread context (same on every row of a session)",
    "position": "Display position",
    "reply": "The reply",
    "author": "Reply author (pseudonymous)",
}


def json_schema() -> dict:
    """Machine-readable schema, used by downstream pipelines."""
    columns = []
    for c in COLUMNS:
        entry = {"name": c.name, "type": c.type, "nullable": c.nullable, "group": c.group,
                 "description": c.description}
        if c.enum:
            entry["enum"] = list(c.enum)
        columns.append(entry)
    return {"name": SCHEMA_NAME, "version": SCHEMA_VERSION, "columns": columns}


def json_schema_text() -> str:
    return json.dumps(json_schema(), indent=2) + "\n"


def markdown_columns() -> str:
    """Column reference tables for the schema doc."""
    out = []
    for group, title in GROUP_TITLES.items():
        out.append(f"### {title}\n")
        out.append("| Column | Type | Null | Description |")
        out.append("| --- | --- | --- | --- |")
        for c in COLUMNS:
            if c.group != group:
                continue
            desc = c.description
            if c.enum:
                desc += " Values: " + ", ".join(f"`{v}`" for v in c.enum) + "."
            out.append(f"| `{c.name}` | {c.type} | {'yes' if c.nullable else 'no'} | {desc} |")
        out.append("")
    return "\n".join(out)
