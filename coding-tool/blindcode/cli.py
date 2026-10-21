"""Command line entry point: python -m blindcode <command> ..."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .codebook import Codebook
from .items import build_items, load_items
from .store import CoderStore, import_csv


def _codebook(args) -> Codebook:
    return Codebook.load(args.codebook)


def cmd_build_items(args) -> int:
    items, warnings = build_items(args.source, args.out, id_col=args.id_col, text_col=args.text_col,
                                  context_col=args.context_col or None, author_col=args.author_col or None,
                                  keep_mentions=args.keep_mentions)
    print(f"Wrote {len(items)} blind items to {args.out} (columns: uid, text, context).")
    for w in warnings:
        print(f"warning: {w}")
    return 0


def cmd_code(args) -> int:
    from .session import run_session
    run_session(load_items(args.items), _codebook(args), CoderStore(args.store, args.coder))
    return 0


def make_coder(args):
    """Build the AI coder named by --backend. Only `anthropic` can cost money."""
    from .ai import KeywordCoder, ReplayCoder
    from .ai.local import CardiffCoder, DetoxifyCoder, OllamaCoder
    if args.backend == "ollama":
        return OllamaCoder(args.ollama_model, url=args.ollama_url, expected_digest=args.digest)
    if args.backend == "detoxify":
        return DetoxifyCoder(threshold=args.threshold)
    if args.backend == "cardiff":
        return CardiffCoder(threshold=args.threshold)
    if args.backend == "keyword":
        return KeywordCoder()
    if args.backend == "replay":
        if not args.replay_from:
            raise SystemExit("--replay-from is required for the replay backend")
        return ReplayCoder(args.store, args.replay_from)
    from .ai.anthropic_coder import ALLOW_ENV, AnthropicCoder, estimate_cost
    n = len(args._items) if args.limit is None else min(args.limit, len(args._items))
    est = estimate_cost(n, _codebook(args), args.model)
    print(f"PAID backend. Model {args.model}, effort {args.effort}, {n} items. Estimated cost: "
          + (f"about ${est:.2f}" if est is not None else "unknown for this model"))
    if not args.allow_paid:
        print(f"Dry run only. Re-run with --allow-paid and {ALLOW_ENV}=1 once the spend is approved.")
        return None
    return AnthropicCoder(args.model, args.effort, allow_paid=True)


def _run_coder(args, items) -> int:
    from .ai import AICoderError, run_ai_coder
    args._items = items
    try:
        coder = make_coder(args)
    except AICoderError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    if coder is None:
        return 2
    try:
        stats = run_ai_coder(coder, items, _codebook(args), args.store, coder_id=args.coder, limit=args.limit,
                             recode=args.recode)
    except AICoderError as e:  # setup failures such as a missing local model
        print(f"error: {e}", file=sys.stderr)
        return 2
    print(f"coded {stats.coded}, skipped {stats.skipped} already done, failed {stats.failed}")
    return 0 if stats.failed == 0 else 1


def cmd_ai_code(args) -> int:
    return _run_coder(args, load_items(args.items))


def cmd_hatecheck(args) -> int:
    from .hatecheck import hatecheck_report, load_cases
    items, gold, func = load_cases(args.cases, limit_per_functionality=args.per_test)
    args.coder = args.coder or f"hatecheck-{args.backend}"
    rc = _run_coder(args, items)
    if rc == 2:
        return rc
    text = hatecheck_report(args.store, args.coder, gold, func)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
        print(f"Wrote {args.out}")
    else:
        print(text)
    return 0


def cmd_page(args) -> int:
    from .webpage import write_page
    out = write_page(load_items(args.items), _codebook(args), args.coder, args.out)
    print(f"Wrote {out}. Send this one file to coder {args.coder}; they open it in a browser and send back the CSV.")
    return 0


def cmd_sample(args) -> int:
    from .items import write_items
    from .sample import draw_sample
    from .store import CoderStore
    items = load_items(args.items)
    pre = None
    if args.enrich_coder:
        pre = {u: r["values"] for u, r in CoderStore(args.store, args.enrich_coder).latest().items()}
    exclude = set()
    for path in args.exclude or []:
        exclude |= {it.uid for it in load_items(path)}
    fields = [f for f in (args.enrich_fields or "").split(",") if f]
    out, rep = draw_sample(items, args.n, seed=args.seed, prelabels=pre, fields=fields,
                           min_per_field=args.min_per_field, exclude=exclude)
    write_items(out, args.out)
    print(f"Wrote {len(out)} items to {args.out}.")
    for f, r in rep.items():
        print(f"  {f}: {r['flagged']} flagged by {args.enrich_coder}, {r['taken']} oversampled")
    return 0


def cmd_import(args) -> int:
    n = import_csv(args.csv, args.store, args.coder, _codebook(args), kind=args.kind)
    print(f"Imported {n} rows as coder {args.coder} ({args.kind}).")
    return 0


def cmd_export(args) -> int:
    n = CoderStore(args.store, args.coder).export_csv(args.out, _codebook(args))
    print(f"Wrote {n} rows to {args.out}.")
    return 0


def cmd_report(args) -> int:
    from .report import build_report, load_groups
    groups = load_groups(args.groups, args.group_col) if args.groups else None
    split = lambda s: [x for x in s.split(",") if x] if s is not None else None
    text, summaries = build_report(args.store, _codebook(args), humans=split(args.humans), ais=split(args.ais),
                                   reference=args.reference, groups=groups, group_label=args.group_col,
                                   n_boot=args.n_boot)
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(text, encoding="utf-8")
        print(f"Wrote {args.out}")
    else:
        print(text)
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="blindcode", description="Blind reply coding: human coders, AI third coder, Krippendorff's alpha.")
    p.add_argument("--codebook", help="codebook JSON (default: built-in reply_v1)")
    sub = p.add_subparsers(dest="cmd", required=True)

    b = sub.add_parser("build-items", help="make a blind items CSV (uid, text, context only)")
    b.add_argument("source")
    b.add_argument("out")
    b.add_argument("--id-col", default="uid")
    b.add_argument("--text-col", default="full_text")
    b.add_argument("--context-col", default="thread")
    b.add_argument("--author-col", default="screen_name", help="used only to warn if a reply names its own author")
    b.add_argument("--keep-mentions", action="store_true", help="keep the leading @reply-to handles")
    b.set_defaults(fn=cmd_build_items)

    c = sub.add_parser("code", help="interactive coding session for one human coder")
    c.add_argument("items")
    c.add_argument("--coder", required=True)
    c.add_argument("--store", default="work/coders")
    c.set_defaults(fn=cmd_code)

    def ai_args(a, default_backend="ollama"):
        a.add_argument("--backend", choices=["ollama", "detoxify", "cardiff", "keyword", "replay", "anthropic"],
                       default=default_backend,
                       help="ollama/detoxify/cardiff run free on this machine; keyword is a test baseline; anthropic is PAID")
        a.add_argument("--coder", help="coder id to store under (default: backend name)")
        a.add_argument("--store", default="work/coders")
        a.add_argument("--limit", type=int)
        a.add_argument("--recode", action="store_true")
        a.add_argument("--ollama-model", default="llama3.1:8b")
        a.add_argument("--ollama-url", default="http://localhost:11434")
        a.add_argument("--digest", help="ollama: required model digest prefix (pin)")
        a.add_argument("--threshold", type=float, default=0.5, help="detoxify/cardiff score threshold")
        a.add_argument("--replay-from", help="replay backend: coder id whose saved raw outputs to replay")
        a.add_argument("--model", default="claude-opus-5-5", help="anthropic backend only")
        a.add_argument("--effort", default="medium", choices=["low", "medium", "high", "xhigh", "max"])
        a.add_argument("--allow-paid", action="store_true")

    a = sub.add_parser("ai-code", help="code items with an AI coder (default: free local LLM via Ollama)")
    a.add_argument("items")
    ai_args(a)
    a.set_defaults(fn=cmd_ai_code)

    h = sub.add_parser("hatecheck", help="validate an AI coder's hate_speech field on HateCheck")
    h.add_argument("cases", help="hatecheck_test_suite_cases.csv")
    h.add_argument("--per-test", type=int, help="cap cases per functional test (faster)")
    h.add_argument("--out")
    ai_args(h)
    h.set_defaults(fn=cmd_hatecheck, store="work/hatecheck")  # kept apart from study codes

    pg = sub.add_parser("page", help="make a single offline HTML coding page for one coder")
    pg.add_argument("items")
    pg.add_argument("--coder", required=True)
    pg.add_argument("--out", required=True)
    pg.set_defaults(fn=cmd_page)

    sm = sub.add_parser("sample", help="draw a pilot or gold-set sample, oversampling rare classes")
    sm.add_argument("items")
    sm.add_argument("out")
    sm.add_argument("--n", type=int, required=True)
    sm.add_argument("--seed", type=int, default=0)
    sm.add_argument("--store", default="work/coders")
    sm.add_argument("--enrich-coder", help="coder whose positive codes steer oversampling (e.g. ai-ollama)")
    sm.add_argument("--enrich-fields", default="hate_speech,threat,slur")
    sm.add_argument("--min-per-field", type=int, default=50)
    sm.add_argument("--exclude", action="append", help="items file whose uids to leave out (e.g. the pilot)")
    sm.set_defaults(fn=cmd_sample)

    i = sub.add_parser("import", help="load an existing flat coding CSV into the store")
    i.add_argument("csv")
    i.add_argument("--coder", required=True)
    i.add_argument("--kind", choices=["human", "ai"], default="human")
    i.add_argument("--store", default="work/coders")
    i.set_defaults(fn=cmd_import)

    e = sub.add_parser("export", help="write one coder's latest codes as CSV")
    e.add_argument("out")
    e.add_argument("--coder", required=True)
    e.add_argument("--store", default="work/coders")
    e.set_defaults(fn=cmd_export)

    r = sub.add_parser("report", help="Krippendorff's alpha report with pass rules")
    r.add_argument("--store", default="work/coders")
    r.add_argument("--humans", help="comma list (default: every human coder in the store)")
    r.add_argument("--ais", help="comma list (default: every AI coder in the store)")
    r.add_argument("--reference", help="coder id to score AI F1 against (default: human consensus)")
    r.add_argument("--groups", help="CSV with uid and a group column, for the bias check")
    r.add_argument("--group-col", default="group")
    r.add_argument("--n-boot", type=int, default=1000)
    r.add_argument("--out")
    r.set_defaults(fn=cmd_report)

    args = p.parse_args(argv)
    return args.fn(args)
