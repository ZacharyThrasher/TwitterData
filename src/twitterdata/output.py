"""Write reply table rows as CSV or JSON Lines."""

from __future__ import annotations

import csv
import json

from twitterdata.schema import COLUMN_NAMES


def _csv_cell(value):
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return value


def write_csv(rows: list[dict], path: str) -> None:
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(COLUMN_NAMES)
        for row in rows:
            writer.writerow([_csv_cell(row.get(name)) for name in COLUMN_NAMES])


def write_jsonl(rows: list[dict], path: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps({name: row.get(name) for name in COLUMN_NAMES}, ensure_ascii=False) + "\n")


WRITERS = {"csv": write_csv, "jsonl": write_jsonl}
