# Reply table schema, version 1

The reply table is the shared format for every reply-list capture in this
project. The X capture parser writes it today; the analysis pipeline reads it,
and the Bluesky collector should write it too (with `platform = bluesky`).

- Machine-readable copy: [`schema/reply_table.v1.json`](../schema/reply_table.v1.json)
- Source of truth: [`src/twitterdata/schema.py`](../src/twitterdata/schema.py)
- Regenerate both files after editing the source: `python -m twitterdata schema --write`

## At a glance

- **One row = one item shown in a reply list**: a top-level reply, a nested
  reply inside a reply module, or a promoted post (ad) that X injected.
- **Display order is the point.** `display_rank` is where a top-level reply
  appeared among organic replies; `display_index` counts every row, ads
  included.
- **Who captured it matters.** `viewer_type`, `viewer_label` and `sort_order`
  say what kind of account was looking and which sort was on.
- **Authors are pseudonymous.** Raw handles and user ids are never written.
  They are replaced by salted hashes (see Privacy below).
- **Text is opt-in.** `text` is empty unless the parser runs with `--include-text`.

## Key ideas

### Capture, session, page

| Term | Meaning |
| --- | --- |
| Capture | One input file (a `.har` export, or one saved response `.json`). Identified by `capture_id`. |
| Session | One load of a thread's reply list, from the top, in one sort order. Scrolling and "Show more replies" stay in the same session. Reloading the thread starts a new one. |
| Page | One TweetDetail response inside a session (`page_index`, from 0). |

A capture that starts mid-scroll (the first page was missed) still parses, but
its `rank_is_absolute` is `false`: ranks count from where the capture began,
not from the top.

### Ranking columns

| Column | Counts | Use it for |
| --- | --- | --- |
| `display_rank` | Top-level organic replies only, each once | "Where did X put this reply?" |
| `display_index` | Every row: replies, nested replies, ads | Ad density, what a reader scrolls past |
| `module_position` | Position inside one reply module | Nested reply depth in the module |
| `conversation_section` | X's own bucket: `HighQuality`, `LowQuality`, `AbusiveQuality` | The "show probable spam" fold |

### Sort order

Read from the `rankingMode` variable of each request:

| X value | `sort_order` |
| --- | --- |
| `Relevance` | `relevance` |
| `Recency` | `recent` |
| `Likes` | `likes` |
| (not sent) | `relevance`, with `sort_order_source = default` |

`--sort-order` overrides it (`sort_order_source = flag`).

### Capture ids from the sampling tracker

The sampling tracker names captures
`{root_tweet_id}_h{01|06|24}_{relevance|recent|likes}_{viewer}`. Pass that as
`--capture-id`, with the matching `--age-bucket`, `--sort-order`,
`--viewer-type` and `--viewer-label`, so every row carries it.

## Privacy

- `author_id_hash`, `author_handle_hash` and `focal_author_id_hash` are
  HMAC-SHA256 of `platform:kind:value` keyed with a local salt, cut to 24 hex
  characters. Handles are lower-cased first.
- The salt comes from `TWITTERDATA_HASH_SALT`, else
  `~/.config/twitterdata/hash_salt` (created on first run). Keep it out of the
  repository. Same salt means hashes join across captures; a different salt
  means they do not.
- Rows are pseudonymous, not anonymous. Tweet ids are public, and a tweet id
  leads back to its author. Treat outputs as personal data.

## Types and encoding

| Type | CSV | JSON Lines |
| --- | --- | --- |
| string | text | string |
| integer | digits | number |
| boolean | `true` / `false` | `true` / `false` |
| timestamp | ISO 8601 UTC with milliseconds, e.g. `2026-10-21T13:33:13.000Z` | same string |
| null | empty cell | `null` |

All ids (tweet ids, `sort_index`) are strings, because they exceed the
integer range of many tools (Excel, JavaScript).

## Versioning

Adding a nullable column at the end is a minor change and keeps version `1`.
Renaming, removing, retyping or reordering a column needs version `2` and a
new `schema/reply_table.v2.json`.

## Columns

<!-- BEGIN GENERATED COLUMNS -->

### Capture metadata (same on every row of a capture)

| Column | Type | Null | Description |
| --- | --- | --- | --- |
| `schema_version` | string | no | Reply table schema version. Always "1" for this version. |
| `platform` | string | no | Platform the capture came from. Values: `x`, `bluesky`. |
| `capture_id` | string | no | Id of the capture. Set with --capture-id (for example the sampling tracker id `{root_tweet_id}_h06_likes_A`); defaults to the input file name without extension. |
| `capture_file` | string | no | Input file base name (no directory). |
| `capture_session` | integer | no | 1-based load of one thread view inside the file. A new session starts each time the thread is loaded from the top (a request without a pagination cursor), per focal tweet and sort order. |
| `capture_time_utc` | timestamp | no | When the first response of this session was received (HAR startedDateTime), ISO 8601 UTC. For raw JSON input, or a HAR without a readable time: --capture-time, else the file modification time. |
| `page_index` | integer | no | 0-based index of the response (page) within the session that this row arrived in. |
| `viewer_type` | string | no | Account type of the person who captured the page. Set with --viewer-type; the parser never inspects cookies, so it cannot detect this itself. Values: `logged_out`, `free`, `premium`, `premium_plus`, `unknown`. |
| `viewer_label` | string | yes | Free-text label for the capturing persona (for example A or B). Set with --viewer-label. |
| `sort_order` | string | no | Reply sort the page was shown in. Read from the request's rankingMode (Relevance -> relevance, Recency -> recent, Likes -> likes) unless --sort-order is given. Values: `relevance`, `recent`, `likes`, `unknown`. |
| `sort_order_source` | string | no | Where sort_order came from: request (rankingMode variable), flag (--sort-order), default (request sent no rankingMode, which X treats as relevance), or unknown (raw response input with no request and no flag). Values: `request`, `flag`, `default`, `unknown`. |
| `age_bucket` | string | yes | Thread age bucket at capture time (for example h01, h06, h24). Set with --age-bucket. |

