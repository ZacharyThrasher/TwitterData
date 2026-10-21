"""`python -m twitterdata bluesky collect|parse ...`."""

from __future__ import annotations

import argparse
import csv
import os
import sys
from datetime import datetime, timezone

from twitterdata.bluesky.bundle import load_bundle, save_bundle
from twitterdata.bluesky.client import PUBLIC_APPVIEW, BlueskyError, Client
from twitterdata.bluesky.collector import MAX_BELOW, MAX_BRANCHING, Collector
from twitterdata.bluesky.mapping import EXTRA_COLUMNS, SORTS, build_rows
from twitterdata.output import WRITERS, _csv_cell
from twitterdata.privacy import DEFAULT_SALT_FILE, SALT_ENV, load_salt

DEFAULT_RAW_DIR = os.path.join("data", "raw", "bluesky")


def add_parser(sub) -> None:
    bs = sub.add_parser("bluesky", help="Bluesky comparison collector (free public API, no login).")
    bsub = bs.add_subparsers(dest="bluesky_command", required=True)

    def common(p):
        p.add_argument("-o", "--output", required=True, help="Reply table output (.csv or .jsonl).")
        p.add_argument("--format", choices=sorted(WRITERS), help="Output format; default from the output extension.")
        p.add_argument("--extras", help="Bluesky-only fields sidecar CSV. Default: <output>.bluesky_extras.csv. "
                                        "Pass 'none' to skip.")
        p.add_argument("--include-text", action="store_true", help="Fill the text column (off by default).")
        p.add_argument("--capture-id", help="Capture id (single capture only).")
        p.add_argument("--salt-file", default=DEFAULT_SALT_FILE,
                       help=f"Hash salt file, created if missing. {SALT_ENV} overrides it. Default: %(default)s")

    c = bsub.add_parser("collect", help="Fetch threads from the public AppView and write the reply table.")
    c.add_argument("targets", nargs="*", help="bsky.app post URLs or at:// post URIs.")
    c.add_argument("--from-file", help="Text file with one URL or URI per line (# comments allowed).")
    c.add_argument("--sort", action="append", choices=sorted(SORTS),
                   help="Reply sort; repeat for several (one capture each). relevance = Bluesky 'top' "
                        "(the app default), recent = Bluesky 'newest'. Default: relevance.")
    c.add_argument("--age-bucket", help="Thread age bucket at capture, for example h06.")
    c.add_argument("--viewer-label", help="Free-text persona label stored on every row.")
    c.add_argument("--raw-dir", default=DEFAULT_RAW_DIR, help="Where raw capture bundles go (git-ignored). "
                                                             "Default: %(default)s")
    c.add_argument("--no-other", action="store_true", help="Skip the hidden 'other replies' fold.")
    c.add_argument("--no-profiles", action="store_true",
                   help="Skip author profile lookups (follower, following and post counts stay empty).")
    c.add_argument("--below", type=int, default=MAX_BELOW, help="Reply depth to fetch (1-%(default)s).")
    c.add_argument("--branching", type=int, default=MAX_BRANCHING,
                   help="Nested replies per post to fetch (1-%(default)s).")
    c.add_argument("--min-interval", type=float, default=1.0,
                   help="Seconds between requests (default %(default)s; never below 0.2).")
    c.add_argument("--appview", default=PUBLIC_APPVIEW, help=argparse.SUPPRESS)
    common(c)

    p = bsub.add_parser("parse", help="Rebuild the reply table from saved capture bundles (offline).")
    p.add_argument("bundles", nargs="+", help="Bundle .json files written by `bluesky collect`.")
    common(p)


def _extras_path(args, out: str) -> str | None:
    if args.extras and args.extras.lower() == "none":
        return None
    if args.extras:
        return args.extras
    stem = out[: -len(os.path.splitext(out)[1])] if os.path.splitext(out)[1] else out
    return stem + ".bluesky_extras.csv"


def _write_extras(extras: list[dict], path: str) -> None:
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(EXTRA_COLUMNS)
        for e in extras:
            w.writerow([_csv_cell(e.get(k)) for k in EXTRA_COLUMNS])


