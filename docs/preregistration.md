# Pre-registration: outrage incentives and paid reply placement on X

| | |
|---|---|
| Status | Draft v1.1 (2026-10-21: capture plan trimmed before collection, see section 8). v1.0 written 2026-10-21. Freeze before the first thread is selected, then post to OSF. |
| Owner | Zachary Thrasher |
| Sampling tool | `sampling/tracker.py`, rules in `sampling/config.json` |
| Reply data | Reply table produced by the capture parser (`src/twitterdata/capture/`): `docs/reply_table_schema.md` and `schema/reply_table.v1.json`. This document uses that schema's field names and does not redefine them. |
| Background | `research/mechanics.md` (sections 3, 4, 8, 9), `research/data-and-methods.md` (section 6), `analysis/thread-reanalysis/FINDINGS.md` in the project files |

---

## 0. One-screen summary

- **Question.** Does X's design pay for posts that provoke anger, and does paid placement (Premium reply priority) decide whose replies people see?
- **What we collect.** 144 viral threads, stratified by topic, poster type (paid clipper, organic creator, news or official) and poster politics. Each thread is captured at 6 and 24 hours after posting, under the Relevance and Likes sorts. That is 4 captures per thread, 576 in total (trimmed from 1,296 before collection; see section 8).
- **What we test.** Seven confirmatory predictions: Premium-first placement (T1), toxic replies ranked lower within a tier (T2), a stronger toxic-reply penalty under very large accounts (T3), big accounts escaping the insult penalty on their own posts (T9), the toxic-reply penalty being weaker in Spanish than English (T10), and two poster-level outrage predictions (O1, O2).
- **What would change our minds.** Each prediction has a stated pass or fail rule below. Null results get reported with the same prominence as positive ones.
- **When we stop.** When every cell is full, or 56 days after the first selection, whichever comes first. No outcome analysis before the stop.

---

## 1. Hypotheses

Wording follows Zachary's clarified claim (2026-10-21): the target is rage culture, incivility, pile-on harassment and dropped decorum, with platforms and outside buyers paying for posts that provoke anger. "Hate speech" is kept for its strict meaning (attacks on people because of a protected characteristic) and is a secondary outcome only.

| ID | Hypothesis | Level |
|---|---|---|
| H1 | **Paid placement.** X ranks replies from Premium subscribers above replies from non-subscribers, independent of how much engagement the reply earns, so paying accounts get a share of reply attention far larger than their share of replies. | Reply |
| H2 | **The reply ranker penalises incivility, but unevenly.** Within a payment tier, uncivil replies are ranked lower. The penalty is stronger where X's code applies extra scoring (very large accounts) and weaker where its classifiers are weaker (non-English). | Reply |
| H3 | **Outrage pays at the poster level.** Posts written to provoke anger reach more people than calm posts from comparable accounts, and accounts paid by views (clip-bounty clippers) post more outrage-framed content than organic creators. Very large accounts escape the insult penalty that small accounts face. | Poster |

---

## 2. Confirmatory predictions

Tests T1 to T3, T9 and T10 come from `research/mechanics.md` section 9. O1 and O2 make H3 testable with the same sample.

