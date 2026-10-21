from blindcode.items import Item
from blindcode.session import run_session
from blindcode.store import CoderStore

ANSWERS_CIVIL = ["1", "0", "0", "1", "0", "0", "0", "0", "13", ""]  # pro_stunt ... other, blank note


def scripted(lines):
    it = iter(lines)
    return lambda prompt: next(it)


def test_codes_items_and_shows_only_text(tmp_path, codebook):
    items = [Item("u1", "some reply", "parent")]
    out = []
    store = CoderStore(tmp_path, "A")
    counts = run_session(items, codebook, store, ask=scripted(ANSWERS_CIVIL + [""]), say=out.append)
    assert counts["saved"] == 1
    v = store.latest()["u1"]["values"]
    assert v["stance"] == "pro_stunt" and v["argument_tag"] == "other" and v["incivility"] == "0"
    shown = "\n".join(out)
    assert "some reply" in shown and "Asmongold" in shown  # text and thread context
    assert "u1" not in shown  # not even the uid, which encodes thread position


def test_invalid_input_help_back_and_redo(tmp_path, codebook):
    items = [Item("u1", "x", "child")]
    store = CoderStore(tmp_path, "A")
    lines = ["9", "?", "2", "b", "3", "maybe", "1"] + ANSWERS_CIVIL[2:] + ["r"] + ANSWERS_CIVIL + [""]
    out = []
    run_session(items, codebook, store, ask=scripted(lines), say=out.append)
    assert any("Not valid" in s for s in out)
    assert any(s.strip().startswith("stance:") for s in out)
    assert store.latest()["u1"]["values"]["stance"] == "pro_stunt"  # the redo wins
    assert len(store.records()) == 1


def test_skip_quit_and_resume(tmp_path, codebook):
    items = [Item(f"u{i}", f"t{i}", "parent") for i in range(3)]
    store = CoderStore(tmp_path, "A")
    c = run_session(items, codebook, store, ask=scripted(["s"] + ANSWERS_CIVIL + ["", "q"]), say=lambda s: None)
    assert (c["saved"], c["skipped"]) == (1, 1)
    c2 = run_session(items, codebook, store, ask=scripted(["q"]), say=lambda s: None)
    assert c2["remaining"] == 2
