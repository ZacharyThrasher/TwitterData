# Rule: tagging an X account as a paid clipper

Rule version 1 (2026-10-21). Code: `clip_monitor/clipper_rule.py`. Tests: `tests/test_clipper_rule.py`.

## Why we need it

Clip-bounty marketplaces pay posters per 1,000 views. If a thread's original post comes from a paid clipper, the poster earns money from attention however it is won, which matters for the "outrage is paid for" question. We want a repeatable, documented way to mark those accounts so they can be a stratum in sampling and a covariate in models.

## The tiers

| Tier | Meaning | What it takes |
|---|---|---|
| `paid_confirmed` | Public evidence of payment | At least one **strong** signal |
| `paid_likely` | Looks and acts like a bounty clip account | Two or more **medium** signals, or one medium plus one **supporting** signal other than Premium |
| `clip_possible` | Some clip-account traits | Exactly one medium signal |
| `none` | No signs | Nothing above |

Only `paid_confirmed` says money changed hands. `paid_likely` describes behaviour; many fan clip accounts are unpaid.

## Signals

**Strong (each one alone gives `paid_confirmed`)**

- `affiliate_badge_marketplace`: the account's X affiliate badge names a clipping marketplace or agency (Clipur, Vyro, Clipping, Whop, Content Rewards, Lumina, ClipFarm, ClipAffiliates, Reach.cat). Example: @AutisticClip carries a Clipur.ai badge.
- `campaign_hashtag_in_post`: one of the account's posts carries a campaign-specific hashtag that a marketplace snapshot lists as required for that campaign (for example `#MW4partner` or `#VyroPartner`). The list comes from `required_hashtags` in `campaign_snapshots.csv`, so it grows with every snapshot.

**Medium (clip-account identity)**

- `bio_clips`: bio mentions clips, clipper or clipping.
- `bio_not_impersonating`: bio says "not impersonating" (clip accounts post other people's faces and add this to avoid impersonation reports).
- `bio_fan_or_parody`: bio says fan account, parody or not affiliated.
- `bio_dm_for_promo`: bio offers "DM for ads / promo / submissions / removal".
- `handle_or_name_clip`: handle or display name contains "clip", ends a word in "mp4", or says "highlights". Known false friends (eclipse, clipboard, paperclip, LA Clippers) are removed from the handle, name and bio before any pattern runs.

**Supporting (only lift a medium signal)**

- `professional_account`: X professional type is Business or Creator.
- `media_share_50pct`: at least half of the account's posts carry media (50 or more posts total).
- `generic_disclosure_hashtag`: a post uses `#ad`, `#sponsored`, `#paidpartnership`, `#partner` or `#promo`. Shows a paid post but not who paid.
- `premium_subscriber`: blue check. Recorded because Premium is needed for X creator payouts, but it never lifts a tier on its own, since most active repliers have it.

## Worked examples (from the 2026-10-20 parent clip capture)

These three accounts were the only repliers in the first 55 minutes under the @AutisticClip post. They are labelled A to C because the project does not publish ordinary repliers' handles; the mapping is in the local capture files.

| Account | Signals | Tier |
|---|---|---|
| Clip account A | bio_clips, bio_not_impersonating, bio_dm_for_promo, professional_account | `paid_likely` |
| Clip account B | bio_clips, bio_not_impersonating, bio_dm_for_promo, handle_or_name_clip | `paid_likely` |
| Clip account C | handle_or_name_clip, professional_account | `paid_likely` |

Running the rule over all 220 parent-thread repliers tags exactly these three as `paid_likely` and none as confirmed. Across the 322 accounts in the quote-tweet thread it tags none. An earlier draft of the handle check tagged an account whose display name contained "ECLIPSE"; that false friend is now excluded and covered by a test.

## Known limits

- **No payout records.** Marketplaces do not publish who they paid. `paid_confirmed` depends on the account's own public signals.
- **Badge coverage.** Only accounts whose marketplace set up an X affiliate badge show one.
- **Hashtag coverage.** We only know hashtags for campaigns we have snapshotted, and Whop (the biggest marketplace) is behind a login.
- **Undisclosed political clipping.** The 2026 New York Times case shows paid political clippers that post without any disclosure. This rule cannot see them unless they also look like clip accounts.
- **English-only patterns.** Bio and handle patterns are English.

## How to run

```
python -m clip_monitor tag-accounts path/to/replies_or_profiles.csv --out tags.csv --data clip_monitor_data
```

The input needs `screen_name` (or `user_id`) and whichever of these it has: `name`, `description`, `professional_type`, `affiliate_badge`, `is_blue_verified`, `statuses_count`, `media_tweets_count`, `full_text`. Our existing capture CSVs already use these names. Several rows per account are fine; their `full_text` values are pooled for the hashtag check.

## Changing the rule

Change the code and this file together, bump `RULE_VERSION`, and add a test for the case that prompted the change. Every output row carries `rule_version`, so older tags stay traceable.
