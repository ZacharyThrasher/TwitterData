import json
from types import SimpleNamespace

import pytest

from blindcode.ai import KeywordCoder, PaidCallNotAllowed, ReplayCoder, run_ai_coder
from blindcode.ai.anthropic_coder import AnthropicCoder, estimate_cost
from blindcode.ai.base import output_schema, prompt_sha256, system_prompt, user_prompt
from blindcode.items import Item
from blindcode.store import CoderStore

from .conftest import full_values

ITEMS = [Item("u1", "you absolute idiot", "child"), Item("u2", "fair point honestly", "parent")]


class FakeClient:
    def __init__(self, replies, served_model="claude-opus-5-5", stop_reason="end_turn"):
        self.replies = list(replies)
        self.calls = []
        self.served_model = served_model
        self.stop_reason = stop_reason
        self.messages = self

    def create(self, **kw):
        self.calls.append(kw)
        text = self.replies.pop(0)
        return SimpleNamespace(id="msg_1", model=self.served_model, stop_reason=self.stop_reason,
                               content=[SimpleNamespace(type="thinking", thinking=""), SimpleNamespace(type="text", text=text)],
                               usage=SimpleNamespace(input_tokens=900, output_tokens=120))


def test_paid_backend_refuses_without_explicit_permission(monkeypatch):
    monkeypatch.delenv("BLINDCODE_ALLOW_PAID", raising=False)
    with pytest.raises(PaidCallNotAllowed):
        AnthropicCoder()
    with pytest.raises(PaidCallNotAllowed):
        AnthropicCoder(allow_paid=True)  # env switch also required


def test_anthropic_request_is_pinned_and_schema_constrained(tmp_path, codebook):
    client = FakeClient([json.dumps(full_values(incivility="1", attacks_op="1", target="op")),
                         json.dumps(full_values())])
    stats = run_ai_coder(AnthropicCoder(client=client), ITEMS, codebook, tmp_path, coder_id="claude")
    assert (stats.coded, stats.failed) == (2, 0)
    kw = client.calls[0]
    assert kw["model"] == "claude-opus-5-5"
    assert kw["output_config"]["effort"] == "medium"
    assert kw["output_config"]["format"]["schema"] == output_schema(codebook)
    assert "temperature" not in kw and "fallbacks" not in kw
    assert kw["system"] == system_prompt(codebook)
    assert "<reply>\nyou absolute idiot\n</reply>" in kw["messages"][0]["content"]
    rec = CoderStore(tmp_path, "claude").latest()["u1"]
    assert rec["kind"] == "ai" and rec["values"]["attacks_op"] == "1"
    assert rec["meta"]["served_model"] == "claude-opus-5-5"
    assert rec["meta"]["prompt_sha256"] == prompt_sha256(codebook)
    assert json.loads(rec["meta"]["raw"])["target"] == "op"


@pytest.mark.parametrize("client_kw,reply,msg", [
    ({"stop_reason": "refusal"}, "{}", "refused"),
    ({"served_model": "claude-opus-4-8"}, json.dumps(full_values()), "differs from pinned"),
    ({}, "not json", "not JSON"),
    ({}, json.dumps(full_values(stance="furious")), "breaks the codebook"),
])
def test_bad_outputs_are_logged_not_stored(tmp_path, codebook, client_kw, reply, msg):
    client = FakeClient([reply], **client_kw)
    stats = run_ai_coder(AnthropicCoder(client=client), ITEMS[:1], codebook, tmp_path, coder_id="c")
    assert stats.failed == 1 and CoderStore(tmp_path, "c").latest() == {}
    assert msg in (tmp_path / "c.errors.log").read_text()


def test_run_skips_done_items_and_respects_limit(tmp_path, codebook):
    s1 = run_ai_coder(KeywordCoder(), ITEMS, codebook, tmp_path, limit=1)
    assert s1.coded == 1
    s2 = run_ai_coder(KeywordCoder(), ITEMS, codebook, tmp_path)
    assert (s2.coded, s2.skipped) == (1, 1)


def test_keyword_baseline_is_deterministic(codebook):
    r = KeywordCoder().code(ITEMS[0], codebook)
    assert r.values["incivility"] == "1" and r.values["attacks_op"] == "1"
    assert KeywordCoder().code(ITEMS[1], codebook).values["incivility"] == "0"


def test_replay_reproduces_a_paid_run_offline(tmp_path, codebook):
    client = FakeClient([json.dumps(full_values(slur="1", incivility="1")), json.dumps(full_values())])
    run_ai_coder(AnthropicCoder(client=client), ITEMS, codebook, tmp_path, coder_id="claude")
    run_ai_coder(ReplayCoder(tmp_path, "claude"), ITEMS, codebook, tmp_path, coder_id="claude-replay")
    a = CoderStore(tmp_path, "claude").latest()
    b = CoderStore(tmp_path, "claude-replay").latest()
    assert {u: r["values"] for u, r in a.items()} == {u: r["values"] for u, r in b.items()}
    assert b["u1"]["meta"]["model"] == "claude-opus-5-5" and b["u1"]["meta"]["replayed"]


def test_prompt_contains_codebook_and_context(codebook):
    sp = system_prompt(codebook)
    for name in codebook.names:
        assert name in sp
    assert "BECAUSE OF a protected characteristic" in sp
    assert "DirtbagLeft1234" in user_prompt(ITEMS[0], codebook)


def test_cost_estimate(codebook):
    assert 0 < estimate_cost(545, codebook) < 50
    assert estimate_cost(10, codebook, "unknown-model") is None