### Thread context (same on every row of a session)

| Column | Type | Null | Description |
| --- | --- | --- | --- |
| `thread_id` | string | yes | Conversation root tweet id (conversation_id_str of the focal tweet). |
| `focal_tweet_id` | string | no | Tweet whose reply list was captured (focalTweetId). |
| `focal_author_id_hash` | string | yes | HMAC hash of the focal tweet author's user id. |
| `focal_author_followers` | integer | yes | Focal author follower count at capture. |
| `focal_author_is_blue_verified` | boolean | yes | Focal author has a paid (blue) checkmark. |
| `focal_author_verified_type` | string | yes | Focal author verified_type (Business, Government) when present. |
| `focal_author_affiliate_label` | string | yes | Focal author affiliate badge text (the organisation name), when present. |
| `focal_view_count` | integer | yes | Focal tweet view count at capture. |
| `focal_like_count` | integer | yes | Focal tweet like count at capture. |
| `focal_reply_count` | integer | yes | Focal tweet reply count at capture. |

### Display position

| Column | Type | Null | Description |
| --- | --- | --- | --- |
| `row_type` | string | no | reply: first item of a reply module (top-level reply). nested_reply: a later item in the same module. promoted: an ad injected into the reply list. Values: `reply`, `nested_reply`, `promoted`. |
| `is_promoted` | boolean | no | True when row_type is promoted. |
| `display_rank` | integer | yes | 1-based order of top-level organic replies in the session, counting each reply once. Null for nested replies and promoted rows. |
| `display_index` | integer | no | 1-based order of every row in the session (replies, nested replies and ads). |
| `rank_is_absolute` | boolean | no | True when the session's first page (no cursor) was captured, so display_rank counts from the top of the thread. False when the capture began mid-thread. |
| `module_position` | integer | no | 0-based position inside the reply module. 0 for top-level replies and standalone ads. |
| `conversation_section` | string | yes | X's section label for the item, for example HighQuality, LowQuality or AbusiveQuality. |
| `sort_index` | string | yes | X timeline sortIndex of the entry (64-bit, kept as text). |

### The reply

| Column | Type | Null | Description |
| --- | --- | --- | --- |
| `tweet_id` | string | no | Reply tweet id. |
| `in_reply_to_tweet_id` | string | yes | Parent tweet id. |
| `created_at_utc` | timestamp | yes | Reply creation time, ISO 8601 UTC. |
| `lang` | string | yes | X language code of the reply. |
| `is_quote` | boolean | no | Reply quotes another post. |
| `has_media` | boolean | no | Reply carries photos, video or GIFs. |
| `view_count` | integer | yes | Views at capture. Null when X did not report views. |
| `like_count` | integer | yes | Likes at capture. |
| `reply_count` | integer | yes | Replies at capture. |
| `repost_count` | integer | yes | Reposts (retweets) at capture. |
| `quote_count` | integer | yes | Quotes at capture. |
| `bookmark_count` | integer | yes | Bookmarks at capture. |
| `text` | string | yes | Full reply text. Only filled when the parser runs with --include-text; null otherwise. |

### Reply author (pseudonymous)

| Column | Type | Null | Description |
| --- | --- | --- | --- |
| `author_id_hash` | string | no | HMAC-SHA256 of the author's user id with the local salt (24 hex chars). Stable across captures made with the same salt. |
| `author_handle_hash` | string | yes | HMAC-SHA256 of the lower-cased handle with the local salt (24 hex chars). |
| `author_is_focal_author` | boolean | no | Reply was written by the focal tweet's author. |
| `author_is_blue_verified` | boolean | yes | Author has a paid (blue) checkmark (X Premium). |
| `author_verified_type` | string | yes | Author verified_type (Business, Government) when present. |
| `author_affiliate_label` | string | yes | Author affiliate badge text, when present. |
| `author_professional_type` | string | yes | Professional account type (Creator, Business) when present. |
| `author_followers` | integer | yes | Author follower count at capture. |
| `author_following` | integer | yes | Accounts the author follows, at capture. |
| `author_statuses` | integer | yes | Author's total post count at capture. |
| `author_created_at_utc` | timestamp | yes | Author account creation time, ISO 8601 UTC. |

<!-- END GENERATED COLUMNS -->
