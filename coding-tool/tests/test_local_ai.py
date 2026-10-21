import json

import pytest

from blindcode.ai import AICoderSetupError, run_ai_coder
from blindcode.ai.base import output_schema
from blindcode.ai.local import CardiffCoder, DetoxifyCoder, OllamaCoder
from blindcode.items import Item
from blindcode.report import build_report
from blindcode.store import CoderStore

from .conftest import full_values

ITEMS = [Item("u1", "you absolute idiot", "child"), Item("u2", "fair point honestly", "parent")]
DIGEST = "sha256:abc123def456"


class FakeOllama:
    def __init__(self, replies, models=("llama3.1:8b",)):
        self.replies = list(replies)
        self.models = models
        self.calls = []

    def __call__(self, path, body):
        self.calls.append((path, body))
        if path == "/api/tags":
            return {"models": [{"name": m, "model": m, "digest": DIGEST} for m in self.models]}
        return {"message": {"role": "assistant", "content": self.replies.pop(0)}, "done_reason": "stop", "eval_count": 50}


def test_ollama_request_is_deterministic_and_pinned(tmp_path, codebook):
    fake = FakeOllama([json.dumps(full_values(incivility="1", attacks_op="1", target="op")), json.dumps(full_values())])
    stats = run_ai_coder(OllamaCoder(transport=fake), ITEMS, codebook, tmp_path)
    assert stats.coded == 2
    path, body = fake.calls[1]
    assert path == "/api/chat" and body["model"] == "llama3.1:8b" and body["stream"] is False
    assert body["options"] == {"temperature": 0, "seed": 42}
    assert body["format"] == output_schema(codebook)
    assert [c[0] for c in fake.calls].count("/api/tags") == 1  # digest looked up once per run
    rec = CoderStore(tmp_path, "ai-ollama").latest()["u1"]
    assert rec["meta"]["model_digest"] == DIGEST and rec["values"]["target"] == "op"


def test_ollama_missing_model_stops_the_run(tmp_path, codebook):
    with pytest.raises(AICoderSetupError, match="ollama pull"):
        run_ai_coder(OllamaCoder("qwen9:1b", transport=FakeOllama([])), ITEMS, codebook, tmp_path)
    assert not (tmp_path / "ai-ollama.errors.log").exists()


def test_ollama_digest_pin(tmp_path, codebook):
    coder = OllamaCoder(expected_digest="sha256:zzz", transport=FakeOllama([]))
    with pytest.raises(AICoderSetupError, match="differs"):
        coder.code(ITEMS[0], codebook)
    ok = OllamaCoder(expected_digest="sha256:abc1", transport=FakeOllama([json.dumps(full_values())]))
    assert ok.code(ITEMS[0], codebook).meta["model_digest"] == DIGEST


def test_ollama_unreachable_server_is_a_setup_error(codebook):
    coder = OllamaCoder(url="http://127.0.0.1:9")
    with pytest.raises(AICoderSetupError, match="ollama serve"):
        coder.code(ITEMS[0], codebook)


class FakeDetox:
    def predict(self, text):
        bad = "idiot" in text
        return {"toxicity": 0.9 if bad else 0.1, "insult": 0.8 if bad else 0.0, "threat": 0.01, "identity_attack": 0.02}


def test_detoxify_fills_only_mapped_fields(tmp_path, codebook):
    run_ai_coder(DetoxifyCoder(model=FakeDetox()), ITEMS, codebook, tmp_path)
    v = CoderStore(tmp_path, "ai-detoxify").latest()
    assert v["u1"]["values"]["incivility"] == "1" and v["u2"]["values"]["incivility"] == "0"
    assert v["u1"]["values"]["threat"] == "0" and v["u1"]["values"]["hate_speech"] == "0"
    assert v["u1"]["values"]["stance"] == ""  # not covered, left blank
    assert json.loads(v["u1"]["meta"]["raw"])["insult"] == 0.8


def test_cardiff_handles_both_output_shapes(codebook):
    pipes = {
        "incivility": lambda t: [[{"label": "offensive", "score": 0.7}, {"label": "non-offensive", "score": 0.3}]],
        "hate_speech": lambda t: [{"label": "HATE", "score": 0.2}, {"label": "NOT-HATE", "score": 0.8}],
    }
    r = CardiffCoder(pipelines=pipes).code(ITEMS[0], codebook)
    assert r.values["incivility"] == "1" and r.values["hate_speech"] == "0" and r.values["slur"] == ""


def test_report_treats_uncovered_fields_as_missing(tmp_path, codebook):
    for c, flip in (("A", False), ("B", False)):
        s = CoderStore(tmp_path, c)
        for i in range(20):
            s.save(f"u{i}", full_values(incivility=int(i % 2), stance="pro_stunt" if i % 3 else "anti_stunt"), codebook)
    d = CoderStore(tmp_path, "ai-detoxify")
    for i in range(20):
        d.save(f"u{i}", {"incivility": str(i % 2)}, codebook, kind="ai", partial=True)
    text, summaries = build_report(tmp_path, codebook, n_boot=0)
    by = {s.name: s for s in summaries}
    assert by["incivility"].ai_verdicts["ai-detoxify"] == "PASS"
    assert by["stance"].ai_verdicts["ai-detoxify"] == "N/A"
