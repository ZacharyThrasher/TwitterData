import numpy as np
import pandas as pd

from replyanalysis import exploratory
from replyanalysis.prepare import AnalysisConfig
from replyanalysis.synthetic import _hash


def test_a7_finds_exactly_the_planted_pod(effect_world):
    _, results = effect_world
    a7 = results["exploratory"]["A7"]
    pod = sorted(_hash("pod", 0, k) for k in range(5))
    assert a7["pods"] == [pod]


def test_a7_finds_no_pod_in_null_world(null_world):
    _, results = null_world
    assert results["exploratory"]["A7"]["pods"] == []


def test_a3_and_a4_recover_signs(effect_world):
    _, results = effect_world
    ex = results["exploratory"]
    assert ex["A3"]["estimate"]["ci_low"] > 0
    assert ex["A4"]["estimate"]["ci_high"] < 0


def test_stubs_say_what_they_need(effect_world):
    _, results = effect_world
    ex = results["exploratory"]
    assert ex["A5"]["status"] == "stub" and "participants" in ex["A5"]["reason"]
    assert ex["A8"]["status"] == "stub" and "historical" in ex["A8"]["reason"]


def test_a1_a6_a9_run(effect_world):
    _, results = effect_world
    ex = results["exploratory"]
    assert {s["stance"] for s in ex["A1"]["by_stance"]} == {"pro", "anti", "neutral"}
    assert ex["A6"]["status"] == "ran" and 0 < ex["A6"]["mismatch_rate"] < 1
    assert ex["A9"]["status"] == "ran" and ex["A9"]["posters"]


def test_a5_stimuli_hold_both_orders(effect_world):
    _, results = effect_world
    stim = results["_frames"]["stimuli"]
    assert set(stim["condition"]) == {"as_shown", "chronological"}
    row = stim.iloc[0]
    other = stim[(stim.session_key == row.session_key) & (stim.condition != row.condition)].iloc[0]
    assert sorted(row.tweet_ids.split()) == sorted(other.tweet_ids.split())


def test_a8_runs_on_historical_series():
    rng = np.random.default_rng(3)
    days = pd.date_range("2025-11-01", "2026-03-01", freq="6h", tz="UTC")
    post = days >= pd.Timestamp("2026-01-17", tz="UTC")
    d = pd.DataFrame({
        "row_type": "reply", "study_thread_id": "t", "tweet_id": [str(i) for i in range(len(days))],
        "created_at_utc": days, "premium": (rng.random(len(days)) < np.where(post, 0.1, 0.4)).astype(float),
        "incivility": (rng.random(len(days)) < 0.3).astype(float),
    })
    out = exploratory.a8_regime_break(d, AnalysisConfig())
    assert out["status"] == "ran"
    s = out["series"]["premium_share"]
    assert s["ci_pp"][1] < 0  # Premium share fell at the break


def test_near_duplicates_need_text(null_world, effect_world):
    assert null_world[1]["exploratory"]["near_duplicates"]["status"] == "not run"
    assert effect_world[1]["exploratory"]["near_duplicates"]["status"] == "ran"


def test_a6_matches_whole_words_only():
    d = pd.DataFrame({"author_id_hash": list("abcd"), "premium": [0, 0, 1, 1],
                      "account_based_in": ["us", "nigeria", "united states", "india"],
                      "claimed_location": ["russia", "niger", "texas, united states", "india"]})
    out = exploratory.a6_location_mismatch(d, AnalysisConfig())
    assert out["mismatch_rate"] == 0.5  # us/russia and nigeria/niger differ; the other two match


def test_t1_cannot_pass_without_likes_captures(effect_world):
    from replyanalysis import confirmatory
    from replyanalysis.prepare import annotate, load_inputs, main_frame, select_sessions
    paths, _ = effect_world
    inp = load_inputs([paths["captures_dir"]])
    cfg = AnalysisConfig(bootstrap=100)
    s, _ = select_sessions(annotate(inp, cfg), inp, cfg)
    s = s[s.sort_order != "likes"]
    r = confirmatory.test_t1(main_frame(s, cfg), s, cfg)
    assert r.direction_ok is False and any("Likes" in n for n in r.notes)
