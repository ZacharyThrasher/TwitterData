"""Free AI coders that run on your own machine.

OllamaCoder: an open-weights LLM served by Ollama (https://ollama.com) applies
the full codebook. Temperature 0 and a fixed seed are set, and the model's
content digest is recorded and checked, so the model cannot change mid-run.

DetoxifyCoder: the Detoxify toxicity classifiers. Fast, but they only cover
some fields (incivility, threat, and a loose identity-attack proxy for
hate_speech); the rest are left blank and the report treats them as missing.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Callable

from ..codebook import Codebook
from ..items import Item
from .base import AICoderError, AICoderSetupError, AIResult, output_schema, parse_output, system_prompt, user_prompt

DEFAULT_OLLAMA_MODEL = "llama3.1:8b"
DEFAULT_OLLAMA_URL = "http://localhost:11434"

Transport = Callable[[str, dict | None], dict]


def _http(base_url: str) -> Transport:
    def call(path: str, body: dict | None) -> dict:
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(base_url.rstrip("/") + path, data=data,
                                     headers={"Content-Type": "application/json"}, method="POST" if data else "GET")
        try:
            with urllib.request.urlopen(req, timeout=600) as resp:
                return json.loads(resp.read())
        except urllib.error.URLError as e:
            raise AICoderSetupError(f"cannot reach Ollama at {base_url} ({e}). Is `ollama serve` running?") from e
    return call


class OllamaCoder:
    def __init__(self, model: str = DEFAULT_OLLAMA_MODEL, *, url: str = DEFAULT_OLLAMA_URL, seed: int = 42,
                 expected_digest: str | None = None, transport: Transport | None = None):
        self.model = model
        self.seed = seed
        self.expected_digest = expected_digest
        self.name = "ai-ollama"
        self._call = transport or _http(url)
        self._digest: str | None = None

    def digest(self) -> str:
        """Content digest of the local model; fails if it is missing or differs from the expected one."""
        if self._digest is None:
            tags = self._call("/api/tags", None).get("models", [])
            match = [m for m in tags if m.get("name") == self.model or m.get("model") == self.model]
            if not match:
                raise AICoderSetupError(f"model {self.model!r} is not pulled. Run: ollama pull {self.model}")
            self._digest = match[0].get("digest", "")
            if self.expected_digest and not self._digest.startswith(self.expected_digest):
                raise AICoderSetupError(f"model digest {self._digest[:12]} differs from expected {self.expected_digest[:12]}")
        return self._digest

    def code(self, item: Item, codebook: Codebook) -> AIResult:
        digest = self.digest()
        resp = self._call("/api/chat", {
            "model": self.model,
            "stream": False,
            "format": output_schema(codebook),
            "options": {"temperature": 0, "seed": self.seed},
            "messages": [{"role": "system", "content": system_prompt(codebook)},
                         {"role": "user", "content": user_prompt(item, codebook)}],
        })
        text = (resp.get("message") or {}).get("content", "")
        values = parse_output(text, codebook)
        meta = {"model": self.model, "model_digest": digest, "temperature": 0, "seed": self.seed,
                "done_reason": resp.get("done_reason"), "eval_count": resp.get("eval_count")}
        return AIResult(values, text, meta)


# Detoxify label -> (codebook field, threshold). hate_speech here is only a proxy:
# identity_attack does not apply the codebook's strict protected-characteristic test.
DETOXIFY_MAP = {"incivility": ("insult", "toxicity"), "threat": ("threat",), "hate_speech": ("identity_attack",)}


class DetoxifyCoder:
    def __init__(self, variant: str = "unbiased", threshold: float = 0.5, *, model=None):
        if model is None:
            try:
                from detoxify import Detoxify  # optional: pip install detoxify
            except ImportError as e:
                raise AICoderSetupError("Detoxify is not installed. Run: pip install detoxify") from e
            model = Detoxify(variant)
        self.model = model
        self.variant = variant
        self.threshold = threshold
        self.name = "ai-detoxify"

    def code(self, item: Item, codebook: Codebook) -> AIResult:
        scores = {k: float(v) for k, v in self.model.predict(item.text).items()}
        values = {}
        for field, labels in DETOXIFY_MAP.items():
            if field in codebook.names:
                values[field] = str(int(any(scores.get(lab, 0.0) >= self.threshold for lab in labels)))
        values = codebook.validate(values, partial=True)
        return AIResult(values, json.dumps(scores, sort_keys=True),
                        {"model": f"detoxify-{self.variant}", "threshold": self.threshold})


# cardiffnlp Twitter classifiers (Hugging Face). Each model fills one field.
CARDIFF_MODELS = {
    "incivility": ("cardiffnlp/twitter-roberta-base-offensive", "offensive"),
    "hate_speech": ("cardiffnlp/twitter-roberta-base-hate", "hate"),
}


class CardiffCoder:
    """cardiffnlp RoBERTa classifiers trained on tweets (TweetEval).

    'offensive' maps to incivility and 'hate' to hate_speech. Other fields stay
    blank. Pass `pipelines` ({field: callable(text) -> [{"label", "score"}]}) to
    test without downloading models.
    """

    def __init__(self, threshold: float = 0.5, *, pipelines: dict | None = None):
        if pipelines is None:
            try:
                from transformers import pipeline  # optional: pip install transformers torch
            except ImportError as e:
                raise AICoderSetupError("transformers is not installed. Run: pip install transformers torch") from e
            pipelines = {f: pipeline("text-classification", model=m, top_k=None) for f, (m, _) in CARDIFF_MODELS.items()}
        self.pipelines = pipelines
        self.threshold = threshold
        self.name = "ai-cardiff"

    def code(self, item: Item, codebook: Codebook) -> AIResult:
        values, raw = {}, {}
        for field, pipe in self.pipelines.items():
            if field not in codebook.names:
                continue
            out = pipe(item.text)
            if out and isinstance(out[0], list):  # batched shape
                out = out[0]
            scores = {d["label"].lower(): float(d["score"]) for d in out}
            positive = CARDIFF_MODELS[field][1]
            raw[field] = scores
            values[field] = str(int(scores.get(positive, 0.0) >= self.threshold))
        values = codebook.validate(values, partial=True)
        return AIResult(values, json.dumps(raw, sort_keys=True),
                        {"model": ",".join(m for m, _ in CARDIFF_MODELS.values()), "threshold": self.threshold})
