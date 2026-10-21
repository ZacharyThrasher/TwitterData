"""Command line entry point: python -m clip_monitor <command> ...

Commands
  sources        list marketplaces, access status and whether collection is allowed
  ingest         parse browser-saved campaign pages into the snapshot dataset
  fetch          fetch listing pages directly (only for sources that permit it)
  summary        print a short summary of the latest snapshot per source
  tag-accounts   apply the paid-clipper rule to an X account CSV
"""

from __future__ import annotations

import argparse
import csv
import glob
import re
import statistics
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from . import clipper_rule, topics
from .fetch import NotPermitted, PoliteFetcher
from .parsers import PARSERS
from .sources import SOURCES
from .store import SnapshotMeta, Store, make_snapshot_id, sha256_bytes

DEFAULT_DATA = "clip_monitor_data"


def _utc_iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _saved_from_url(page: str) -> str:
    # Chrome and Edge "Save page as" add: <!-- saved from url=(0026)https://vyro.com/campaigns -->
    m = re.search(r"<!--\s*saved from url=\(\d+\)(\S+?)\s*-->", page[:2000])
    return m.group(1) if m else ""


def snapshot_page(store: Store, source_key: str, raw: bytes, observed_at: str, method: str, url: str = "", original_file: str = "", note: str = ""):
    """Parse one page and store it. Returns (stored: bool, campaigns)."""
    page = raw.decode("utf-8", "replace")
    url = url or _saved_from_url(page)
    campaigns = PARSERS[source_key](page, url=url, observed_at=observed_at)
    for c in campaigns:
        topics.apply(c)
    digest = sha256_bytes(raw)
    meta = SnapshotMeta(
        snapshot_id=make_snapshot_id(source_key, observed_at, digest),
        source=source_key,
        observed_at=observed_at,
        method=method,
        page_url=url,
        sha256=digest,
        n_campaigns=len(campaigns),
        original_file=original_file,
        note=note,
    )
    return store.save(meta, raw, campaigns), campaigns


def cmd_sources(args) -> int:
    for s in SOURCES.values():
        auto = "yes" if s.automated_allowed else "no"
        print(f"{s.key:15} {s.access:18} parser={s.parser or '-':13} automated={auto}  {s.name}")
        if s.terms_summary:
            print(f"{'':15} terms: {s.terms_summary}")
    return 0


def cmd_ingest(args) -> int:
    store = Store(args.data)
    source = SOURCES.get(args.source)
    if not source or not source.collectable:
        print(f"Unknown or non-collectable source: {args.source}", file=sys.stderr)
        return 2
    total = 0
    for path in _expand(args.files):
        raw = path.read_bytes()
        observed = args.observed_at or _utc_iso(path.stat().st_mtime)
        stored, campaigns = snapshot_page(
            store, source.key, raw, observed, "manual_save", url=args.url or "", original_file=path.name, note=args.note or ""
        )
        status = "stored" if stored else "already stored, skipped"
        print(f"{path.name}: {len(campaigns)} campaigns, {status}")
        if not campaigns:
            print("  warning: no campaigns found; check the page kind or save it again", file=sys.stderr)
        total += len(campaigns) if stored else 0
    print(f"{total} campaign rows added to {store.csv_path}")
    return 0


def _expand(patterns: list) -> list:
    """Expand wildcards ourselves: the Windows shell passes them through literally."""
    out = []
    for p in patterns:
        matches = sorted(glob.glob(p)) if any(ch in p for ch in "*?[") else [p]
        if not matches:
            print(f"no files match {p}", file=sys.stderr)
        out.extend(Path(m) for m in matches)
    return out


def cmd_fetch(args) -> int:
    store = Store(args.data)
    source = SOURCES.get(args.source)
    if not source or not source.collectable:
        print(f"Unknown or non-collectable source: {args.source}", file=sys.stderr)
        return 2
    fetcher = PoliteFetcher(min_interval=args.min_interval)
    try:
        fetcher.check_source(source)
        for url in source.listing_urls:
            raw = fetcher.fetch(source, url)
            observed = _utc_iso(datetime.now(timezone.utc).timestamp())
            stored, campaigns = snapshot_page(store, source.key, raw, observed, "fetch", url=url)
            print(f"{url}: {len(campaigns)} campaigns, {'stored' if stored else 'unchanged'}")
    except NotPermitted as e:
        print(f"Not fetching: {e}", file=sys.stderr)
        return 3
    return 0


def current_view(rows: list, window_days: float = 7.0) -> dict:
    """Latest row per campaign, per source, among rows seen within window_days
    of that source's newest snapshot. Returns {source: (newest_time, rows)}."""
    newest = {}
    for r in rows:
        if r["source"] not in newest or r["observed_at"] > newest[r["source"]]:
            newest[r["source"]] = r["observed_at"]
    out = {}
    for source, when in newest.items():
        cutoff = _parse_iso(when).timestamp() - window_days * 86400
        latest = {}
        for r in rows:
            if r["source"] != source or _parse_iso(r["observed_at"]).timestamp() < cutoff:
                continue
            latest.setdefault(r["campaign_id"], []).append(r)
        out[source] = (when, [_merge_latest(rs) for rs in latest.values()])
    return out


