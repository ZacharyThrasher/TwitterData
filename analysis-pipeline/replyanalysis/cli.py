"""Command line: `python -m replyanalysis run ...` and `python -m replyanalysis demo ...`."""

from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

from .pipeline import run, write_results
from .prepare import AnalysisConfig, load_inputs
from .synthetic import Effects, generate, null_effects, write_dataset

NO_PEEKING = (
    "Refusing to run outcome models: pre-registration section 6 forbids outcome analysis before collection stops.\n"
    "When `sampling/tracker.py status` prints STOP (or the 56-day limit has passed), rerun with --collection-stopped.\n"
    "To try the pipeline without real outcomes, use `python -m replyanalysis demo`."
)


def _config_args(p: argparse.ArgumentParser) -> None:
    g = p.add_argument_group("analysis settings (defaults follow docs/preregistration.md)")
    g.add_argument("--platform", default="x", choices=["x", "bluesky"],
                   help="platform to analyse; the other platform's rows are set aside (default x)")
    g.add_argument("--main-sort", default="relevance", choices=["relevance", "recent", "likes"])
    g.add_argument("--main-age", default="h06")
    g.add_argument("--viewer", default="A", help="viewer_label to analyse; 'all' keeps every viewer")
    g.add_argument("--incivility-col", default="incivility")
    g.add_argument("--toxicity-col", default="toxicity")
    g.add_argument("--stance-col", default="stance")
    g.add_argument("--include-late", action="store_true", help="sensitivity run including captures marked late")
    g.add_argument("--bootstrap", type=int, default=2000)
    g.add_argument("--pod-permutations", type=int, default=200)
    g.add_argument("--seed", type=int, default=20261021)


def _config(a: argparse.Namespace) -> AnalysisConfig:
    return AnalysisConfig(platform=a.platform, main_sort=a.main_sort, main_age=a.main_age, viewer=None if a.viewer == "all" else a.viewer,
                          incivility_col=a.incivility_col, toxicity_col=a.toxicity_col, stance_col=a.stance_col,
                          include_late=a.include_late, bootstrap=a.bootstrap, pod_permutations=a.pod_permutations,
                          seed=a.seed)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="replyanalysis", description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="analyse parser outputs")
    r.add_argument("replies", nargs="+", help="reply table files (.csv/.jsonl) or folders of them")
    r.add_argument("--codes", help="reply codes CSV, or a blindcode JSONL file (latest record per uid)")
    r.add_argument("--codes-key", help="join column in the codes file (default tweet_id, else uid)")
    r.add_argument("--threads", help="sampling tracker threads.csv")
    r.add_argument("--root-codes", help="root post codes CSV (thread_id, outrage_framing, targeted_insult)")
    r.add_argument("--authors", help="author codes CSV keyed by author_id_hash")
    r.add_argument("--captures", help="sampling tracker captures.csv (sets aside late captures)")
    r.add_argument("-o", "--out", required=True, help="results folder")
    r.add_argument("--collection-stopped", action="store_true",
                   help="confirm the pre-registered stop rule has been met")
    _config_args(r)

    d = sub.add_parser("demo", help="generate synthetic data with known effects and analyse it")
    d.add_argument("-o", "--out", required=True)
    d.add_argument("--threads-n", type=int, default=40)
    d.add_argument("--null", action="store_true", help="generate a world with no effects")
    _config_args(d)

    a = ap.parse_args(argv)
    cfg = _config(a)
    if a.cmd == "run":
        if not a.collection_stopped:
            print(NO_PEEKING, file=sys.stderr)
            return 2
        inp = load_inputs(a.replies, a.codes, a.codes_key, a.threads, a.root_codes, a.authors, a.captures)
    else:
        fx = null_effects() if a.null else Effects()
        data_dir = Path(a.out) / "synthetic_input"
        paths = write_dataset(data_dir, generate(a.threads_n, a.seed, fx), overwrite=True)
        inp = load_inputs([paths["captures_dir"]], paths["codes"], None, paths["threads"], paths["root_codes"],
                          paths["authors"], paths["captures"])
    results = run(inp, cfg)
    out = write_results(results, a.out)
    print(f"wrote {out['report']}")
    for t in results["confirmatory"]:
        print(f"  {t['id']:>3}  {t['status']}")
    return 0
