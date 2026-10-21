"""Codebook: the single source of truth for what coders (human or AI) record.

A codebook is a JSON file. Its SHA-256 is stamped on every stored code so a
report can tell when coders worked from different versions.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path

BUILTIN_DIR = Path(__file__).parent / "codebooks"
DEFAULT_CODEBOOK = BUILTIN_DIR / "reply_v1.json"

BINARY_VALUES = ("0", "1")


class CodebookError(ValueError):
    pass


@dataclass(frozen=True)
class Field:
    name: str
    type: str  # "binary" | "categorical" | "text"
    definition: str
    options: tuple[str, ...] = ()
    max_words: int | None = None
    key: bool = True  # counts toward the headline pass/fail verdict

    @property
    def allowed(self) -> tuple[str, ...]:
        if self.type == "binary":
            return BINARY_VALUES
        return self.options

    @property
    def is_coded(self) -> bool:
        """True for fields that take part in reliability statistics."""
        return self.type in ("binary", "categorical")

    def normalise(self, value) -> str:
        """Return the canonical string for value, or raise CodebookError."""
        if value is None:
            value = ""
        if isinstance(value, bool):
            value = int(value)
        s = str(value).strip()
        if self.type == "text":
            if self.max_words and len(s.split()) > self.max_words:
                s = " ".join(s.split()[: self.max_words])
            return s
        if self.type == "binary":
            s = {"true": "1", "false": "0", "yes": "1", "no": "0", "y": "1", "n": "0", "1.0": "1", "0.0": "0"}.get(s.lower(), s)
        if s not in self.allowed:
            raise CodebookError(f"{self.name}: {value!r} is not one of {list(self.allowed)}")
        return s


@dataclass(frozen=True)
class Codebook:
    id: str
    title: str
    instructions: str
    contexts: dict[str, str]
    fields: tuple[Field, ...]
    sha256: str = field(default="", compare=False)

    @classmethod
    def load(cls, path: str | Path | None = None) -> "Codebook":
        path = Path(path) if path else DEFAULT_CODEBOOK
        raw = path.read_bytes()
        data = json.loads(raw)
        fields = []
        for f in data["fields"]:
            if f["type"] not in ("binary", "categorical", "text"):
                raise CodebookError(f"unknown field type {f['type']!r} for {f['name']}")
            if f["type"] == "categorical" and not f.get("options"):
                raise CodebookError(f"categorical field {f['name']} needs options")
            fields.append(Field(f["name"], f["type"], f["definition"], tuple(f.get("options", ())), f.get("max_words"),
                                bool(f.get("key", True))))
        names = [f.name for f in fields]
        if len(set(names)) != len(names):
            raise CodebookError("duplicate field names")
        return cls(data["id"], data.get("title", data["id"]), data.get("instructions", ""),
                   dict(data.get("contexts", {})), tuple(fields), hashlib.sha256(raw).hexdigest())

    @property
    def names(self) -> list[str]:
        return [f.name for f in self.fields]

    @property
    def coded_fields(self) -> list[Field]:
        return [f for f in self.fields if f.is_coded]

    @property
    def key_fields(self) -> list[Field]:
        return [f for f in self.coded_fields if f.key]

    def field(self, name: str) -> Field:
        for f in self.fields:
            if f.name == name:
                return f
        raise KeyError(name)

    def validate(self, values: dict, *, partial: bool = False) -> dict[str, str]:
        """Return values normalised to canonical strings.

        Unknown keys are rejected. With partial=False every coded field is required.
        """
        unknown = set(values) - set(self.names)
        if unknown:
            raise CodebookError(f"unknown fields: {sorted(unknown)}")
        out = {}
        for f in self.fields:
            if f.name in values:
                out[f.name] = f.normalise(values[f.name])
            elif f.is_coded and not partial:
                raise CodebookError(f"missing field {f.name}")
            else:
                out[f.name] = ""
        return out

    def render(self) -> str:
        """Plain-text codebook, used both on screen and inside the AI prompt."""
        lines = [self.title, "", self.instructions, ""]
        if self.contexts:
            lines.append("Thread contexts:")
            lines += [f"- {k}: {v}" for k, v in self.contexts.items()]
            lines.append("")
        lines.append("Fields:")
        for i, f in enumerate(self.fields, 1):
            kind = "0/1" if f.type == "binary" else ("one of: " + ", ".join(f.options) if f.type == "categorical" else "free text")
            lines.append(f"{i}. {f.name} ({kind}). {f.definition}")
        return "\n".join(lines)
