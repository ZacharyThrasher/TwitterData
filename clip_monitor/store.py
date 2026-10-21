"""Append-only storage for snapshots.

Layout under the data directory (default: clip_monitor_data/):

    raw/<source>/<snapshot_id>.html   exact bytes that were parsed (git-ignored)
    snapshots.jsonl                   one line per snapshot: when, how, file hash, counts
    campaign_snapshots.csv            one row per campaign per snapshot

A snapshot is identified by source, observation time and the SHA-256 of the
page, so ingesting the same saved file twice is a no-op.
"""

from __future__ import annotations

import csv
import hashlib
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .models import CSV_COLUMNS

PARSER_VERSION = "1"


@dataclass
class SnapshotMeta:
    snapshot_id: str
    source: str
    observed_at: str
    method: str  # "manual_save" or "fetch"
    page_url: str
    sha256: str
    n_campaigns: int
    parser_version: str = PARSER_VERSION
    original_file: str = ""
    note: str = ""


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def make_snapshot_id(source: str, observed_at: str, digest: str) -> str:
    """e.g. vyro_20261021T175500Z_1a2b3c4d. observed_at is ISO 8601."""
    when = datetime.fromisoformat(observed_at.replace("Z", "+00:00"))
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    stamp = when.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{source}_{stamp}_{digest[:8]}"


class Store:
    def __init__(self, root: str | os.PathLike):
        self.root = Path(root)
        self.raw_dir = self.root / "raw"
        self.log_path = self.root / "snapshots.jsonl"
        self.csv_path = self.root / "campaign_snapshots.csv"
        self._hashes = None

    def known_hashes(self, source: str) -> set:
        # Read the log once per Store; save() keeps the cache current.
        if self._hashes is None:
            self._hashes = {}
            for m in self.snapshots():
                self._hashes.setdefault(m["source"], set()).add(m["sha256"])
        return self._hashes.setdefault(source, set())

    def snapshots(self) -> list:
        if not self.log_path.exists():
            return []
        out = []
        with self.log_path.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    out.append(json.loads(line))
        return out

    def save(self, meta: SnapshotMeta, raw: bytes, campaigns: list) -> bool:
        """Write a snapshot. Returns False (and writes nothing) if already stored.

        The log line is written last and is what marks a snapshot as stored.
        If an earlier run died between the CSV and the log, its rows for this
        snapshot are removed before writing them again, so they never double.
        """
        if meta.sha256 in self.known_hashes(meta.source):
            return False
        self.root.mkdir(parents=True, exist_ok=True)
        raw_path = self.raw_dir / meta.source / f"{meta.snapshot_id}.html"
        raw_path.parent.mkdir(parents=True, exist_ok=True)
        raw_path.write_bytes(raw)

        self._drop_rows(meta.snapshot_id)
        new_file = not self.csv_path.exists()
        with self.csv_path.open("a", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=CSV_COLUMNS)
            if new_file:
                writer.writeheader()
            for c in campaigns:
                writer.writerow(c.to_row(meta.snapshot_id, meta.observed_at))

        with self.log_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(meta.__dict__, sort_keys=True) + "\n")
        self.known_hashes(meta.source).add(meta.sha256)
        return True

    def _drop_rows(self, snapshot_id: str) -> None:
        rows = self.rows()
        keep = [r for r in rows if r["snapshot_id"] != snapshot_id]
        if len(keep) == len(rows):
            return
        with self.csv_path.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=CSV_COLUMNS)
            writer.writeheader()
            writer.writerows(keep)

    def rows(self) -> list:
        if not self.csv_path.exists():
            return []
        with self.csv_path.open(newline="", encoding="utf-8") as fh:
            return list(csv.DictReader(fh))
