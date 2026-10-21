"""Record and scrub Bluesky API fixtures.

Fixtures are real public AppView responses with every identity swapped for a
stable fake: DIDs, handles, record keys and CIDs are replaced one-to-one, text
becomes a placeholder, and names, avatars, bios and link titles are dropped.
Every timestamp moves back by the same fixed amount, so relative order and
gaps stay true but posts cannot be matched to the live thread by time.
Structure, order, counts, languages, labels and embed types stay as recorded,
so tests exercise the real response shape without publishing anyone's
identity.

Re-record (needs network; the collector itself is free and needs no login):

    python tests/bluesky_fixtures.py <bsky.app post URL>
"""

from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timedelta
from urllib.parse import urlparse

OFFICIAL_MODERATION = "did:plc:ar7c4by46qjdydhdevvrndac"
FIXTURE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "bluesky")

DROP_KEYS = {
    "displayName", "avatar", "banner", "description", "status", "facets", "viewer", "pronouns", "website",
    "pinnedPost", "joinedViaStarterPack", "thumb", "fullsize", "alt", "aspectRatio", "playlist", "thumbnail",
    "title", "sig", "verifications", "debug", "presentation", "tags", "via",
}
TIME_SHIFT = timedelta(days=397, hours=5, minutes=17)
_ISO = re.compile(r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(\.\d+)?(Z|[+-]\d{2}:\d{2})$")
_DID = re.compile(r"did:(?:plc:[a-z2-7]{24}|web:[A-Za-z0-9.\-:%]+)")
_AT = re.compile(r"at://([^/\s]+)/([a-z0-9.]+)/([A-Za-z0-9._~:-]+)")


class Scrubber:
    def __init__(self):
        self.dids: dict[str, str] = {OFFICIAL_MODERATION: OFFICIAL_MODERATION}
        self.handles: dict[str, str] = {}
        self.rkeys: dict[str, str] = {}
        self.cids: dict[str, str] = {}
        self.texts = 0

    def did(self, value: str) -> str:
        if value not in self.dids:
            self.dids[value] = f"did:plc:fx{len(self.dids):022d}"
        return self.dids[value]

    def handle(self, value: str) -> str:
        if value == "handle.invalid":
            return value
        if value.lower() not in self.handles:
            self.handles[value.lower()] = f"user{len(self.handles) + 1}.fixture.test"
        return self.handles[value.lower()]

    def rkey(self, value: str) -> str:
        if value in ("self",):
            return value
        if value not in self.rkeys:
            self.rkeys[value] = f"fx{len(self.rkeys) + 1:011d}"
        return self.rkeys[value]

    def cid(self, value: str) -> str:
        if value not in self.cids:
            self.cids[value] = f"bafyfixture{len(self.cids) + 1:08d}"
        return self.cids[value]

    def string(self, value: str) -> str:
        m = _ISO.match(value)
        if m:
            shifted = datetime.fromisoformat(m.group(1)) - TIME_SHIFT
            return shifted.strftime("%Y-%m-%dT%H:%M:%S") + (m.group(2) or "") + m.group(3)
        value = _AT.sub(lambda m: f"at://{self.did(m.group(1)) if m.group(1).startswith('did:') else self.handle(m.group(1))}"
                                  f"/{m.group(2)}/{self.rkey(m.group(3))}", value)
        value = re.sub(r"(bsky\.app/profile/)([^/]+)(/post/)([A-Za-z0-9]+)",
                       lambda m: m.group(1) + (self.did(m.group(2)) if m.group(2).startswith("did:")
                                               else self.handle(m.group(2))) + m.group(3) + self.rkey(m.group(4)),
                       value)
        return _DID.sub(lambda m: self.did(m.group(0)), value)

    def walk(self, node, key: str | None = None):
        if isinstance(node, dict):
            out = {}
            for k, v in node.items():
                if k in DROP_KEYS:
                    continue
                if k == "associated":
                    if isinstance(v, dict) and "labeler" in v:
                        out[k] = {"labeler": v["labeler"]}
                    continue
                out[k] = self.walk(v, k)
            return out
        if isinstance(node, list):
            return [self.walk(v, key) for v in node]
        if not isinstance(node, str):
            return node
        if key == "handle":
            return self.handle(node)
        if key == "cid" or key == "$link":
            return self.cid(node)
        if key == "text":
            self.texts += 1
            return f"fixture text {self.texts}"
        if key == "uri" and node.startswith("http"):
            host = urlparse(node).hostname or "example.test"
            return f"https://{host}/redacted"
        return self.string(node)


def scrub_bundle(data: dict) -> dict:
    return Scrubber().walk(data)


def record(target: str, sorts=("relevance", "recent")) -> list[str]:  # pragma: no cover - needs network
    sys.path.insert(0, os.path.join(os.path.dirname(FIXTURE_DIR), "..", "..", "src"))
    from twitterdata.bluesky.client import Client
    from twitterdata.bluesky.collector import Collector

    collector = Collector(Client(min_interval=1.0))
    scrubber = Scrubber()  # shared, so the same post maps to the same fake id in every fixture
    written = []
    os.makedirs(FIXTURE_DIR, exist_ok=True)
    for sort_order in sorts:
        bundle = collector.collect(target, sort_order, age_bucket="h24")
        scrubbed = scrubber.walk(bundle.to_json())
        scrubbed["capture_id"] = f"fixture_{sort_order}"
        path = os.path.join(FIXTURE_DIR, f"thread_{sort_order}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(scrubbed, f, ensure_ascii=False, indent=1)
            f.write("\n")
        written.append(path)
    return written


if __name__ == "__main__":  # pragma: no cover
    for p in record(sys.argv[1]):
        print(p)
