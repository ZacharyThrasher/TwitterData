"""TypeSafe AI's Jev model as an AI coder (paid per input token; off unless allowed).

Jev answers yes/no ("noul") and pick-one ("choice") questions about a text and
returns calibrated probabilities. Each codebook field becomes one question in a
single request per reply: binary fields as noul, categorical fields as choice.
Free-text fields are left blank. The probabilities are kept in the raw output,
so borderline replies can be sent to a human first.

Pinning: requests use an alias (jev-latest) but the API reports the concrete
version it served. The first version seen in a run is the pin; a later reply
served by a different version stops the run.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Callable

from ..codebook import Codebook
from ..items import Item
from .anthropic_coder import ALLOW_ENV
from .base import AICoderError, AICoderSetupError, AIResult, PaidCallNotAllowed

DEFAULT_URL = "https://api.typesafe.ai"
DEFAULT_MODEL = "jev-latest"
KEY_ENV = "TYPESAFE_API_KEY"

Transport = Callable[[dict], dict]


def _http(url: str) -> Transport:
    def call(body: dict) -> dict:
        headers = {"Content-Type": "application/json"}
        if os.environ.get(KEY_ENV):  # otherwise an authenticating proxy may add it
            headers["Authorization"] = f"Bearer {os.environ[KEY_ENV]}"
        req = urllib.request.Request(url.rstrip("/") + "/v1/systemone", data=json.dumps(body).encode(),
                                     headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                raise AICoderSetupError(f"TypeSafe API refused the key (HTTP {e.code}). Set {KEY_ENV}.") from e
            raise AICoderError(f"TypeSafe API returned HTTP {e.code}") from e
        except (TimeoutError, json.JSONDecodeError) as e:
            raise AICoderError(f"TypeSafe request failed: {e}") from e
        except urllib.error.URLError as e:
            raise AICoderSetupError(f"cannot reach TypeSafe API at {url} ({e})") from e
    return call


def build_questions(codebook: Codebook) -> dict:
    qs = {}
    for f in codebook.fields:
        if f.type == "binary":
            qs[f.name] = {"type": "noul", "instructions": f"Codebook field `{f.name}`: {f.definition} Is this true of the reply?"}
        elif f.type == "categorical":
            qs[f.name] = {"type": "choice", "instructions": f"Codebook field `{f.name}`: {f.definition}",
                          "criteria": {o: o.replace("_", " ") for o in f.options}}
    return qs


class TypeSafeCoder:
    def __init__(self, model: str = DEFAULT_MODEL, *, url: str = DEFAULT_URL, threshold: float = 0.5,
                 transport: Transport | None = None, allow_paid: bool = False):
        if transport is None:
            if not (allow_paid and os.environ.get(ALLOW_ENV) == "1"):
                raise PaidCallNotAllowed(
                    f"The TypeSafe API bills input tokens. Pass allow_paid=True (CLI: --allow-paid) "
                    f"and set {ALLOW_ENV}=1 once the spend is approved.")
            transport = _http(url)
        self._call = transport
        self.model = model
        self.threshold = threshold
        self.name = f"ai-typesafe-{model}"
        self.pinned: str | None = None

    def code(self, item: Item, codebook: Codebook) -> AIResult:
        state = {"coding_rules": codebook.instructions, "reply": item.text}
        if item.context:
            state["thread_context"] = codebook.contexts.get(item.context, item.context)
        resp = self._call({"model": self.model, "state": state, "questions": build_questions(codebook)})
        served = resp.get("model", "")
        if self.pinned is None:
            self.pinned = served
        elif served != self.pinned:
            raise AICoderSetupError(f"served model changed mid-run: {self.pinned} -> {served}")
        values = {}
        for name, ans in (resp.get("answers") or {}).items():
            if name not in codebook.names:
                continue
            if ans.get("type") == "noul":
                values[name] = str(int(float(ans["noul"]) >= self.threshold))
            elif ans.get("type") == "choice":
                values[name] = ans["choice"]
        missing = [f.name for f in codebook.coded_fields if f.name not in values]
        if missing:
            raise AICoderError(f"no answer for {missing}")
        try:
            values = codebook.validate(values, partial=True)
        except Exception as e:  # an answer outside the codebook's options
            raise AICoderError(f"answer breaks the codebook: {e}") from e
        usage = resp.get("usage") or {}
        meta = {"model": self.model, "served_model": served, "threshold": self.threshold,
                "input_tokens": usage.get("input_tokens"), "output_tokens": usage.get("output_tokens")}
        return AIResult(values, json.dumps(resp.get("answers"), sort_keys=True), meta)