| ID | Prediction | Supports | Pass rule | Fail rule |
|---|---|---|---|---|
| **T1** | In Relevance sort, Premium replies are placed above non-Premium replies regardless of likes. | H1 | Premium coefficient in the rank model is positive with 95% CI above zero after controls, AND Premium reply-view amplification ratio is above 1.5 with CI above 1. | CI includes zero, or the effect disappears under the Likes sort contrast (see 5.2). |
| **T2** | Within a payment tier, more uncivil replies rank lower in Relevance sort. | H2 | Incivility coefficient on within-tier rank percentile is negative with 95% CI below zero. | CI includes zero or is positive (positive would mean the ranker rewards incivility). |
| **T3** | The T2 penalty is stronger under roots whose author has 250k or more followers (the Grok reply-scoring threshold in X's 2026 code). | H2 | Interaction incivility x `focal_author_followers >= 250000` is negative with 95% CI below zero. | CI includes zero. |
| **T9** | Targeted-insult posts from very large accounts keep their normal reach; similar posts from small accounts lose reach. | H3 | Interaction OP-insult x large-account on log views per follower is positive with 95% CI above zero. | CI includes zero or is negative. |
| **T10** | The T2 penalty is weaker for Spanish replies than for English replies (X's insult demotion is English-first). | H2 | Interaction incivility x Spanish on within-tier rank percentile is positive with 95% CI above zero. | CI includes zero or is negative. |
| **O1** | Outrage-framed root posts get more views per follower at 24h than non-outrage posts, controlling for account size, topic and poster type. | H3 | Outrage coefficient on log views per follower is positive with 95% CI above zero. | CI includes zero or is negative. |
| **O2** | Paid-clipper root posts are more often outrage-framed than organic-creator root posts on the same topics. | H3 | Odds ratio clipper vs organic above 1 with 95% CI above 1. | CI includes 1. |

**Smallest effects we care about.** A Premium share of reply views at least 1.5 times its share of replies (T1). A 5 percentile-point rank shift for uncivil replies (T2, T3, T10). A 20% change in views per follower (O1, T9). Effects below these are reported as "too small to matter" even if statistically clear.

**Why these thresholds.** In the two pilot threads Premium was 14.5% of replies and 38 to 52% of reply views (ratio about 2.6 to 3.6), and uncivil replies sat 14 to 22 percentile points lower within tier (`FINDINGS.md` section 3). The thresholds are set well below the pilot values so a real but smaller effect still counts.

---

## 3. Sampling plan

### 3.1 Strata

| Dimension | Levels | How it is assigned |
|---|---|---|
| Topic | politics_government, social_culture_war, streamer_gaming, sports, news_events, entertainment_celebrity | From the root post's text and the seed account's beat, by the screener at discovery. |
| Account type | paid_clipper, organic_creator, news_official | paid_clipper: clip-format account with a clip-marketplace affiliate badge or bio link (Clipur, Whop Content Rewards and similar). news_official: news outlet, journalist on assignment, government or party account. organic_creator: everyone else posting their own content. |
| Poster politics | left, right, none_unclear | From the poster's bio, pinned post and the last 20 posts, coded before seeing any reply data. Second coder on a 20% subsample. |
| Follower band | under_250k, 250k_plus | From the follower count at discovery. The 250k line is the T3 threshold. |
| Language | en (main sample), es (supplement for T10) | Language of the root post. |

### 3.2 Quotas (144 threads)

- **Main sample:** 6 topics x 3 account types = 18 cells, **7 threads each = 126 English threads.**
- **Spanish supplement:** the same 18 cells, **1 thread each = 18 threads.** This guarantees non-English replies for T10.
- **Balancing rules, enforced by the tracker:**
  - At least 50 threads in each follower band.
  - At least 20 left and 20 right posters. After a side reaches 20, it may not exceed 1.5 times the other side.
  - One thread per poster account, so no single account dominates.

Why 144: `data-and-methods.md` section 6.1 estimates 100 to 150 threads (about 30 to 60k replies) gives enough power for a 5-point difference with thread random effects. 144 sits at the top of that range so the confirmatory minimum (100) survives drop-outs.

### 3.3 Frame and selection

1. **Seed list, frozen before collection.** For each cell, at least 8 accounts, chosen to span both follower bands and, where it applies, both politics sides. Each entry records why it was included (`tracker.py add-seed --why`). Seeds are added before the first session and not changed afterwards, except as a logged deviation.
2. **Random discovery sessions.** `tracker.py plan-sessions --seed <n>` draws 3 sessions a day for 56 days, one in each 8-hour block of the UTC day, so all times of day are covered. The seed number is recorded here once chosen: **seed = ________**.
3. **Screening.** During a session the screener checks seed accounts (and, as a second source, Trending and Search) and logs every post that might qualify with `tracker.py screen`. Every screened post is recorded, including the ones that fail, with the reason.
4. **Eligibility (all must hold):**
   - Original post or quote post, not a plain repost or a reply.
   - At most 2 hours old when found (keeps selection early in the thread's life, well before the 6h capture).
   - At least 15 replies when found.
   - Poster has at least 10,000 followers and is not protected.
   - Poster not already in the sample.
5. **Selection rule.** The first eligible post seen whose cell still has room, and which does not break a balancing rule, is selected. The tracker makes this decision, not the screener, and writes the reason to `candidates.csv` and `threads.csv`.

**Outcome-blind selection.** Reply counts at 24h, views and the content of replies are never used to select or drop a thread.

### 3.4 Capture schedule

| Age | Window (relative to due time) | Sorts | Captures |
|---|---|---|---|
| 6 hours | 30 min early to 45 min late | Relevance, Likes | 2 |
| 24 hours | 90 min early to 2 h late | Relevance, Likes | 2 |

- Capture ids follow `{root_tweet_id}_h{06|24}_{relevance|likes}_{viewer}`, for example `2000000000000000001_h06_likes_A`. The parser accepts this id verbatim as `capture_id`.
- Within an age, the two sorts are taken back to back in a fixed order (Relevance, then Likes) to keep them as close in time as possible.
- A capture taken outside its window is kept and flagged `late`. Main analyses use on-time captures; a sensitivity analysis adds late ones.
- `tracker.py due` lists what is open, coming up and overdue.

### 3.5 Capture protocol

- **Viewer A:** one logged-in, non-Premium account, same device, browser, region and language settings throughout. Recorded in the parser as `viewer_label = A`, `viewer_type = free`.
- Scroll the reply section until 200 top-level replies or the end, including past the "show probable spam" / low-quality fold.
- Save only the parsed, credential-free output of the capture parser. **Raw .har files are never stored in the project or the repo** (they contain live login tokens). The tracker refuses a `.har` file reference.
- Manual, low-volume collection from our own account. No third-party scraping services.
- Optional extension, logged as a deviation if used: a second viewer (Premium or logged out) on a random 20% of threads, to separate author-based ranking from viewer personalisation.

### 3.6 Drop-outs and replacement

| Event | What happens |
|---|---|
| Thread deleted, account protected or suspended, or both 6h captures fail, **before the 6h Relevance capture succeeds** | Thread status `dropped`. Its cell reopens and the next eligible post replaces it. |
| Same events **after the 6h Relevance capture succeeds** | Thread status `partial`. Kept in the sample with the data it has. No replacement. |
| Any other reason | Not allowed. A thread is never dropped because of what its replies contain. |

Command: `tracker.py drop <thread_id> --reason deleted|protected|suspended|capture_failure`.

---

## 4. Measures

Reply-level fields come from the parser's reply table (`docs/reply_table_schema.md`). Names below are that schema's names.

| Measure | Source | Definition |
|---|---|---|
| Rank | `display_rank` | Position among top-level organic replies in a capture. Converted to a percentile within the capture, and within the capture and payment tier. Rank models use only captures with `rank_is_absolute = true` (first page captured). |
| Section | `conversation_section` | Above or below the low-quality fold. |
| Premium | `author_is_blue_verified` | 1 if the author pays for any X subscription tier. `author_verified_type` separates Business and Government. |
| Exposure | `view_count` | Views at capture time. |
| Engagement controls | `like_count`, `reply_count`, `quote_count`, `created_at_utc`, `author_followers` | Logged; reply age in hours from `created_at_utc` to capture time. |
| Language | `lang` | Reply language as reported by X. |
| Root size | `focal_author_followers`, `focal_view_count` | Root author followers and root views at capture. |
| Clip marketplace flag | `focal_author_affiliate_label` | Supports the paid_clipper assignment. |
| Incivility (reply) | Blind coding | Codebook v1 (`analysis/thread-reanalysis/codebook.md`): insults, name-calling, profanity at a person or group, contemptuous mockery. Coded from text only, author and rank hidden. |
| Toxicity score (reply) | Automated | Detoxify, version pinned at freeze. Secondary measure for T2, T3, T10. Perspective API is not used (shuts down 2026-12-31). |
| Strict hate speech | Blind coding | Codebook v1 definition. Secondary outcome only. |
| Outrage framing (root) | Blind coding | Root post is written to provoke anger at a person or group: accusation, contempt, mockery, us-versus-them call-out, or "look what they did" framing. Coded from root text only, poster identity hidden. |
| Targeted insult (root) | Blind coding | Root post insults a named person or group. Used for T9. |
| Large account | `focal_author_followers` | 250,000 or more followers (same line as T3). |

**Coding validity.** Follows `data-and-methods.md` 6.6: a 300 to 500 reply human gold set from two coders (alpha at least 0.67), LLM coding used for the rest only if LLM-vs-human alpha is within 0.05 of human-vs-human, and bias checks split by Premium, stance and target group. Coders never see handles, check marks, likes or rank. Codebook frozen before coding starts.

---

## 5. Analysis plan

All confirmatory models use the Relevance sort at the 6h capture unless stated. 6h is chosen in advance as the main age because rank is settled but the thread is still active. 24h is reported as robustness (does the ranking pattern hold as the thread ages).

### 5.1 T1 Premium-first placement

- **Descriptive:** share of captures where every Premium reply sits above every non-Premium reply within the same section (the "wall"). Reported per sort.
- **Model:** linear mixed model of within-capture rank percentile on Premium, controlling for log likes, log author followers, log reply age, whether the root author replied, and text length; random intercept for thread. Sensitivity: rank-ordered logit with thread strata.
- **Exposure:** amplification ratio = Premium share of reply views / Premium share of replies, per thread, then the median and a thread-level bootstrap CI.

### 5.2 Sort contrast (supports T1)

For each reply seen in both the Relevance and Likes captures at the same age: rank under Relevance minus rank under Likes. If Premium replies gain rank under Relevance relative to Likes, the boost is X's placement and not just popularity. This contrast is the T1 falsification check and uses the 6h Likes capture. (A near-chronological Recent baseline was dropped in the 2026-10-21 amendment.)

### 5.3 T2, T3, T10 incivility and rank

- **Model:** within-capture, within-tier rank percentile on incivility (coded), with the same controls as 5.1 and a random intercept for thread.
- T3 adds incivility x large-root-account. T10 adds incivility x Spanish, using the Spanish supplement plus any Spanish replies in English threads.
- Secondary: the same models with the Detoxify score in place of coded incivility.

### 5.4 T9, O1, O2 poster-level

- One row per thread. Outcome for O1 and T9: log(`focal_view_count` at 24h / `focal_author_followers`).
- **O1:** outcome on outrage framing, controlling for log followers, topic, account type, poster politics, Premium status of the poster and time of day. Robust (HC3) errors.
- **T9:** same model with targeted insult x large account.
- **O2:** logistic regression of outrage framing on account type (clipper vs organic) with topic fixed effects.

### 5.5 Multiple tests and reporting

- The seven confirmatory tests are one family, corrected with Holm at alpha 0.05.
- Effect sizes and 95% CIs are reported for every test, along with the smallest-effect thresholds in section 2.
- Replies are never treated as independent across a thread: every reply model has a thread random effect or clustered errors.
- Code, codebook, tracker CSVs and tweet ids (not reply text, not replier handles) are shared for replication.

### 5.6 Exploratory (labelled as such)

Premium x poster politics on the visible top 10 (the parent-thread tilt in `FINDINGS.md`), strict hate speech rates, brigade and coordination checks (`data-and-methods.md` 6.4), ad density, and change from 6h to 24h. None of these can confirm or refute H1 to H3.

---

## 6. Stopping rules

| Rule | Trigger | Action |
|---|---|---|
| Full | All 36 cells reach quota (`tracker.py status` prints STOP) | Stop selecting. Finish scheduled captures for selected threads. |
| Time | 56 days after the first selection | Stop selecting, finish scheduled captures. |
| Minimum | Fewer than 100 threads with an on-time 6h Relevance capture at stop | Confirmatory tests are reported as exploratory, and the shortfall is stated up front. |
| Quality check (allowed during collection) | On-time capture rate below 80% in any week | Adjust staffing or session times only. Logged as a deviation. |
| No peeking | Any time before the stop | Nobody runs outcome models, computes amplification ratios or reads coded incivility by rank. Only capture counts and quota fill may be checked. |
| Platform change | X announces a ranking, Premium or payout change during collection | Record the date. Report results before and after it separately as a sensitivity analysis. Collection continues. |

---

## 7. Known limits, stated before data

- One viewer account. Personalised ranking cannot be ruled out without the optional second viewer.
- View counts are platform totals, not views from the reply section.
- Payout amounts are not observable. Monetisation exposure is proxied by Premium, verified type and clip-marketplace badges.
- Poster politics is inferred from public signals and may be wrong for some accounts; reported with coder agreement.
- X's code shows defaults; production can differ (`mechanics.md` caveat). T3 and T10 test whether the coded behaviour shows up in practice.
- Political and election accounts were excluded from X payouts on 2026-09-08, so payout-driven behaviour among political posters may already have shifted.

---

## 8. Deviations log

Every change after freeze goes here with the date, what changed, why, and whether it was made before or after any outcome data was seen.

| Date | Change | Reason | Outcome data seen? |
|---|---|---|---|
| 2026-10-21 | **Pre-collection amendment (v1.1).** Capture plan trimmed from 9 to 4 captures per thread (1,296 to 576): dropped the 1h capture and the Recent sort; kept 6h and 24h under Relevance and Likes. Rules that depended on the 1h capture changed with it: discovery age limit raised from 40 minutes to 2 hours (3.3), early-failure drop rule now "both 6h captures fail" (3.6), robustness age is 24h only (5), Recent baseline removed from the sort contrast (5.2). Thread count, strata, quotas, predictions, pass/fail rules and stopping rules are unchanged. | Workload: 1,296 manual captures was not realistic for one person, and the 1h capture's 40-minute discovery rule was the hardest timing constraint. The confirmatory tests use 6h Relevance and the T1 falsifier uses 6h Likes, so neither loses data and power is unchanged (rationale in project file `capture/capture-rules-and-options.md`, section 4). Approved by Zachary 2026-10-21. | No. Made before the first thread was selected. |

---

## Plain-language brief

This is the "rules of the game, written before we play" document. We pick 144 busy X threads across six topics, three kinds of posters (paid clip accounts, regular creators, news) and both political sides. A tool picks them by fixed rules so we cannot cherry-pick. We screenshot each thread's replies at 1, 6 and 24 hours under all three sort orders. Then we check seven specific predictions, such as "paid blue-check replies get put at the top" and "angry posts get more views", each with a clear pass or fail line set in advance. We stop at 144 threads or 8 weeks, and nobody looks at results until then.
