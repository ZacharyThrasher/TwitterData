# blindcode: blind reply coding

A small, dependency-free Python tool for coding X replies against a fixed codebook, so the
TwitterHate results can be checked by more than one coder.

- **Blind.** Coders see the thread context and the reply text. Never the handle, blue check, views, likes or rank.
- **Per coder.** Each coder's codes live in their own append-only file.
- **AI third coder.** Pluggable. Offline backends by default; the paid Claude backend is off unless explicitly allowed.
- **Agreement report.** Krippendorff's alpha with a 95% bootstrap interval, pass/fail rules, F1, and a bias check.

Implements methods section 6.6 and 6.7 of `research/data-and-methods.md`.

## Quick start

Run commands from this `coding-tool/` folder. Python 3.10+, no required packages. On Windows use `py` instead of `python`.

```bash
pip install -e .[dev]            # optional: gives the `blindcode` command and test tools

# 1. Make the blind items file (keeps only uid, text, context)
python -m blindcode build-items analysis_merged.csv work/items.csv

# 2. Each human codes on their own
python -m blindcode code work/items.csv --coder zach
python -m blindcode code work/items.csv --coder coder2

# 3. AI third coder (free offline baseline shown; see "AI coder" below)
python -m blindcode ai-code work/items.csv --backend keyword

# 4. Report
python -m blindcode report --out work/report.md
```

Existing codes (for example `coded_A.csv`) can be loaded with
`python -m blindcode import coded_A.csv --coder A`.

## How blinding works

| Step | What is enforced |
|---|---|
| `build-items` | Writes only `uid`, `text`, `context`. Strips the leading `@reply-to` handles (keep them with `--keep-mentions`). Warns if a reply names its own author. |
| `code` / `ai-code` | Refuse any items file with an extra column. |
| Session screen | Shows thread context and reply text only; not even the uid. Each coder gets their own shuffled order. |
| Storage | `work/coders/<coder>.jsonl`. A session reads only its own coder's file. |

`work/` is git-ignored: reply text and codes are research data, not code.

## Coding session keys

Type the option number or the value. `?` shows the field's definition, `b` goes back one field,
`s` skips the item, `q` saves and quits. After the last field, Enter saves and `r` redoes the item.
Sessions resume where they stopped.

## AI coder

| Backend | Cost | Use |
|---|---|---|
| `keyword` | free | Crude deterministic baseline so the pipeline runs offline. **Not** a valid research coder. |
| `replay` | free | Re-parses raw outputs saved by an earlier AI run (`--replay-from <coder>`). |
| `anthropic` | paid | Claude, pinned model (default `claude-opus-5-5`), fixed effort, JSON-schema-constrained output. |

The paid backend needs **both** `--allow-paid` and the environment variable `BLINDCODE_ALLOW_PAID=1`.
Without them it prints a cost estimate and stops. Install the SDK with `pip install -e .[anthropic]`.

What gets saved on every AI code: model requested, model actually served, effort, prompt hash,
raw output, token counts. Pinning choices:

- A served model that differs from the pinned one is an error, not a silent swap.
- Refusal fallbacks are off on purpose, because a fallback changes the model mid-run. Refusals are logged to `<coder>.errors.log`.
- Current Claude models do not accept `temperature`, so "temperature 0" from the methods note cannot be set. Reproducibility comes from the pinned model, fixed effort, saved prompt hash and saved raw outputs. To measure run-to-run stability, run it twice under two coder IDs and read their pairwise alpha.

To add another backend, write a class with a `name` and `code(item, codebook) -> AIResult`
(see `blindcode/ai/base.py`).

## Report and pass rules

| Rule | Passes when |
|---|---|
| Humans | Krippendorff's alpha across all human coders is at least **0.67** |
| AI | Its **worst** alpha against any single human is at least human alpha minus **0.05**. Shown as BLOCKED until humans pass. |

Headline verdicts use the key fields (all coded fields except `argument_tag`). A field where
nobody ever used more than one value has undefined alpha and shows N/A. The report also warns
when a binary field's rarer class has fewer than 10 codes (alpha is unstable; oversample).

Optional bias check (methods 6.6 step 4): pass `--groups file.csv --group-col premium`, where the
CSV has `uid` and a group column. The report splits AI F1 by group and flags gaps above 0.10.
Group data joins only at report time, so coders still never see it.

## Codebook

`blindcode/codebooks/reply_v1.json` is the v1 codebook from `analysis/thread-reanalysis/codebook.md`,
word for word. Its SHA-256 is stamped on every code; the report warns if coders used different
versions. To change the codebook, copy the file, edit it, and pass `--codebook path.json`.

## Tests

```bash
python -m pytest
```

Alpha is checked against Krippendorff's published example (0.743) and against the
`krippendorff` package on random data with missing values. The Claude backend is tested with a
fake client, so tests never call the API.
