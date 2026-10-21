"""Claude as a pinned-model third coder (paid; off unless explicitly allowed).

Pinning:
- The model ID is fixed per run and saved on every record together with the
  model the API reports it actually served. A mismatch is treated as an error.
- Server-side refusal fallbacks are deliberately NOT enabled: a fallback would
  silently switch models mid-run and break the pin. A refusal is logged as a
  failed item instead.
- Current Claude models reject `temperature`, so "temperature 0" cannot be set.
  Reproducibility comes from the pinned model, a fixed effort level, a
  schema-constrained output, the saved prompt hash, and the saved raw output
  (re-scorable offline with ReplayCoder). Run it twice under two coder IDs to
  measure self-consistency with the same alpha report.
"""
from __future__ import annotations

import os

from ..codebook import Codebook
from ..items import Item
from .base import AICoderError, AIResult, PaidCallNotAllowed, output_schema, parse_output, system_prompt, user_prompt

DEFAULT_MODEL = "claude-opus-5-5"
DEFAULT_EFFORT = "medium"
ALLOW_ENV = "BLINDCODE_ALLOW_PAID"

# USD per million tokens, (input, output). Estimate only; check current pricing before a run.
PRICES = {"claude-opus-5-5": (4.00, 20.00), "claude-sonnet-5-5": (2.00, 10.00), "claude-haiku-5-5": (0.10, 0.50)}


def estimate_cost(n_items: int, codebook: Codebook, model: str = DEFAULT_MODEL, *, avg_reply_chars: int = 200,
                  output_tokens_per_item: int = 600) -> float | None:
    """Rough upper-end USD estimate. Output allowance includes adaptive thinking."""
    if model not in PRICES:
        return None
    in_tok = (len(system_prompt(codebook)) + avg_reply_chars + 300) / 3.5
    pin, pout = PRICES[model]
    return n_items * (in_tok * pin + output_tokens_per_item * pout) / 1e6


class AnthropicCoder:
    def __init__(self, model: str = DEFAULT_MODEL, effort: str = DEFAULT_EFFORT, *, client=None,
                 allow_paid: bool = False, max_tokens: int = 8000):
        if client is None:
            if not (allow_paid and os.environ.get(ALLOW_ENV) == "1"):
                raise PaidCallNotAllowed(
                    f"Calling the Claude API costs money. Pass allow_paid=True (CLI: --allow-paid) "
                    f"and set {ALLOW_ENV}=1 once the spend is approved.")
            import anthropic  # optional dependency: pip install blindcode[anthropic]
            client = anthropic.Anthropic()
        self.client = client
        self.model = model
        self.effort = effort
        self.max_tokens = max_tokens
        self.name = f"anthropic:{model}"

    def code(self, item: Item, codebook: Codebook) -> AIResult:
        resp = self.client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            system=system_prompt(codebook),
            messages=[{"role": "user", "content": user_prompt(item, codebook)}],
            output_config={"effort": self.effort, "format": {"type": "json_schema", "schema": output_schema(codebook)}},
        )
        if resp.stop_reason == "refusal":
            raise AICoderError("model refused")
        if resp.stop_reason == "max_tokens":
            raise AICoderError("hit max_tokens before finishing")
        if resp.model != self.model:
            raise AICoderError(f"served model {resp.model!r} differs from pinned {self.model!r}")
        text = next((b.text for b in resp.content if getattr(b, "type", "") == "text"), "")
        values = parse_output(text, codebook)
        usage = getattr(resp, "usage", None)
        meta = {
            "model": self.model,
            "served_model": resp.model,
            "effort": self.effort,
            "stop_reason": resp.stop_reason,
            "response_id": getattr(resp, "id", None),
            "input_tokens": getattr(usage, "input_tokens", None),
            "output_tokens": getattr(usage, "output_tokens", None),
        }
        return AIResult(values, text, meta)
