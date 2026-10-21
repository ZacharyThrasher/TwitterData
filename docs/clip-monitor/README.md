# Clip-economy monitor

Takes dated snapshots of public campaign listings on clip-bounty marketplaces and turns them into one tidy table: who is paying, how much per 1,000 views, on which platforms, and on what topic. It also tags X accounts as paid clippers with a documented rule.

## In one minute

- **What it records:** campaign, buyer, payout model, rate per 1,000 views (per platform where shown), platforms, whether X views pay, budget and spend, dates, minimum views, required hashtags, and a topic tag.
- **Where from:** Vyro and Clipping.net, the two marketplaces with public campaign lists (checked 2026-10-21). The rest are behind a login or have no public list; see the table below.
- **How:** `fetch --all` runs on a daily schedule and downloads the listing pages itself, slowly (10 seconds or more between requests, robots.txt respected, no login). A browser save plus `ingest` still works as a fallback.
- **Output:** `clip_monitor_data/campaign_snapshots.csv` (one row per campaign per snapshot) and `snapshots.jsonl` (one line per snapshot, with file hash). Raw pages are kept beside them.

## Sources (checked 2026-10-21)

| Source | Public list? | robots.txt | Terms on automation | Collected how |
|---|---|---|---|---|
| Vyro (vyro.com/campaigns) | Yes, 12 newest server-rendered; the rest via its campaigns sitemap | Allows | Forbid "data mining, scraping" | Automated (owner's decision, 2026-10-21) |
| Clipping.net (homepage cards) | About 4 featured campaigns | Allows | Forbid "automated tools to access services" | Automated (owner's decision, 2026-10-21) |
| Whop Content Rewards | No, login required | n/a | n/a | Not collected |
| Content Rewardz | No, login required | Crawl-delay 10 | n/a | Not collected |
| Clipur (clipur.ai, clipur.com) | No list, marketing pages only | Disallows /app/ | n/a | Not collected |
| Lumina Clippers | Agency, no list | Allows all | n/a | Not collected |
| ClipAffiliates | Reported list | Cloudflare blocked our sandbox | Not checked | Not collected |

`python -m clip_monitor sources` prints the same registry from `clip_monitor/sources.py`, which is the source of truth.

## Daily automatic snapshot

One run fetches the Vyro board, then Vyro's campaigns sitemap and the detail page of every campaign the board did not show (up to 40, `--max-details`), then the Clipping.net homepage. That is about 25 requests, taking 4 to 5 minutes at the polite pace.

```
python -m clip_monitor fetch --all --data C:\Sandbox\TwitterHate\data\clip_monitor
python -m clip_monitor summary --data C:\Sandbox\TwitterHate\data\clip_monitor
```

To schedule it on Windows (daily at 09:00), run this once in a Command Prompt (not PowerShell) opened in the repo folder:

```
schtasks /Create /SC DAILY /ST 09:00 /TN "TwitterHate clip monitor" /TR "cmd /c cd /d %CD% && python -m clip_monitor fetch --all --data C:\Sandbox\TwitterHate\data\clip_monitor >> C:\Sandbox\TwitterHate\data\clip_monitor\fetch.log 2>&1"
```

Exit codes: 0 all fine, 1 some URLs failed (listed in the log; campaigns that ended and now return 404 do not count), 3 a source is switched off.

## Manual fallback: save pages from a browser

1. Open https://vyro.com/campaigns in Chrome or Edge. Not logged in.
2. Press Ctrl+S, choose "Webpage, HTML only", save into `C:\Sandbox\TwitterHate\data\clip_monitor\inbox\` as `vyro_YYYY-MM-DD_p1.html`.
3. Click to page 2 (and further pages if any). Press Ctrl+S, choose **"Webpage, Complete"** this time (later pages load in the browser, so only a full save keeps them), and save as `vyro_YYYY-MM-DD_p2.html`.
4. Open https://clipping.net/ and save it as `clipping_YYYY-MM-DD.html` ("Webpage, HTML only").
5. Run, from the repo folder:

```
python -m clip_monitor ingest C:\Sandbox\TwitterHate\data\clip_monitor\inbox\vyro_*.html --source vyro --data C:\Sandbox\TwitterHate\data\clip_monitor
python -m clip_monitor ingest C:\Sandbox\TwitterHate\data\clip_monitor\inbox\clipping_*.html --source clipping_net --data C:\Sandbox\TwitterHate\data\clip_monitor
```

The time of a snapshot is the file's saved time unless you pass `--observed-at 2026-10-28T15:00:00Z`. Ingesting the same file twice is harmless: it is recognised by hash and skipped.

Optional: save single campaign pages (`vyro.com/campaigns/<name>`) the same way; `ingest` detects them and fills in platforms for campaigns that only appeared as cards.

## The data, column by column

| Column | Meaning |
|---|---|
| `snapshot_id`, `observed_at` | Which snapshot, when (UTC) |
| `source`, `campaign_id` | Marketplace and its stable campaign key |
| `name`, `buyer` | Campaign title and the paying workspace or brand |
| `payout_model` | `cpm` (per view) or `bounty` (fixed pot) |
| `rate_per_1k_usd`, `rate_is_max` | Headline USD per 1,000 views; `true` when the site shows an "up to" ceiling or a range |
| `platform_rates_per_1k` | Per-platform rates, e.g. `tiktok=3;x=2.5` |
| `platforms`, `platforms_known`, `targets_x` | Platforms that pay; `targets_x` is blank when unknown, never guessed |
| `budget_*` | Listed budget, spent and remaining (Vyro only) |
| `status`, `is_locked`, `start_date`, `end_date` | Campaign state; Clipping.net end dates come from "N days left" |
| `min_views_per_clip` | Views a clip needs before it earns |
| `required_hashtags` | Disclosure and campaign hashtags clippers must use; feeds the paid-clipper rule |
| `topic`, `topics`, `topic_keywords` | Keyword topic tags; primary topic is the first of politics, gambling, crypto, commentary, podcast, streamer, gaming, music, brand |
| `url` | Campaign page |

`summary` shows, per source, the campaigns seen in the last 7 days (`--window-days` to change): rate median and range, how many pay for X views, topic counts and the biggest buyers by listed budget.

## Paid-clipper rule

See [PAID_CLIPPER_RULE.md](PAID_CLIPPER_RULE.md). Short version: a marketplace affiliate badge or a campaign hashtag in the account's posts confirms payment; clip-account bios and handles make it "likely"; everything is logged with the signals that fired.

## How the fetcher behaves

`fetch --source <key>` or `fetch --all` only runs for sources with `automated_allowed=True` in `sources.py` (Vyro and Clipping.net). It checks robots.txt and refuses if robots.txt disallows the page or is missing, waits at least 10 seconds between requests per host (longer if the site sets a Crawl-delay), sends an honest user agent, and never sends cookies or logins. Every snapshot's `method` column says `fetch` or `manual_save`.

## First look (2026-10-21, one-off check while building)

Seen while building the parsers, from a handful of page loads. Treat as a preview; the daily snapshots are the real data.

- Vyro: 12 newest campaigns, USD 1.00 to 2.50 per 1,000 views, buyers mostly games and creators (Call of Duty with a USD 60,000 budget, MrBeast, Valorant, a podcast network). None paid for X views; all were TikTok, YouTube or Instagram.
- Clipping.net: 4 featured campaigns; 3 pay for X views. The highest rate was the gambling brand Stake at up to USD 3 per 1,000 views.
- No political campaign was listed publicly on either site. The known political clip money (Lumina, per the New York Times, 2026-10-20) runs through an agency with no public listing.

## Tests

```
pip install pytest
python -m pytest -q
```

Fixtures in `tests/fixtures/` are synthetic pages with the same structure as the live sites, not copies of them.
