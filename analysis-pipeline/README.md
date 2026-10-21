# Reply analysis pipeline

Runs the pre-registered tests on many threads at once. It reads the reply
tables written by the capture parser (and the Bluesky collector), joins the
blind codes, and writes one report with effect sizes and 95% intervals.

It generalises the two-thread scripts in the project files
(`analysis/thread-reanalysis/*.py`) to the full sample.

- **Free and local.** numpy, pandas, scipy, statsmodels. No API calls, no network.
- **No peeking.** `run` refuses to fit outcome models until you confirm the
  collection stop rule was met (pre-registration section 6).
- **No reply text out.** Results hold ids, model variables and estimates only.

## Quick start

```bash
cd analysis-pipeline
pip install -e .[dev]

# Try it on synthetic data with known effects (or --null for a world with none)
python -m replyanalysis demo -o work/demo

# Real data, after collection stops
python -m replyanalysis run captures/ \
    --codes coded_final.csv \
    --threads ../sampling/data/threads.csv \
    --captures ../sampling/data/captures.csv \
    --root-codes root_codes.csv \
    --authors author_codes.csv \
    -o work/results --collection-stopped
```

Outputs in the results folder:

| File | What it holds |
| --- | --- |
| `report.md` | Verdict table first, then details for every test |
| `results.json` | Every estimate, interval, Holm p-value, setting and note |
| `threads.csv` | One row per thread: the poster-level model inputs |
| `a5_stimuli.csv` | Two reply orders per capture for the A5 experiment |

`work/` is git-ignored: results carry tweet ids, which are personal data.

## Inputs

Only the reply tables are required. Each test says plainly when an input it
needs is missing, and is reported as "not run".

| Input | One row per | Needed for |
| --- | --- | --- |
| Reply tables (schema v1, `.csv` or `.jsonl`, files or folders) | reply-list item | everything |
| `--codes` (CSV keyed by `tweet_id` or `uid`, or a blindcode `.jsonl`) | reply | T2, T3, T10, A1 to A4 |
| `--threads` (tracker `threads.csv`) | thread | O1, O2, T9 controls |
| `--root-codes` (`thread_id`, `outrage_framing`, `targeted_insult`, optional `poster_motive`) | thread | O1, O2, T9, A9 |
| `--authors` (`author_id_hash`, optional `motive`, `account_based_in`, `claimed_location`) | author | A6, A9 |
| `--captures` (tracker `captures.csv`) | capture | sets aside `late` captures (add `--include-late` for the sensitivity run) |

Code columns the pipeline looks for: `incivility` (0/1), `attacks_op` (0/1),
`stance`, `pushback` (0/1), `toxicity` (0 to 1, optional secondary score).
Rename with `--incivility-col`, `--toxicity-col`, `--stance-col`.

For the blind coding tool, build items with the reply `tweet_id` as `uid`,
then pass the adjudicated codes file here.

The optional `toxicity` score can come from Detoxify run locally (free, open
weights); add it as a column in the codes file. Perspective API is not used.

## What it tests

### Confirmatory (pre-registration sections 2 and 5)

Main frame: Relevance sort, 6h captures, top-level organic replies, viewer A,
one session per capture that starts at the top of the thread.

| Test | Model | Pass rule |
| --- | --- | --- |
| **T1** Premium placed first | Mixed model of rank height (0 to 100) on Premium plus likes, followers, reply age, OP replied, text length; random intercept per thread. Sensitivity: rank-ordered logit. Plus the Premium amplification ratio and the Likes sort contrast. | Coefficient CI above 0, AND ratio above 1.5 with CI above 1, AND the Likes contrast holds |
| **T2** Uncivil replies sink within tier | Mixed model of within-tier rank height on incivility | CI below 0 |
| **T3** Stronger penalty under 250k+ roots | T2 plus incivility x large root | Interaction CI below 0 |
| **T9** Big accounts escape the insult penalty | OLS (HC3) of log views per follower at 24h on insult x large account | Interaction CI above 0 |
| **T10** Weaker penalty in Spanish | T2 plus incivility x Spanish | Interaction CI above 0 |
| **O1** Outrage reaches further | OLS (HC3) of log views per follower on outrage framing plus controls | CI above 0 |
| **O2** Clippers post more outrage | Logit of outrage on clipper vs organic with topic effects | Odds ratio CI above 1 |

- All seven are one family, **Holm-corrected**. A test passes only when its
  interval rule holds and its Holm p is below 0.05.
- Each result also says whether it clears the **smallest effect of interest**
  (5 rank points, a 1.5x ratio, a 20% reach change).
- With fewer than **100 threads** the report opens with an "exploratory only"
  banner, as the stopping rules require.
- With few threads, collinear poster controls are dropped one at a time and the
  report names them; dropping topic effects in O2 is flagged as a deviation.

### Exploratory (labelled as such in the report)

| Id | Question | Status |
| --- | --- | --- |
| A1 | Top-10 vs all-replies stance gap | runs with `stance` codes |
| A2 | Do replies get ruder after a rude Premium reply reaches the top? | difference-in-differences with thread fixed effects |
| A3 | Do Premium pile-on repliers gain followers? | author panel across captures |
| A4 | Do people who push back and get piled on post less? | author panel; weeks need later captures |
| A5 | Perceived-consensus experiment | **stub**: needs participants; exports the stimuli |
| A6 | "About this account" country vs claimed location | needs an author file (not in schema v1) |
| A7 | Reply pods: same accounts replying within seconds across threads | permutation test, candidate pods by author hash |
| A8 | Before vs after the 17 Jan 2026 payout change | **stub until historical data exists**; interrupted time series, runs as soon as 4+ weeks sit on each side |
| A9 | Farmer vs ideologue repliers and posters | needs `motive` / `poster_motive` codes |

Also reported: incivility exposure ratio, the "uncivil replies get about half
the views" multiplier, and the near-duplicate text check from `brigade.py`
(needs `--include-text` captures).

## Platforms

Rows from other platforms are set aside: `--platform x` (default) or
`--platform bluesky`. Bluesky has no Premium and no view counts, so T1 and the
exposure ratios do not run there; the incivility ranking models (T2) do, which
is the comparison the control platform is for.

## Checked against the pilot

Converting the two pilot threads into schema v1 and running `run` reproduces
`FINDINGS.md`: Premium 14.5% of replies, amplification ratio about 3,
uncivil replies about 0.47x the views of comparable civil ones, and uncivil
replies about 19 rank points lower within tier. With 2 threads the report is
correctly marked exploratory only.

## Tests

```bash
cd analysis-pipeline && python -m pytest -q
```

Synthetic worlds with planted effects (every confirmatory test should pass,
the planted reply pod is found exactly) and a null world (nothing passes, no
pods). The schema test fails if `schema/reply_table.v1.json` changes structure
and the copy in `replyanalysis/data/` is not updated.
