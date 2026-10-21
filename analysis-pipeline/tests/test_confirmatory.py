from conftest import by_id


def test_reply_level_tests_pass_when_effects_are_planted(effect_world):
    _, results = effect_world
    t = by_id(results)
    for tid in ("T1", "T2", "T3", "T10"):
        assert t[tid]["status"] == "pass", (tid, t[tid])
    assert t["T1"]["primary"]["estimate"] > 0
    assert t["T2"]["primary"]["estimate"] < 0
    assert t["T3"]["primary"]["estimate"] < 0
    assert t["T10"]["primary"]["estimate"] > 0


def test_t1_carries_all_three_pieces(effect_world):
    _, results = effect_world
    t1 = by_id(results)["T1"]
    amp = t1["supporting"]["amplification"]
    assert amp["median_ratio"] > 1.5 and amp["median_ratio_ci"][0] > 1
    assert t1["supporting"]["likes_contrast"]["ci_low"] > 0
    assert t1["supporting"]["rank_ordered_logit"]["estimate"] > 0
    assert t1["meets_sesoi"] is True


def test_poster_level_effects_point_the_right_way(effect_world):
    _, results = effect_world
    t = by_id(results)
    assert t["O1"]["primary"]["estimate"] > 0
    assert t["T9"]["primary"]["estimate"] > 0
    assert t["O2"]["primary"]["estimate"] > 1


def test_nothing_passes_in_a_null_world(null_world):
    _, results = null_world
    for t in results["confirmatory"]:
        assert t["status"] != "pass", t


def test_holm_is_applied_across_the_family(effect_world):
    _, results = effect_world
    for t in results["confirmatory"]:
        if t["p_for_family"] is not None:
            assert t["p_holm"] >= t["p_for_family"]


def test_secondary_toxicity_models_run(effect_world):
    _, results = effect_world
    t2 = by_id(results)["T2"]
    assert t2["supporting"]["toxicity_score"]["estimate"] < 0
