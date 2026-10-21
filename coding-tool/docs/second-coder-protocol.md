# Second-coder protocol (free plan)

Who codes, in what order, and how disagreements are settled. Everything here is free.

## The short version

1. Draw a **pilot** (100 replies) and a **gold set** (300 replies) with `sample`.
2. Two blind human coders: **one volunteer** and **Zachary**. Both code the same items, separately.
3. Check alpha after the pilot. Below 0.67 on a key field: fix the codebook wording, recode the pilot.
4. Code the gold set. The free AI coders are scored against it.
5. Settle disagreements with the **volunteer's label as the tie-break**.

## Why the volunteer's labels count most

Zachary knows the hypothesis and has read the earlier findings. That is a known source of bias
(expectation bias): borderline replies tend to get read the way the hypothesis predicts. The
volunteer has no stake, so on any disagreement the volunteer's code wins unless both agree
after discussion. Report alpha both ways (Zachary vs volunteer) so a reader can see the gap.

## Rules for every coder

- Code from the page only. **Do not look replies up on X**: that shows the handle, blue check and likes.
- Do not discuss specific replies with the other coder until both have finished.
- When unsure, pick the milder code and say why in the note.
- Code in short sessions (20 to 30 minutes). Fatigue lowers agreement.
- Do not read `FINDINGS.md` or the synthesis before coding (volunteer only; it is too late for Zachary).

## Finding a free volunteer

Good fits: a friend or colleague with no view on the streamer drama, a student in a social
science methods course (coding practice counts for them), or a research-volunteer forum.
About 300 replies take 3 to 5 hours. A volunteer needs nothing installed: they get one HTML file.

## Commands

Run from `coding-tool/`. `items.csv` is the full blind file from `build-items`.

```bash
# Optional: free AI pre-pass so the sample can oversample rare classes
python -m blindcode ai-code work/items.csv --backend detoxify

# Pilot, then gold set (gold excludes pilot items)
python -m blindcode sample work/items.csv work/pilot.csv --n 100 --enrich-coder ai-detoxify --enrich-fields hate_speech,threat --min-per-field 20
python -m blindcode sample work/items.csv work/gold.csv  --n 300 --enrich-coder ai-detoxify --enrich-fields hate_speech,threat --min-per-field 50 --exclude work/pilot.csv

# One page per coder (each gets their own shuffled order)
python -m blindcode page work/pilot.csv --coder volunteer --out work/pilot_volunteer.html
python -m blindcode page work/pilot.csv --coder zach      --out work/pilot_zach.html

# When the CSVs come back
python -m blindcode import codes_volunteer.csv --coder volunteer
python -m blindcode import codes_zach.csv --coder zach
python -m blindcode report --humans volunteer,zach --reference volunteer --out work/pilot_report.md
```

`--reference volunteer` makes the volunteer's labels the yardstick for AI precision, recall and F1.
For the gold set, use separate stores (`--store work/gold_coders`) so pilot and gold codes stay apart.

## What "pass" means here

- Humans pass when alpha is at least 0.67 on every key field.
- An AI coder passes when its worst alpha against either human is at least the human alpha minus 0.05.
- Rare classes: aim for at least 50 hate-speech candidates in the gold set. With fewer, the report
  will warn that alpha for that field is unstable, and that field should be reported as descriptive only.
