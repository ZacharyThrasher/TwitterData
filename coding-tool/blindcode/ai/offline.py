"""AI coder backends that never touch the network.

KeywordCoder is a crude deterministic baseline. It exists so the whole
pipeline (store, alpha, pass rule) can run and be tested for free. It is not
a valid third coder for research results.

ReplayCoder re-reads raw outputs saved by an earlier run, so a paid run can
be re-parsed or re-scored later without paying again.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from ..codebook import Codebook
from ..items import Item
from ..store import CoderStore
from .base import AICoderError, AIResult, parse_output

_INSULTS = r"\b(idiot|stupid|dumb|moron|clown|loser|pathetic|cringe|shut up|stfu|bitch|ass|fuck\w*|shit\w*|cope|seethe|l ?bozo)\b"
_SLURS = r"\b(retard\w*|fag\w*|tranny|dyke|n[i1]gg\w*|whore|slut)\b"
_POLITICAL = r"\b(commie|communist|leftist|libtard|liberal|socialist|marxist|maga|fascist|nazi|tankie|woke)\b"
_THREAT = r"\b(kys|kill yourself|kill your ?self|i will (find|hurt|kill)|die in)\b"
_YOU = r"\b(you|your|you're|ur|u)\b"


def _has(pattern: str, text: str) -> bool:
    return re.search(pattern, text, re.I) is not None


class KeywordCoder:
    name = "ai-keyword-baseline"

    def code(self, item: Item, codebook: Codebook) -> AIResult:
        t = item.text
        slur = _has(_SLURS, t)
        political = _has(_POLITICAL, t)
        threat = _has(_THREAT, t)
        uncivil = slur or threat or _has(_INSULTS, t) or (political and _has(_YOU, t))
        attacks_op = uncivil and _has(_YOU, t)
        values = {
            "stance": "unclear",
            "incivility": int(uncivil),
            "attacks_op": int(attacks_op),
            "target": "op" if attacks_op else ("other" if uncivil else "none"),
            "slur": int(slur),
            "hate_speech": 0,
            "political_identity_attack": int(political and uncivil),
            "threat": int(threat),
            "argument_tag": "insult_only" if uncivil and len(t.split()) < 6 else "other",
            "note": "keyword baseline",
        }
        values = {k: v for k, v in values.items() if k in codebook.names}
        values = codebook.validate(values, partial=True)
        return AIResult(values, json.dumps(values), {"model": "keyword-baseline-v1"})


class ReplayCoder:
    """Replays raw outputs stored by a previous AI run (meta.raw)."""

    def __init__(self, store_root: str | Path, source_coder: str):
        self.name = f"replay-{source_coder}"
        self._recs = CoderStore(store_root, source_coder).latest()

    def code(self, item: Item, codebook: Codebook) -> AIResult:
        rec = self._recs.get(item.uid)
        if not rec or "raw" not in rec.get("meta", {}):
            raise AICoderError("no saved raw output for this uid")
        meta = {k: v for k, v in rec["meta"].items() if k not in ("raw", "backend", "prompt_sha256")}
        return AIResult(parse_output(rec["meta"]["raw"], codebook, partial=True), rec["meta"]["raw"], {**meta, "replayed": True})
