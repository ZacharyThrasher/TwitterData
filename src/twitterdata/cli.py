"""Command line entry point: `python -m twitterdata ...`."""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone

from twitterdata import schema
from twitterdata.capture.parser import CaptureMeta, parse_capture
from twitterdata.capture.safe_har import CaptureError
from twitterdata.output import WRITERS
from twitterdata.privacy import DEFAULT_SALT_FILE, SALT_ENV, load_salt

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCHEMA_DOC = os.path.join(REPO_ROOT, "docs", "reply_table_schema.md")
SCHEMA_JSON = os.path.join(REPO_ROOT, "schema", "reply_table.v1.json")
BEGIN, END = "<!-- BEGIN GENERATED COLUMNS -->", "<!-- END GENERATED COLUMNS -->"


def _utc(value: str) -> datetime:
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)).astimezone(timezone.utc)


def _build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="python -m twitterdata")
    sub = ap.add_subparsers(dest="command", required=True)

    p = sub.add_parser("parse", help="Parse X thread captures (.har or saved TweetDetail .json) into the reply table.")
    p.add_argument("captures", nargs="+", help="Capture files (.har, or a TweetDetail response saved as .json).")
    p.add_argument("-o", "--output", required=True, help="Output file (.csv or .jsonl).")
    p.add_argument("--format", choices=sorted(WRITERS), help="Output format; default from the output extension.")
    p.add_argument("--viewer-type", choices=schema.VIEWER_TYPES, default="unknown",
                   help="Account type of the person who captured the page.")
    p.add_argument("--viewer-label", help="Free-text persona label, for example A.")
    p.add_argument("--capture-id", help="Capture id (single input only). Defaults to the file name.")
    p.add_argument("--sort-order", choices=[s for s in schema.SORT_ORDERS if s != "unknown"],
                   help="Override the sort order read from the request.")
    p.add_argument("--age-bucket", help="Thread age bucket at capture, for example h06.")
    p.add_argument("--focal-tweet-id", help="Focal tweet id, for raw .json input that lacks the focal entry.")
    p.add_argument("--capture-time", type=_utc, help="Capture time (ISO 8601) for raw .json input.")
    p.add_argument("--include-text", action="store_true", help="Fill the text column (off by default).")
    p.add_argument("--salt-file", default=DEFAULT_SALT_FILE,
                   help=f"Hash salt file, created if missing. {SALT_ENV} overrides it. Default: %(default)s")

    s = sub.add_parser("schema", help="Print or regenerate the reply table schema files.")
    s.add_argument("--format", choices=["json", "markdown"], default="json")
    s.add_argument("--write", action="store_true", help="Rewrite docs/reply_table_schema.md and schema/reply_table.v1.json.")
    return ap


def render_doc(current: str) -> str:
    """Replace the generated column block in the schema doc."""
    start, end = current.index(BEGIN) + len(BEGIN), current.index(END)
    return current[:start] + "\n\n" + schema.markdown_columns() + "\n" + current[end:]


def _cmd_schema(args) -> int:
    if args.write:
        with open(SCHEMA_DOC, "r", encoding="utf-8") as f:
            doc = f.read()
        with open(SCHEMA_DOC, "w", encoding="utf-8") as f:
            f.write(render_doc(doc))
        with open(SCHEMA_JSON, "w", encoding="utf-8") as f:
            f.write(schema.json_schema_text())
        print(f"wrote {SCHEMA_DOC} and {SCHEMA_JSON}", file=sys.stderr)
        return 0
    sys.stdout.write(schema.json_schema_text() if args.format == "json" else schema.markdown_columns())
    return 0


def _cmd_parse(args) -> int:
    if args.capture_id and len(args.captures) > 1:
        print("--capture-id applies to one input; run once per capture", file=sys.stderr)
        return 2
    out = os.path.abspath(args.output)
    if out.lower().endswith(".har") or out in {os.path.abspath(c) for c in args.captures}:
        print("refusing to write output over a capture file", file=sys.stderr)
        return 2
    fmt = args.format or ("jsonl" if out.lower().endswith((".jsonl", ".ndjson")) else "csv")

    salt = load_salt(args.salt_file)
    rows = []
    for path in args.captures:
        meta = CaptureMeta(
            viewer_type=args.viewer_type, viewer_label=args.viewer_label, capture_id=args.capture_id,
            sort_order=args.sort_order, age_bucket=args.age_bucket, focal_tweet_id=args.focal_tweet_id,
            capture_time=args.capture_time, include_text=args.include_text,
        )
        try:
            result = parse_capture(path, meta, salt)
        except CaptureError as e:
            print(f"error: {e}", file=sys.stderr)
            return 1
        st = result.stats
        print(f"{os.path.basename(path)}: {st['tweetdetail']} TweetDetail responses, {st['sessions']} sessions, "
              f"{st['rows']} rows, {st['duplicates']} duplicates dropped, {st['unavailable']} unavailable tweets",
              file=sys.stderr)
        if st["redacted_cells"]:
            print(f"warning: {st['redacted_cells']} secret-shaped cells redacted", file=sys.stderr)
        if st["no_focal_id"]:
            print(f"warning: {st['no_focal_id']} pages skipped without a focal tweet id "
                  "(pass --focal-tweet-id)", file=sys.stderr)
        rows.extend(result.rows)

    WRITERS[fmt](rows, out)
    print(f"wrote {len(rows)} rows to {args.output}", file=sys.stderr)
    return 0


def main(argv=None) -> int:
    args = _build_parser().parse_args(argv)
    return _cmd_schema(args) if args.command == "schema" else _cmd_parse(args)
