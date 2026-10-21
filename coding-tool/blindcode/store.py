"""Per-coder storage.

Each coder gets one append-only JSONL file: <store>/<coder>.jsonl. Re-coding
an item appends a new line; the latest line per uid wins. Nothing is ever
rewritten, so the file doubles as an audit log.
"""
from __future__ import annotations

import csv
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from .codebook import Codebook, CodebookError

_CODER_ID = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")


def check_coder_id(coder: str) -> str:
    if not _CODER_ID.match(coder) or coder.startswith("."):
        raise ValueError(f"coder id {coder!r} must be 1-64 letters, digits, '_', '-' or '.'")
    return coder


class CoderStore:
    def __init__(self, root: str | Path, coder: str):
        self.coder = check_coder_id(coder)
        self.path = Path(root) / f"{coder}.jsonl"

    def records(self) -> list[dict]:
        if not self.path.exists():
            return []
        with open(self.path, encoding="utf-8") as fh:
            return [json.loads(line) for line in fh if line.strip()]

    def latest(self) -> dict[str, dict]:
        """uid -> latest record."""
        out = {}
        for rec in self.records():
            out[rec["uid"]] = rec
        return out

    def save(self, uid: str, values: dict, codebook: Codebook, *, kind: str = "human", meta: dict | None = None,
             partial: bool = False) -> dict:
        """Append one code. partial=True allows blank coded fields (AI backends that cover only some fields)."""
        rec = {
            "uid": uid,
            "coder": self.coder,
            "kind": kind,
            "values": codebook.validate(values, partial=partial),
            "codebook_id": codebook.id,
            "codebook_sha256": codebook.sha256,
            "coded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        if meta:
            rec["meta"] = meta
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
        return rec

    def export_csv(self, out: str | Path, codebook: Codebook) -> int:
        """Write latest codes as a flat CSV (uid + codebook columns)."""
        latest = self.latest()
        with open(out, "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["uid"] + codebook.names)
            for uid, rec in latest.items():
                w.writerow([uid] + [rec["values"].get(n, "") for n in codebook.names])
        return len(latest)


def list_coders(root: str | Path) -> list[str]:
    return sorted(p.stem for p in Path(root).glob("*.jsonl"))


def load_all(root: str | Path) -> dict[str, dict[str, dict]]:
    """coder -> uid -> latest record, for every coder in the store."""
    return {c: CoderStore(root, c).latest() for c in list_coders(root)}


def import_csv(path: str | Path, root: str | Path, coder: str, codebook: Codebook, *, kind: str = "human") -> int:
    """Load an existing flat coding CSV (e.g. coded_A.csv) into the store."""
    store = CoderStore(root, coder)
    n = 0
    with open(path, newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    shas = {r.get("codebook_sha256", "") for r in rows} - {""}
    if shas and shas != {codebook.sha256}:
        raise ValueError(f"{Path(path).name} was coded with a different codebook version than {codebook.id}")
    partial = kind == "ai"  # AI backends may leave fields they do not cover blank
    checked = []
    for i, row in enumerate(rows, 2):  # validate everything before writing anything
        try:
            checked.append((row["uid"], codebook.validate({k: row[k] for k in codebook.names if k in row}, partial=partial)))
        except CodebookError as e:
            raise ValueError(f"{Path(path).name} line {i}: {e}. Nothing was imported.") from e
    for uid, values in checked:
        store.save(uid, values, codebook, kind=kind, meta={"imported_from": Path(path).name}, partial=partial)
        n += 1
    return n
