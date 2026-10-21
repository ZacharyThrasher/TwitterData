"""Pseudonymous hashing and the output secret guard."""

from __future__ import annotations

import hashlib
import hmac
import os
import re
import secrets
import sys

SALT_ENV = "TWITTERDATA_HASH_SALT"
DEFAULT_SALT_FILE = os.path.join(os.path.expanduser("~"), ".config", "twitterdata", "hash_salt")
HASH_HEX_CHARS = 24


def load_salt(path: str | None = None, create: bool = True) -> bytes:
    """Salt for identity hashes: env var, else a local file created on first use.

    The salt must stay out of the repository. Without it, a handle hash is
    easy to reverse by hashing candidate handles; with it, hashes only match
    across captures processed with the same salt.
    """
    env = os.environ.get(SALT_ENV)
    if env:
        return env.encode("utf-8")
    path = path or DEFAULT_SALT_FILE
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            value = f.read().strip()
        if not value:
            raise ValueError(f"salt file {path} is empty")
        return value.encode("utf-8")
    if not create:
        raise FileNotFoundError(path)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    value = secrets.token_hex(32)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(value + "\n")
    print(f"created new hash salt at {path}; keep it to get matching hashes across runs", file=sys.stderr)
    return value.encode("utf-8")


def pseudonym(salt: bytes, platform: str, kind: str, value: str | None) -> str | None:
    """HMAC-SHA256 of `platform:kind:value`, truncated to 24 hex characters."""
    if value is None or value == "":
        return None
    msg = f"{platform}:{kind}:{value}".encode("utf-8")
    return hmac.new(salt, msg, hashlib.sha256).hexdigest()[:HASH_HEX_CHARS]


# Shapes of X session secrets. Any output cell matching one is replaced with
# REDACTED. The safe loader already drops the places these live, so a hit here
# means something unexpected and is reported.
SECRET_PATTERNS = (
    re.compile(r"\bauth_token\s*[=:]", re.I),
    re.compile(r"\bct0\s*[=:]", re.I),
    re.compile(r"\btwid\s*[=:]", re.I),
    re.compile(r"\bkdt\s*[=:]", re.I),
    re.compile(r"\bx-csrf-token\b", re.I),
    re.compile(r"\bBearer\s+[A-Za-z0-9%._~+/=-]{20,}"),
    re.compile(r"AAAAAAAAAAAAAAAAAAAAA[A-Za-z0-9%]{20,}"),  # X web bearer token prefix
)
REDACTED = "REDACTED"


def looks_secret(value: str) -> bool:
    return any(p.search(value) for p in SECRET_PATTERNS)


def scrub_rows(rows: list[dict]) -> int:
    """Redact secret-shaped string cells in place; return how many were hit."""
    hits = 0
    for row in rows:
        for key, value in row.items():
            if isinstance(value, str) and looks_secret(value):
                row[key] = REDACTED
                hits += 1
    return hits
