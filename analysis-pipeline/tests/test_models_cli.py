import json

import numpy as np
import pandas as pd
import pytest

from replyanalysis import exposure
from replyanalysis.cli import main
from replyanalysis.models import NotEstimable, holm, mixed_lm, rank_ordered_logit


def test_holm_matches_hand_calculation():
    out = holm({"a": 0.01, "b": 0.04, "c": 0.03, "d": None})
    assert out == {"a": 0.03, "b": 0.06, "c": 0.06, "d": None}


def test_rank_ordered_logit_recovers_plackett_luce_coefficient():
    rng = np.random.default_rng(0)
    rows = []
    for s in range(150):
        x = rng.normal(size=12)
        g = rng.gumbel(size=12)
        order = np.argsort(-(1.0 * x + g))  # Plackett-Luce with beta = 1
        for rank, i in enumerate(order, 1):
            rows.append({"cap": s, "thread": s // 3, "rank": rank, "x": x[i]})
    est = rank_ordered_logit(pd.DataFrame(rows), "cap", "rank", ["x"], "thread", "x")
    assert est.ci_low < 1.0 < est.ci_high


def test_mixed_lm_refuses_tiny_data():
    with pytest.raises(NotEstimable):
        mixed_lm(pd.DataFrame({"y": [1.0, 2.0], "x": [0.0, 1.0], "g": ["a", "b"]}), "y ~ x", "g", "x")


def test_exposure_ratio_by_hand():
    df = pd.DataFrame({
        "study_thread_id": ["t"] * 4 + ["u"] * 4,
        "premium": [1, 0, 0, 0, 1, 1, 0, 0],
        "view_count": [50, 25, 15, 10, 30, 30, 20, 20],
    })
    table = exposure.per_thread_ratios(df, "premium").set_index("study_thread_id")
    assert table.loc["t", "ratio"] == pytest.approx(0.5 / 0.25)
    assert table.loc["u", "ratio"] == pytest.approx(0.6 / 0.5)


def test_run_refuses_before_collection_stops(tmp_path, capsys):
    assert main(["run", str(tmp_path), "-o", str(tmp_path / "out")]) == 2
    assert "pre-registration" in capsys.readouterr().err


def test_demo_writes_report_without_reply_text(tmp_path):
    out = tmp_path / "demo"
    assert main(["demo", "-o", str(out), "--threads-n", "12", "--bootstrap", "100", "--pod-permutations", "20"]) == 0
    report = (out / "report.md").read_text()
    assert "## Confirmatory tests" in report and "| T1 |" in report
    assert "Exploratory only" in report  # 12 threads is below the pre-registered minimum
    results = json.loads((out / "results.json").read_text())
    assert [t["id"] for t in results["confirmatory"]] == ["T1", "T2", "T3", "T9", "T10", "O1", "O2"]
    assert "text" not in pd.read_csv(out / "threads.csv").columns


def test_exposure_without_views_returns_nan_not_crash():
    df = pd.DataFrame({"study_thread_id": ["t", "t"], "premium": [1, 0], "view_count": [None, None]})
    out = exposure.summarize(df, "premium", n_boot=50)
    assert out["threads_with_ratio"] == 0 and np.isnan(out["median_ratio"])
