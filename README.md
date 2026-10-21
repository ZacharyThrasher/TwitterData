# TwitterData

Research code for the TwitterHate project: how X ranking and monetisation reward outrage and paid reply placement.

- `docs/preregistration.md`: hypotheses, predictions, analysis plan and stopping rules.
- `sampling/`: thread sampling tracker (selection, capture schedule, status).
- `src/twitterdata/capture/`: safe capture parser that turns X thread captures into the reply table ([schema](docs/reply_table_schema.md)).
- `src/twitterdata/bluesky/`: Bluesky comparison collector, same reply table with `platform = bluesky` ([mapping](docs/bluesky_mapping.md)).
- `analysis-pipeline/`: runs the pre-registered tests (T1 to T3, T9, T10, O1, O2) and exploratory tests A1 to A9 on many reply tables ([README](analysis-pipeline/README.md)).

Raw `.har` captures contain login tokens and must never be committed.

## Safe capture parser

Turns a browser capture of an X thread into the standard **reply table**
(one row per reply, with display position, sort order, viewer type and
pseudonymous author info). Schema: [docs/reply_table_schema.md](docs/reply_table_schema.md).

### Safety rules (read first)

- Raw `.har` files from a logged-in browser contain **live session tokens**
  (`auth_token`, `ct0`, the bearer header). Never commit, upload or share them.
  `.gitignore` blocks `*.har`.
- The parser drops every `headers`, `cookies`, `postData` and `queryString`
  object while it decodes the file, keeps only `TweetDetail` responses, and
  reads only `focalTweetId`, `rankingMode` and cursor presence from the URL.
  It never prints URLs or file contents.
- Output cells that look like a session secret are replaced with `REDACTED`
  as a second line of defence.
- Author handles and ids are replaced with salted hashes. The salt lives at
  `~/.config/twitterdata/hash_salt` (or `TWITTERDATA_HASH_SALT`), outside the repo.
- Tests use only synthetic captures (`tests/synthetic.py`).

### Install

```
pip install -e ".[test]"
```

### Capture a thread

1. Open the thread on x.com, open dev tools (F12), Network tab, filter `TweetDetail`.
2. Pick the sort (Relevance, Recent, Likes), reload, and scroll to load the replies you want.
3. Right-click the request list, "Save all as HAR".

### Parse it

```
python -m twitterdata parse "x.com_Archive.har" -o output/replies.csv \
    --viewer-type free --viewer-label A --age-bucket h06 \
    --capture-id 2112654828199391249_h06_relevance_A
```

| Flag | Meaning |
| --- | --- |
| `--viewer-type` | `logged_out`, `free`, `premium`, `premium_plus` or `unknown` (the parser cannot tell on its own) |
| `--viewer-label` | Persona label, for example `A` |
| `--capture-id` | Id for this capture (one input file only); default is the file name |
| `--sort-order` | Override the sort read from the request |
| `--age-bucket` | Thread age bucket, for example `h06` |
| `--include-text` | Fill the reply `text` column (off by default) |
| `-o file.jsonl` | Write JSON Lines instead of CSV |

A saved single response body (`.json`, "Copy response" in dev tools) also
works; pass `--capture-time` and, if needed, `--focal-tweet-id`.

### Schema files

```
python -m twitterdata schema --format json      # print the schema
python -m twitterdata schema --write            # regenerate docs and JSON after editing src/twitterdata/schema.py
```

## Bluesky comparison collector

Collects Bluesky reply threads from the free public API (no login, no key)
into the same reply table, so X and Bluesky can be analysed side by side.
Bluesky has no paid tier and no ads, which makes it the control platform.

```
python -m twitterdata bluesky collect "https://bsky.app/profile/someone.bsky.social/post/3abc..." \
    --sort relevance --sort recent --age-bucket h06 -o output/bsky.csv
python -m twitterdata bluesky parse data/raw/bluesky/*.json -o output/bsky.csv   # rebuild offline
```

- Paced at 1 request per second, with retries and backoff.
- Raw responses are saved as bundles in `data/raw/bluesky/` (git-ignored; they
  hold real handles and text).
- Bluesky-only fields (moderation labels, reply depth, index time) go to
  `<output>.bluesky_extras.csv`.
- Full mapping, ordering rules and gaps: [docs/bluesky_mapping.md](docs/bluesky_mapping.md).

### Tests

```
pytest -q
```
