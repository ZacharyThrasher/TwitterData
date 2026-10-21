"""Read reply tables (schema v1) and check them against the schema.

The schema is owned by the capture parser (`src/twitterdata/schema.py`,
`schema/reply_table.v1.json`). A copy of the JSON file ships in this package
so the pipeline runs on its own; `tests/test_schema_prepare.py` checks the copy still
matches the repository file when both are present.
"""

from __future__ import annotations

import json
from functools import lru_cache
from importlib import resources
from pathlib import Path

import pandas as pd

SUPPORTED_VERSIONS = ("1",)


class SchemaError(ValueError):
    """A reply table does not match schema v1."""


@lru_cache(maxsize=1)
def load_schema() -> dict:
    text = resources.files("replyanalysis").joinpath("data/reply_table.v1.json").read_text(encoding="utf-8")
    return json.loads(text)


def columns() -> list[dict]:
    return load_schema()["columns"]


def column_names() -> list[str]:
    return [c["name"] for c in columns()]


def _read_raw(path: Path) -> pd.DataFrame:
    # Every column is read as text first; ids exceed float precision and must stay strings.
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return pd.read_csv(path, dtype=str, keep_default_na=False, na_values=[""])
    if suffix in (".jsonl", ".ndjson"):
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        df = pd.DataFrame(rows)
        return df.astype(object).where(df.notna(), None)
    raise SchemaError(f"{path}: expected .csv or .jsonl, got {suffix or 'no extension'}")


def _to_bool(value):
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return pd.NA
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in ("true", "1"):
        return True
    if text in ("false", "0"):
        return False
    raise SchemaError(f"not a boolean: {value!r}")


def coerce(df: pd.DataFrame, source: str = "table") -> pd.DataFrame:
    """Check columns, nulls and enums, then convert to analysis dtypes."""
    if df.empty:
        raise SchemaError(f"{source}: no rows")
    expected = column_names()
    missing = [c for c in expected if c not in df.columns]
    if missing:
        raise SchemaError(f"{source}: missing schema v1 columns: {', '.join(missing)}")
    versions = set(df["schema_version"].dropna().astype(str))
    if not versions <= set(SUPPORTED_VERSIONS):
        raise SchemaError(f"{source}: unsupported schema_version {sorted(versions)}")

    out = pd.DataFrame(index=df.index)
    for col in columns():
        name, kind = col["name"], col["type"]
        series = df[name].astype(object).where(df[name].notna(), None)
        if not col["nullable"] and series.isna().any():
            raise SchemaError(f"{source}: column {name} has empty values but is not nullable")
        if kind == "integer":
            out[name] = pd.to_numeric(series, errors="raise").astype("Int64")
        elif kind == "boolean":
            out[name] = series.map(_to_bool).astype("boolean")
        elif kind == "timestamp":
            out[name] = pd.to_datetime(series, utc=True, errors="raise", format="ISO8601")
        else:
            out[name] = series.map(lambda v: None if v is None else str(v)).astype("string")
        if col.get("enum"):
            bad = set(out[name].dropna()) - set(col["enum"])
            if bad:
                raise SchemaError(f"{source}: column {name} has values outside the schema: {sorted(bad)}")
    # Extra columns (a later minor version, or local additions) are kept as text.
    for extra in [c for c in df.columns if c not in expected]:
        out[extra] = df[extra]
    return out


def read_reply_table(path: str | Path) -> pd.DataFrame:
    path = Path(path)
    return coerce(_read_raw(path), source=str(path))


def read_reply_tables(paths: list[str | Path]) -> pd.DataFrame:
    """Read many parser outputs into one frame. Directories are searched for *.csv and *.jsonl."""
    files: list[Path] = []
    for p in map(Path, paths):
        if p.is_dir():
            files += sorted(list(p.glob("*.csv")) + list(p.glob("*.jsonl")))
        else:
            files.append(p)
    if not files:
        raise SchemaError("no reply table files found")
    raw = [_read_raw(f) for f in files]
    try:
        df = coerce(pd.concat(raw, ignore_index=True), source=f"{len(files)} reply table files")
    except (SchemaError, ValueError, TypeError):
        # Name the first offending file rather than the batch.
        for f, frame in zip(files, raw):
            coerce(frame, source=str(f))
        raise
    dup = df.duplicated(["capture_id", "capture_session", "display_index"])
    if dup.any():
        raise SchemaError(
            f"{int(dup.sum())} rows share capture_id + capture_session + display_index; "
            "the same capture was probably loaded twice"
        )
    return df