def _merge_latest(rows: list) -> dict:
    """Newest row for a campaign, with blanks filled from older rows.

    A detail-page save carries fewer fields than the board, so a newer detail
    row should not erase budget or hashtags seen on the board a moment earlier.
    """
    ordered = sorted(rows, key=lambda r: r["observed_at"], reverse=True)
    merged = dict(ordered[0])
    for older in ordered[1:]:
        for k, v in older.items():
            if not merged.get(k) and v:
                merged[k] = v
    return merged


def _parse_iso(s: str) -> datetime:
    d = datetime.fromisoformat(s.replace("Z", "+00:00"))
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def summarize(rows: list, window_days: float = 7.0) -> str:
    lines = []
    for source, (when, cur) in sorted(current_view(rows, window_days).items()):
        rates = [float(r["rate_per_1k_usd"]) for r in cur if r["rate_per_1k_usd"]]
        known = [r for r in cur if r["platforms_known"] == "true"]
        on_x = [r for r in known if r["targets_x"] == "true"]
        lines.append(f"{source}, newest snapshot {when}: {len(cur)} campaigns seen in the last {window_days:g} days")
        if rates:
            lines.append(
                f"  rate per 1,000 views: median ${statistics.median(rates):.2f}, "
                f"range ${min(rates):.2f}-${max(rates):.2f}"
            )
        lines.append(f"  pay for X views: {len(on_x)} of {len(known)} with known platforms")
        lines.append("  topics: " + ", ".join(f"{t} {n}" for t, n in Counter(r["topic"] for r in cur).most_common()))
        budgets = defaultdict(float)
        for r in cur:
            if r["budget_total_usd"]:
                budgets[r["buyer"]] += float(r["budget_total_usd"])
        if budgets:
            top = sorted(budgets.items(), key=lambda kv: -kv[1])[:5]
            lines.append("  biggest buyers by listed budget: " + ", ".join(f"{b} ${v:,.0f}" for b, v in top))
    return "\n".join(lines) if lines else "No snapshots yet."


def cmd_summary(args) -> int:
    print(summarize(Store(args.data).rows(), args.window_days))
    return 0


def cmd_tag_accounts(args) -> int:
    known = clipper_rule.campaign_hashtags(Store(args.data).rows())
    with open(args.input, newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    accounts = {}
    for r in rows:
        key = r.get("screen_name") or r.get("user_id")
        if not key:
            continue
        acc = accounts.setdefault(key, dict(r, texts=[]))
        if r.get("full_text"):
            acc["texts"].append(r["full_text"])
    out_cols = ["screen_name", "user_id", "paid_clipper_tier", "signals", "matched_campaign_tags", "rule_version"]
    counts = Counter()
    with open(args.out, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=out_cols)
        w.writeheader()
        for key, acc in accounts.items():
            t = clipper_rule.tag_account(acc, known)
            counts[t.tier] += 1
            w.writerow(
                {
                    "screen_name": acc.get("screen_name", ""),
                    "user_id": acc.get("user_id", ""),
                    "paid_clipper_tier": t.tier,
                    "signals": ";".join(t.signals),
                    "matched_campaign_tags": ";".join(t.matched_campaign_tags),
                    "rule_version": t.rule_version,
                }
            )
    print(f"{len(accounts)} accounts tagged -> {args.out}")
    for tier in ["paid_confirmed", "paid_likely", "clip_possible", "none"]:
        print(f"  {tier}: {counts[tier]}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="clip_monitor", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("sources", help="list marketplaces and access status").set_defaults(func=cmd_sources)

    pi = sub.add_parser("ingest", help="parse browser-saved pages")
    pi.add_argument("files", nargs="+")
    pi.add_argument("--source", required=True, choices=sorted(k for k, s in SOURCES.items() if s.collectable))
    pi.add_argument("--observed-at", help="ISO 8601 UTC time the page was saved (default: file modified time)")
    pi.add_argument("--url", help="page URL, if the saved file does not record it")
    pi.add_argument("--note", help="free-text note stored with the snapshot")
    pi.add_argument("--data", default=DEFAULT_DATA)
    pi.set_defaults(func=cmd_ingest)

    pf = sub.add_parser("fetch", help="fetch listings directly (only where permitted)")
    pf.add_argument("--source", required=True, choices=sorted(k for k, s in SOURCES.items() if s.collectable))
    pf.add_argument("--min-interval", type=float, default=10.0, help="seconds between requests per host")
    pf.add_argument("--data", default=DEFAULT_DATA)
    pf.set_defaults(func=cmd_fetch)

    ps = sub.add_parser("summary", help="summarize the latest snapshots")
    ps.add_argument("--window-days", type=float, default=7.0, help="how far back a campaign still counts as current")
    ps.add_argument("--data", default=DEFAULT_DATA)
    ps.set_defaults(func=cmd_summary)

    pt = sub.add_parser("tag-accounts", help="apply the paid-clipper rule to an account CSV")
    pt.add_argument("input")
    pt.add_argument("--out", required=True)
    pt.add_argument("--data", default=DEFAULT_DATA, help="snapshot data, for campaign hashtags")
    pt.set_defaults(func=cmd_tag_accounts)
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)
