# Capture recorder

Fast hand capture of X threads that stays inside X's rules on automation.

**You** open, scroll and switch sorts. The recorder only keeps a copy of the
thread data your browser already downloaded. It never opens pages, scrolls,
clicks, or sends a single request to X. It does not read cookies or headers,
so no login token is ever saved.

Two parts:

| Part | What it does |
|---|---|
| Chrome extension (this folder) | Watches the page's own `TweetDetail` responses (the thread and its replies) and hands them to the helper on `127.0.0.1`. Shows a small counter in the bottom-left corner of x.com. |
| Local helper (`python -m twitterdata assist`) | Queue page of due captures. Matches each thread view to its tracker capture id, saves a token-free bundle, parses it into the reply table and marks the capture done. |

## One-time setup (Windows, about 5 minutes)

1. In the repo folder: `pip install -e .`
2. Chrome: go to `chrome://extensions`, switch on **Developer mode** (top right), click **Load unpacked**, pick this `capture-extension` folder.
3. Pin the extension (puzzle icon, then the pin) so the pause button is one click away.
4. Start the helper and leave it running in its own window:

   ```
   python -m twitterdata assist
   ```

5. Open <http://127.0.0.1:8765/> and click anywhere once to allow "capture window open" notifications.

To start the helper automatically at login, put the command above in a `.bat` file in `shell:startup`.

## Each capture (about 1 to 2 minutes)

1. On the queue page, click **Open thread** on the top card (or press `N`).
2. Scroll the replies. The corner counter shows `Relevant 6h: 143/200 saved` and turns green at 200. Keep going past the "show probable spam" fold if it appears. If the thread runs out first, that is fine.
3. Switch the sort (in the order the card lists, currently Relevant then Likes) and scroll again. Each sort is saved on its own.
4. Close the tab. The queue page strikes the done sorts off within 15 seconds.

The sort order comes from X's own request, the age bucket from the tracker
schedule, and the viewer label from `--viewer` (default `A`). A capture outside
its window is recorded as `late`, as the tracker already does.

Corner messages:

| Message | Meaning |
|---|---|
| `reload from top` | The extension started while you were mid-thread, so display ranks are not absolute. Reload the page and scroll again. |
| `already captured, kept the earlier one` | You reopened a thread whose capture was already done in this window. The first, fuller capture is kept. |
| `kept in organic set` | Not a scheduled capture (see below). |
| `Helper not running` | Start `python -m twitterdata assist`. |

## Always-on mode, and what it records

The recorder runs whenever Chrome is open on x.com, not only during
scheduled captures. Be aware of what that means:

- **Every thread you open on X is recorded on your PC**, including threads you read for fun. Only thread pages (`TweetDetail`) are kept, not your home timeline, DMs, notifications, likes or searches.
- Threads the tracker has due are filed as scheduled captures, as above.
- Everything else goes to a separate **organic** set under `captures/organic/`. It is a convenience sample of what one person happened to read, not the pre-registered random sample, so it never touches the tracker and must not be used in the confirmatory tests. It suits exploratory checks only.
- Nothing leaves your PC. Files live under `captures/`, which is gitignored. Reply authors are stored as salted hashes in the tables. The raw bundles under `raw/` still hold the full reply data X sent, so treat them as personal data and never upload them.

**To pause:** click the extension's toolbar button. It shows a red `OFF` badge
while paused and nothing is saved. Click again to resume. To stop organic
recording but keep scheduled captures, start the helper with `--no-organic`.
Closing the helper window also stops all saving.

## Files

```
captures/
  raw/<capture_id>.tdcapture.json      token-free bundle, re-parse with `python -m twitterdata parse`
  tables/<capture_id>.csv              reply table, referenced from the tracker
  organic/raw/, organic/tables/        everyday browsing, named <tweet>_<sort>_<time>_<viewer>
```

## Helper options

| Flag | Default | Meaning |
|---|---|---|
| `--port` | 8765 | Port on 127.0.0.1. If you change it, set the same port in the extension's options. |
| `--out` | `captures` | Output folder. |
| `--viewer` | `A` | Viewer label in capture ids. |
| `--viewer-type` | `free` | `viewer_type` column. |
| `--include-text` | off | Fill the reply `text` column (needed for incivility coding). The raw bundle keeps text either way, so you can re-parse later. |
| `--no-organic` | off | Drop views that match no due capture. |
| `--sampling-dir`, `--data` | repo `sampling/` | Where the tracker and its CSVs live. |

## Why this fits X's rules

X's terms ban accessing the service "by any means (automated or otherwise)
other than through our currently available, published interfaces" and ban
"crawling or scraping ... in any form" without consent. A person using
x.com in a browser is using a published interface. The recorder adds no
traffic and drives nothing, so X sees normal browsing. It is a stricter
version of the DevTools "Save as HAR" method. It is not zero risk: a strict
reading could call saving the data "scraping". The realistic worst case is a
suspension of the viewing account. This is a reading of the rules, not legal
advice.

## Safety

- The helper listens on `127.0.0.1` only and answers only requests with a
  localhost `Host` header. Saves must come from a browser extension origin,
  so a website you visit cannot post fake captures.
- Bundles keep only the request path plus its `variables` parameter, the
  response status, time and body. The parser's loader drops any header,
  cookie or query object again when reading.

## Tests

```
pytest -q tests/test_assist.py
node --test capture-extension/test/*.test.js
```
