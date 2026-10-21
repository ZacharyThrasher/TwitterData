"""Raw capture bundles: the API responses behind one Bluesky capture.

A bundle is the Bluesky counterpart of an X .har file. It keeps every response
the collector received (thread, hidden "other replies" fold, author profiles)
so the reply table can be rebuilt offline with `bluesky parse`. Bundles hold
public posts with real handles and text: treat them as personal data. The
default folder, data/raw/, is git-ignored.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime

BUNDLE_FORMAT = "twitterdata.bluesky_bundle"
BUNDLE_VERSION = 1

THREAD = "app.bsky.unspecced.getPostThreadV2"
THREAD_OTHER = "app.bsky.unspecced.getPostThreadOtherV2"
PROFILES = "app.bsky.actor.getProfiles"
RESOLVE_HANDLE = "com.atproto.identity.resolveHandle"


@dataclass
class Bundle:
    anchor_uri: str
    bluesky_sort: str  # top | newest
    sort_order: str  # reply table value: relevance | recent
    responses: list[dict]  # {endpoint, params, status, received_at, body}
    capture_id: str | None = None
    age_bucket: str | None = None
    viewer_label: str | None = None
    target: str | None = None

    def to_json(self) -> dict:
        return {
            "format": BUNDLE_FORMAT,
            "version": BUNDLE_VERSION,
            "target": self.target,
            "anchor_uri": self.anchor_uri,
            "bluesky_sort": self.bluesky_sort,
            "sort_order": self.sort_order,
            "capture_id": self.capture_id,
            "age_bucket": self.age_bucket,
            "viewer_label": self.viewer_label,
            "responses": self.responses,
        }

    @classmethod
    def from_json(cls, data: dict) -> "Bundle":
        if data.get("format") != BUNDLE_FORMAT:
            raise ValueError("not a Bluesky capture bundle (missing format marker)")
        if data.get("version") != BUNDLE_VERSION:
            raise ValueError(f"unsupported bundle version {data.get('version')!r}")
        return cls(anchor_uri=data["anchor_uri"], bluesky_sort=data["bluesky_sort"],
                   sort_order=data["sort_order"], responses=data["responses"],
                   capture_id=data.get("capture_id"), age_bucket=data.get("age_bucket"),
                   viewer_label=data.get("viewer_label"), target=data.get("target"))

    def responses_for(self, endpoint: str) -> list[dict]:
        return [r for r in self.responses if r["endpoint"] == endpoint]


def response_record(endpoint: str, params: dict, status: int, received_at: datetime, body: dict) -> dict:
    return {"endpoint": endpoint, "params": params, "status": status,
            "received_at": received_at.isoformat().replace("+00:00", "Z"), "body": body}


def save_bundle(bundle: Bundle, path: str) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(bundle.to_json(), f, ensure_ascii=False, indent=1)
        f.write("\n")


def load_bundle(path: str) -> Bundle:
    with open(path, "r", encoding="utf-8") as f:
        return Bundle.from_json(json.load(f))