def _report(name: str, stats: dict) -> None:
    print(f"{name}: {stats['rows']} rows ({stats['top_level']} top-level, {stats['other_items']} from the hidden "
          f"fold), {stats['unavailable']} unavailable items; Bluesky counts {stats['focal_reply_count']} replies "
          f"at all depths", file=sys.stderr)
    if stats["has_other_replies"] and not stats["other_fetched"]:
        print(f"{name}: note: thread has a hidden 'other replies' fold that was not fetched", file=sys.stderr)
    if stats["redacted_cells"]:
        print(f"warning: {stats['redacted_cells']} secret-shaped cells redacted", file=sys.stderr)


def _finish(args, rows, extras) -> int:
    out = os.path.abspath(args.output)
    fmt = args.format or ("jsonl" if out.lower().endswith((".jsonl", ".ndjson")) else "csv")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    WRITERS[fmt](rows, out)
    print(f"wrote {len(rows)} rows to {args.output}", file=sys.stderr)
    extras_path = _extras_path(args, args.output)
    if extras_path:
        _write_extras(extras, extras_path)
        print(f"wrote Bluesky-only fields to {extras_path}", file=sys.stderr)
    return 0


def _salt(args) -> bytes | None:
    try:
        return load_salt(args.salt_file)
    except (OSError, ValueError) as e:
        print(f"error: could not load the hash salt: {e}", file=sys.stderr)
        return None


def _unused_path(directory: str, stem: str) -> str:
    path, n = os.path.join(directory, f"{stem}.json"), 1
    while os.path.exists(path):
        n += 1
        path = os.path.join(directory, f"{stem}-{n}.json")
    return path


def _targets(args) -> list[str]:
    targets = list(args.targets)
    if args.from_file:
        with open(args.from_file, "r", encoding="utf-8") as f:
            targets += [ln.strip() for ln in f if ln.strip() and not ln.lstrip().startswith("#")]
    return targets


def _cmd_collect(args) -> int:
    targets, sorts = _targets(args), args.sort or ["relevance"]
    if not targets:
        print("no targets given", file=sys.stderr)
        return 2
    if args.capture_id and len(targets) * len(sorts) > 1:
        print("--capture-id applies to one capture; drop it to get bsky_{rkey}_{sort} ids", file=sys.stderr)
        return 2
    salt = _salt(args)
    if salt is None:
        return 2
    client = Client(base_url=args.appview, min_interval=max(args.min_interval, 0.2))
    collector = Collector(client, below=args.below, branching=args.branching,
                          include_other=not args.no_other, include_profiles=not args.no_profiles)
    rows, extras, failures = [], [], 0
    for target in targets:
        for sort_order in sorts:
            try:
                bundle = collector.collect(target, sort_order, args.age_bucket, args.viewer_label, args.capture_id)
            except (BlueskyError, ValueError, KeyError) as e:
                print(f"error: {target} ({sort_order}): {e}", file=sys.stderr)
                failures += 1
                continue
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            try:
                path = _unused_path(args.raw_dir, f"{bundle.capture_id}_{stamp}")
                save_bundle(bundle, path)
                result = build_rows(bundle, salt, os.path.basename(path), include_text=args.include_text)
            except (ValueError, KeyError, OSError) as e:
                print(f"error: {target} ({sort_order}): {e}", file=sys.stderr)
                failures += 1
                continue
            _report(bundle.capture_id, result.stats)
            rows += result.rows
            extras += result.extras
    print(f"{client.requests} API requests", file=sys.stderr)
    if not rows and failures:
        print(f"nothing collected; left {args.output} untouched", file=sys.stderr)
        return 1
    _finish(args, rows, extras)
    return 1 if failures else 0


def _cmd_parse(args) -> int:
    if args.capture_id and len(args.bundles) > 1:
        print("--capture-id applies to one bundle", file=sys.stderr)
        return 2
    written = {os.path.abspath(p) for p in (args.output, _extras_path(args, args.output)) if p}
    if written & {os.path.abspath(b) for b in args.bundles}:
        print("refusing to write output over a bundle file", file=sys.stderr)
        return 2
    salt = _salt(args)
    if salt is None:
        return 2
    rows, extras = [], []
    for path in args.bundles:
        try:
            result = build_rows(load_bundle(path), salt, os.path.basename(path),
                                include_text=args.include_text, capture_id=args.capture_id)
        except (ValueError, KeyError, OSError) as e:
            print(f"error: {path}: {e}", file=sys.stderr)
            return 1
        _report(os.path.basename(path), result.stats)
        rows += result.rows
        extras += result.extras
    return _finish(args, rows, extras)


def run(args) -> int:
    return _cmd_collect(args) if args.bluesky_command == "collect" else _cmd_parse(args)
