"""Run everything and write the results folder."""

from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from . import __version__, confirmatory, exploratory
from .prepare import AnalysisConfig, Inputs, annotate, main_frame, select_sessions, thread_frame
from .report import render_markdown


def run(inp: Inputs, cfg: AnalysisConfig) -> dict:
    rows = annotate(inp, cfg)
    sessions, session_info = select_sessions(rows, inp, cfg)
    main = main_frame(sessions, cfg)
    threads = thread_frame(sessions, inp, cfg)
    tests = confirmatory.run_all(main, sessions, threads, cfg)
    explore = exploratory.run_all(sessions, main, threads, cfg)
    n_threads = int(main["study_thread_id"].nunique())
    return {
        "meta": {
            "pipeline_version": __version__,
            "run_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "config": cfg.to_dict(),
            "sessions": session_info,
            "notes": inp.notes,
            "main_frame": f"{cfg.main_sort} sort, {cfg.main_age} captures, top-level organic replies",
            "threads_in_main_frame": n_threads,
            "below_confirmatory_minimum": n_threads < cfg.min_confirmatory_threads,
            "min_confirmatory_threads": cfg.min_confirmatory_threads,
        },
        "confirmatory": [t.to_dict() for t in tests],
        "exploratory": explore,
        "_frames": {"main": main, "threads": threads, "stimuli": exploratory.a5_stimuli(main)},
    }


def _clean_json(obj):
    if isinstance(obj, dict):
        return {str(k): _clean_json(v) for k, v in obj.items() if not isinstance(v, pd.DataFrame)}
    if isinstance(obj, (list, tuple)):
        return [_clean_json(v) for v in obj]
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating, float)):
        return None if not math.isfinite(float(obj)) else float(obj)
    if isinstance(obj, (np.bool_,)):
        return bool(obj)
    if isinstance(obj, pd.Timestamp):
        return obj.isoformat()
    if obj is pd.NA:
        return None
    return obj


def write_results(results: dict, out_dir: str | Path) -> dict[str, Path]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    payload = {k: v for k, v in results.items() if k != "_frames"}
    paths = {
        "json": out / "results.json",
        "report": out / "report.md",
        "thread_table": out / "threads.csv",
        "stimuli": out / "a5_stimuli.csv",
    }
    paths["json"].write_text(json.dumps(_clean_json(payload), indent=2), encoding="utf-8")
    paths["report"].write_text(render_markdown(_clean_json(payload)), encoding="utf-8")
    frames = results["_frames"]
    # Only ids and model variables leave the pipeline; no reply text.
    frames["threads"].to_csv(paths["thread_table"], index=False)
    frames["stimuli"].to_csv(paths["stimuli"], index=False)
    return paths
