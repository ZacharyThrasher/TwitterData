# Bluesky comparison collector: how Bluesky maps onto the reply table

Bluesky is the control platform: similar audiences and news events, but no
paid reply boosting, no creator revenue sharing and no ads. The collector
writes the same reply table as the X parser ([schema v1](reply_table_schema.md))
with `platform = bluesky`, so one analysis can read both.

## At a glance

- **Free, no login.** Reads the public AppView (`public.api.bsky.app`). No
  account, no API key, no cost.
- **Polite.** 1 request per second by default (floor 0.2 s), retries 429 and 5xx
  with backoff that honours `Retry-After` and `RateLimit-Reset`. A typical
  thread costs 3 to 8 requests.
- **Same order a reader sees.** Rows follow the order Bluesky's own app shows,
  from the same endpoint the app uses (`getPostThreadV2`).
- **Same privacy rules.** Authors become salted HMAC hashes with the same salt
  and scheme as the X parser. Text only with `--include-text`.
- **Honest gaps.** Anything X has and Bluesky does not (Premium, ads, views) is
  `false` or empty, never guessed. Anything Bluesky has and X does not goes in
  a sidecar file.

## Run it

```
python -m twitterdata bluesky collect "https://bsky.app/profile/someone.bsky.social/post/3abc..." \
    --sort relevance --sort recent --age-bucket h06 -o output/bsky.csv
```

| Flag | Meaning |
| --- | --- |
| `--sort` | `relevance` (Bluesky "top", the app default) or `recent` (Bluesky "newest"). Repeat for both; one capture each. Default `relevance`. |
| `--from-file` | Text file of post URLs or `at://` URIs, one per line. |
| `--age-bucket`, `--viewer-label`, `--capture-id` | Same meaning as for the X parser. |
| `--include-text` | Fill the `text` column. |
| `--no-other` | Skip the hidden "other replies" fold. |
| `--no-profiles` | Skip profile lookups (author follower, following and post counts stay empty). |
| `--below`, `--branching` | Reply depth (max 20) and nested replies per post (max 100) to fetch. Defaults are the maximum. |
| `--min-interval` | Seconds between requests. |
| `--raw-dir` | Where raw capture bundles go. Default `data/raw/bluesky/` (git-ignored). |
| `--extras` | Sidecar path. Default `<output>.bluesky_extras.csv`; `none` skips it. |

Each capture also saves its raw API responses as a **bundle** (the Bluesky
version of a `.har`). Rebuild the table offline at any time:

```
python -m twitterdata bluesky parse data/raw/bluesky/*.json -o output/bsky.csv
```

Default capture id: `bsky_{rkey}[_{age}]_{sort}[_{viewer}]`, for example
`bsky_3abc_h06_relevance_A`, mirroring the X tracker ids.

## Reply order

| Reply table `sort_order` | Bluesky sort | What Bluesky does |
| --- | --- | --- |
| `relevance` | `top` | Bluesky's default ranking. Bluesky does not publish the formula, but it has no paid signal to feed it. |
| `recent` | `newest` | Newest first by **when Bluesky indexed the post** (`indexedAt`), not the client-set `createdAt`. Verified on live data. |
| `likes` | none | Bluesky has no "most liked" sort. The collector refuses it. |
| (not offered) | `oldest` | No X equivalent in schema v1, so the collector does not offer it. |

`sort_order_source` is always `request`: the collector chose the sort.

### The hidden fold ("other replies")

Like X's "Show probable spam" fold, Bluesky hides some replies behind a button
at the end of the thread. The main list comes from `getPostThreadV2`
(`page_index = 0`); the fold comes from `getPostThreadOtherV2`
(`page_index = 1`) and is appended **after** the main list, as the app shows it.

| `conversation_section` | Meaning |
| --- | --- |
| `Main` | Shown in the main reply list. |
| `OtherReplies` | In the hidden fold (Bluesky judged it lower priority; the reasons are not exposed). |
| `HiddenByAuthor` | In the hidden fold because the thread author hid it with a threadgate. |

X writes its own labels here (`HighQuality`, `LowQuality`, `AbusiveQuality`).
Compare "in the main list" against "folded" across platforms, not the labels.

### Modules and ranks

- A top-level reply (`depth 1`) is `row_type = reply`, gets the next
  `display_rank`, and starts a module (`module_position = 0`).
- Its descendants that Bluesky shows under it are `nested_reply` rows with
  `module_position` 1, 2, 3 ... in display order, and no `display_rank`.
- `display_index` counts every row. `rank_is_absolute` is always `true`
  (Bluesky returns the whole thread in one response; no mid-scroll captures).
- `capture_session` is always 1 (one capture = one thread in one sort).

## Who is looking: logged out

