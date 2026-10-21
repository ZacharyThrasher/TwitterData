# Thread sampling tracker

Picks threads for the study by fixed rules, schedules their captures, and records what happened to each one. The rules come from `docs/preregistration.md` and live in `config.json`.

Python 3.10+, standard library only. Tests: `python -m unittest discover sampling`.

## Files in `data/`

| File | One row per | What it answers |
|---|---|---|
| `seed_accounts.csv` | seed account | Which accounts we watch, and why each was included |
| `sessions.csv` | discovery session | When we look for new threads (random, all times of day) |
| `candidates.csv` | screened post | Every post we considered, the decision, and the reason |
| `threads.csv` | selected thread | Its strata, why it was selected, and its status |
| `captures.csv` | scheduled capture | 9 per thread (1h, 6h, 24h x Relevance, Recent, Likes): window, status, output file |

## Daily workflow

```bash
# once, before collection
python sampling/tracker.py add-seed SomeHandle --topic sports --account-type news_official --why "national sports desk"
python sampling/tracker.py plan-sessions --start 2026-11-02 --seed 20261102

# during a session: log every post you screen, pass or fail
python sampling/tracker.py screen 2112779086036599242 --handle SomeHandle --followers 480000 \
  --posted 2026-11-02T14:05:00Z --replies 32 --session S0004 \
  --topic sports --account-type news_official --politics none_unclear

# what needs capturing now or in the next hour
python sampling/tracker.py due

# after each capture (point at the parser output, never a raw .har)
python sampling/tracker.py mark 2112779086036599242_h01_relevance_A --status done \
  --file-ref captures/2112779086036599242_h01_relevance_A.csv --n-replies 187

# if a thread disappears
python sampling/tracker.py drop 2112779086036599242 --reason deleted

# progress, stop rule and integrity
python sampling/tracker.py status
python sampling/tracker.py validate
```

## Rules the tool enforces

- **Eligibility:** original post or quote, at most 40 minutes old when found, at least 15 replies, poster has 10k+ followers, not protected, poster not already sampled.
- **Selection:** first eligible post whose cell has room. 18 English cells (topic x account type) of 7, plus 18 Spanish cells of 1, for 144 threads.
- **Balance:** at least 50 threads per follower band; left and right posters each at least 20, then neither more than 1.5 times the other.
- **Captures:** a capture outside its window is recorded as `late`, not discarded.
- **Drop-outs:** a thread lost before its 6h Relevance capture frees its cell; after that it stays as `partial`.
- **Safety:** refuses any `.har` file reference, since raw HAR files carry login tokens.

Capture ids (`{root_tweet_id}_h{01|06|24}_{sort}_{viewer}`) are passed to the capture parser as `capture_id`, so reply tables join back to this tracker.
