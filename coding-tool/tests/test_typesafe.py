import pytest

from blindcode.ai import AICoderSetupError, PaidCallNotAllowed, run_ai_coder
from blindcode.ai.typesafe import TypeSafeCoder, build_questions
from blindcode.items import Item
from blindcode.store import CoderStore

ITEMS = [Item("u1", "you clown, the stunt is fine", "child"), Item("u2", "fair point", "parent")]


def answer(codebook, **over):
    out = {}
    for f in codebook.fields:
        if f.type == "binary":
            out[f.name] = {"type": "noul", "noul": 0.1}
        elif f.type == "categorical":
            out[f.name] = {"type": "choice", "choice": f.options[0], "confidence": 0.9,
                           "probabilities": {o: 0.0 for o in f.options}}
    out.update(over)
    return out


class Fake:
    def __init__(self, codebook, versions=("jev-1.13.0", "jev-1.13.0"), **over):
        self.codebook, self.versions, self.over, self.calls = codebook, list(versions), over, []

    def __call__(self, body):
        self.calls.append(body)
        return {"model": self.versions.pop(0), "answers": answer(self.codebook, **self.over),
                "usage": {"input_tokens": 900, "output_tokens": 40}}


def test_paid_gate(monkeypatch):
    monkeypatch.delenv("BLINDCODE_ALLOW_PAID", raising=False)
    with pytest.raises(PaidCallNotAllowed):
        TypeSafeCoder(allow_paid=True)


def test_questions_follow_codebook(codebook):
    qs = build_questions(codebook)
    assert qs["incivility"]["type"] == "noul" and "note" not in qs
    assert set(qs["stance"]["criteria"]) == set(codebook.field("stance").options)


def test_codes_and_pins_served_version(tmp_path, codebook):
    fake = Fake(codebook, incivility={"type": "noul", "noul": 0.97})
    stats = run_ai_coder(TypeSafeCoder(transport=fake), ITEMS, codebook, tmp_path)
    assert stats.coded == 2
    assert fake.calls[0]["state"]["reply"] == ITEMS[0].text and "thread_context" in fake.calls[0]["state"]
    rec = CoderStore(tmp_path, "ai-typesafe-jev-latest").latest()["u1"]
    assert rec["values"]["incivility"] == "1" and rec["values"]["slur"] == "0" and rec["values"]["note"] == ""
    assert rec["meta"]["served_model"] == "jev-1.13.0" and rec["meta"]["input_tokens"] == 900


def test_version_change_stops_run(tmp_path, codebook):
    fake = Fake(codebook, versions=("jev-1.13.0", "jev-1.14.0"))
    with pytest.raises(AICoderSetupError, match="changed mid-run"):
        run_ai_coder(TypeSafeCoder(transport=fake), ITEMS, codebook, tmp_path)


def test_bad_choice_fails_one_item(tmp_path, codebook):
    fake = Fake(codebook, stance={"type": "choice", "choice": "furious", "confidence": 1, "probabilities": {}})
    stats = run_ai_coder(TypeSafeCoder(transport=fake), ITEMS[:1], codebook, tmp_path)
    assert stats.failed == 1