Every capture is `viewer_type = logged_out`. That has one visible effect:
**authors who turned on "discourage apps from showing my account to logged-out
users" are left out**, by Bluesky itself. On one test thread that was 25 of 114
top-level replies. The collector respects that choice and does not use older
endpoints that would still return those posts. So `focal_reply_count` (which
Bluesky counts across all depths, opted-out authors included) is usually
higher than the rows captured; the run log prints both numbers.

The gap can be large on older threads. Bluesky's `replyCount` also keeps
replies that were later deleted or taken down by moderation. On one year-old
thread it said 2018 while the API returned 292 rows, and even the older
endpoint (which ignores the opt-out) listed only 183 top-level replies. Treat
`focal_reply_count` as an upper bound, not as the size of the visible thread.

## Column mapping

| Column | Bluesky source | Note |
| --- | --- | --- |
| `tweet_id`, `in_reply_to_tweet_id`, `focal_tweet_id`, `thread_id` | `at://` post URIs | DID-based, so they survive handle changes. Public, like tweet ids. |
| `created_at_utc` | `record.createdAt` | Set by the posting app and can be backdated. Server time is `indexed_at_utc` in the sidecar. |
| `lang` | first of `record.langs` | Author-declared, not detected. |
| `is_quote` | embed `record` or `recordWithMedia` | |
| `has_media` | embed `images`, `video`, `recordWithMedia`, or a GIF-picker link (Tenor, Klipy) | Ordinary link cards do not count. |
| `like_count`, `reply_count`, `repost_count`, `quote_count`, `bookmark_count` | post view counts | All present on Bluesky. |
| `view_count`, `focal_view_count` | none | **Always empty.** Bluesky does not show views. |
| `author_id_hash`, `focal_author_id_hash` | DID | `HMAC(salt, "bluesky:user:" + did)`. |
| `author_handle_hash` | handle, lower-cased | `HMAC(salt, "bluesky:handle:" + handle)`. Empty for `handle.invalid`. |
| `author_is_blue_verified`, `focal_author_is_blue_verified` | none | **Always `false`.** Bluesky has no paid tier. |
| `author_verified_type`, `focal_author_verified_type` | profile `verification` | `BlueskyVerified` or `BlueskyTrustedVerifier`. These badges are free and granted, not bought. Do not pool them with X's paid checkmark. |
| `author_affiliate_label`, `author_professional_type`, `focal_author_affiliate_label` | none | Always empty. |
| `author_followers`, `author_following`, `author_statuses`, `focal_author_followers` | `getProfiles` | Fetched seconds after the thread. Empty with `--no-profiles`. |
| `author_created_at_utc` | profile `createdAt` | |
| `is_promoted` | none | **Always `false`.** Bluesky has no ads; no `promoted` rows. |
| `sort_index` | none | Always empty. |

## Bluesky-only fields (the sidecar)

`<output>.bluesky_extras.csv`, one line per reply row, joined on
`capture_id` + `tweet_id`:

| Column | Meaning |
| --- | --- |
| `depth` | Reply depth (1 = direct reply to the focal post). |
| `conversation_section` | Same as in the table, repeated for convenience. |
| `indexed_at_utc` | When Bluesky indexed the post. Drives the `recent` order. |
| `op_thread` | Part of the original poster's own self-reply chain. |
| `more_replies` | Replies under this post that were not loaded (depth or branching limit). |
| `hidden_by_threadgate` | Thread author hid this reply. |
| `post_labels`, `author_labels` | Moderation labels, `;`-joined, prefixed by who applied them: `bsky:` (Bluesky's moderation service), `self:` (the author), `other:` (a third-party labeler). Negated labels are dropped. |
| `author_is_labeler` | The author runs a labeling service. |
| `embed_type` | Raw Bluesky embed type. |

Labels are Bluesky's nearest thing to X's quality buckets and moderation
interstitials. They are not in schema v1 because X has no public equivalent.

## What this means for the comparison

- The Premium-boost tests (T1 to T3) can only run on X: Bluesky has no paid
  tier, which is the point of the control. Bluesky tells us what ranking looks
  like **without** a pay-to-be-seen signal.
- Compare incivility in the **top N displayed replies** under `relevance` on
  both platforms, for the same news events.
- Exposure on Bluesky must use likes or rank, not views.
- Bluesky threads come back whole in one response; X threads paginate. Use
  `display_rank` cut-offs, not "everything captured".

## Privacy and ethics

- Same salt file as the X parser (`~/.config/twitterdata/hash_salt` or
  `TWITTERDATA_HASH_SALT`). The `bluesky:` prefix keeps Bluesky hashes from
  ever matching X hashes.
- Raw bundles contain real handles and text. They live in `data/raw/`, which
  is git-ignored. Never publish them; report aggregates only (the 2024 Bluesky
  dataset backlash is the cautionary tale).
- Test fixtures are real responses with every identity swapped for a fake and
  every timestamp shifted by a fixed amount (`tests/bluesky_fixtures.py`).
