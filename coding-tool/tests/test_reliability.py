import random

import pytest

from blindcode import reliability as R

# Krippendorff (2011), "Computing Krippendorff's Alpha-Reliability", 4 observers x 12 units.
# Published nominal alpha = 0.743.
KRIPP = {
    "A": [1, 2, 3, 3, 2, 1, 4, 1, 2, None, None, None],
    "B": [1, 2, 3, 3, 2, 2, 4, 1, 2, 5, None, 3],
    "C": [None, 3, 3, 3, 2, 3, 4, 2, 2, 5, 1, None],
    "D": [1, 2, 3, 3, 2, 4, 4, 1, 2, 5, 1, None],
}


def as_codes(table):
    return {c: {f"u{i}": str(v) for i, v in enumerate(vals) if v is not None} for c, vals in table.items()}


def test_published_example():
    assert R.krippendorff_alpha(as_codes(KRIPP), list(KRIPP)) == pytest.approx(0.743, abs=5e-4)


def test_matches_reference_package_with_missing_data():
    kd = pytest.importorskip("krippendorff")
    import numpy as np
    rng = random.Random(3)
    for trial in range(20):
        n_coders, n_units, k = rng.randint(2, 4), rng.randint(10, 60), rng.randint(2, 5)
        table = {}
        truth = [rng.randrange(k) for _ in range(n_units)]
        for c in range(n_coders):
            row = []
            for t in truth:
                if rng.random() < 0.15:
                    row.append(None)
                else:
                    row.append(t if rng.random() < 0.75 else rng.randrange(k))
            table[f"c{c}"] = row
        mine = R.krippendorff_alpha(as_codes(table), list(table))
        arr = np.array([[np.nan if v is None else v for v in row] for row in table.values()], dtype=float)
        ref = kd.alpha(reliability_data=arr, level_of_measurement="nominal")
        assert mine == pytest.approx(ref, abs=1e-9), trial


def test_perfect_agreement_and_no_variation():
    codes = {"a": {"1": "x", "2": "y"}, "b": {"1": "x", "2": "y"}}
    assert R.krippendorff_alpha(codes, ["a", "b"]) == pytest.approx(1.0)
    flat = {"a": {"1": "0", "2": "0"}, "b": {"1": "0", "2": "0"}}
    assert R.krippendorff_alpha(flat, ["a", "b"]) is None


def test_units_with_one_value_are_ignored():
    codes = {"a": {"1": "x", "2": "y", "3": "x"}, "b": {"1": "x", "2": "y"}}
    assert R.alpha_with_ci(codes, ["a", "b"], n_boot=0).n_units == 2


def test_bootstrap_ci_brackets_point_estimate():
    codes = as_codes(KRIPP)
    r = R.alpha_with_ci(codes, list(KRIPP), n_boot=500, seed=1)
    assert r.ci_low <= r.alpha <= r.ci_high


def test_human_verdict_threshold():
    assert R.human_verdict(0.67) == "PASS"
    assert R.human_verdict(0.669) == "FAIL"
    assert R.human_verdict(None) == "N/A"


def test_ai_verdict_rule():
    assert R.ai_verdict([0.80, 0.76], 0.80) == "PASS"      # worst 0.76 >= 0.75
    assert R.ai_verdict([0.80, 0.74], 0.80) == "FAIL"      # worst 0.74 < 0.75
    assert R.ai_verdict([0.90, 0.90], 0.60) == "BLOCKED"   # humans have not passed
    assert R.ai_verdict([None], 0.80) == "N/A"


def test_consensus_and_f1():
    codes = {"a": {"1": "1", "2": "0", "3": "1", "4": "0"}, "b": {"1": "1", "2": "0", "3": "0", "4": "0"}}
    ref = R.consensus(codes, ["a", "b"])
    assert ref == {"1": "1", "2": "0", "4": "0"}
    pred = {"1": "1", "2": "1", "4": "0"}
    (s,) = R.per_class_f1(pred, ref, ["1"])
    assert (s.precision, s.recall, s.support) == (0.5, 1.0, 1)
    assert s.f1 == pytest.approx(2 / 3)
    (miss,) = R.per_class_f1({"1": "0", "2": "0", "4": "0"}, ref, ["1"])
    assert miss.f1 == 0.0
    assert R.confusion(pred, ref)[("0", "1")] == 1
