"""Fetch one Bluesky thread from the public AppView into a capture bundle.

Requests per capture: one handle lookup (only for handle URLs), one thread,
one hidden-fold request when the thread has one, and one profile request per
25 authors. No login, so the capture shows what a logged-out reader sees:
authors who opted out of logged-out viewing are left out by Bluesky itself,
and this collector does not try to get around that.
"""

from __future__ import annotations

import re

from twitterdata.bluesky.bundle import PROFILES, RESOLVE_HANDLE, THREAD, THREAD_OTHER, Bundle, response_record
from twitterdata.bluesky.client import Client
from twitterdata.bluesky.mapping import POST_ITEM, SORTS, rkey

MAX_BELOW = 20  # deepest reply level getPostThreadV2 accepts
MAX_BRANCHING = 100  # most nested replies per post getPostThreadV2 accepts
PROFILE_BATCH = 25  # getProfiles limit

_WEB_URL = re.compile(r"^https?://(?:www\.)?bsky\.app/profile/([^/]+)/post/([A-Za-z0-9]+)/?(?:[?#].*)?$")
_AT_URI = re.compile(r"^at://([^/]+)/app\.bsky\.feed\.post/([A-Za-z0-9]+)$")


def parse_target(target: str) -> tuple[str, str]:
    """(actor, rkey) from a bsky.app post URL or an at:// post URI."""
    target = target.strip()
    m = _WEB_URL.match(target) or _AT_URI.match(target)
    if not m:
        raise ValueError(f"not a Bluesky post URL or at:// URI: {target!r}")
    return m.group(1), m.group(2)


def default_capture_id(anchor_uri: str, sort_order: str, age_bucket: str | None,
                       viewer_label: str | None) -> str:
    """bsky_{rkey}[_{age}]_{sort}[_{viewer}], mirroring the X `{root}_h06_relevance_A` ids."""
    parts = ["bsky", rkey(anchor_uri), age_bucket, sort_order, viewer_label]
    return "_".join(p for p in parts if p)


class Collector:
    def __init__(self, client: Client, below: int = MAX_BELOW, branching: int = MAX_BRANCHING,
                 include_other: bool = True, include_profiles: bool = True):
        if not 0 < below <= MAX_BELOW or not 0 < branching <= MAX_BRANCHING:
            raise ValueError(f"below must be 1-{MAX_BELOW}, branching 1-{MAX_BRANCHING}")
        self.client, self.below, self.branching = client, below, branching
        self.include_other, self.include_profiles = include_other, include_profiles
        self._did_cache: dict[str, str] = {}

    def _record(self, responses: list, endpoint: str, params: dict) -> dict:
        resp = self.client.get(endpoint, params)
        responses.append(response_record(endpoint, resp.params, resp.status, resp.received_at, resp.body))
        return resp.body

    def resolve(self, target: str, responses: list) -> str:
        actor, key = parse_target(target)
        if not actor.startswith("did:"):
            handle = actor.lower()
            if handle not in self._did_cache:
                body = self._record(responses, RESOLVE_HANDLE, {"handle": handle})
                self._did_cache[handle] = body["did"]
            actor = self._did_cache[handle]
        return f"at://{actor}/app.bsky.feed.post/{key}"

    def collect(self, target: str, sort_order: str = "relevance", age_bucket: str | None = None,
                viewer_label: str | None = None, capture_id: str | None = None) -> Bundle:
        if sort_order not in SORTS:
            raise ValueError(f"sort_order must be one of {sorted(SORTS)}")
        responses: list[dict] = []
        anchor = self.resolve(target, responses)
        params = {"anchor": anchor, "above": "false", "below": self.below,
                  "branchingFactor": self.branching, "sort": SORTS[sort_order]}
        thread = self._record(responses, THREAD, params)
        if self.include_other and thread.get("hasOtherReplies"):
            self._record(responses, THREAD_OTHER, {"anchor": anchor})
        if self.include_profiles:
            dids = _author_dids(responses)
            for start in range(0, len(dids), PROFILE_BATCH):
                self._record(responses, PROFILES, {"actors": dids[start:start + PROFILE_BATCH]})
        return Bundle(anchor_uri=anchor, bluesky_sort=SORTS[sort_order], sort_order=sort_order,
                      responses=responses, age_bucket=age_bucket, viewer_label=viewer_label, target=target,
                      capture_id=capture_id or default_capture_id(anchor, sort_order, age_bucket, viewer_label))


def _author_dids(responses: list[dict]) -> list[str]:
    """Distinct authors of the focal post and its replies, in first-seen order."""
    out: dict[str, None] = {}
    for resp in responses:
        if resp["endpoint"] not in (THREAD, THREAD_OTHER):
            continue
        for item in resp["body"].get("thread", []):
            value = item.get("value", {})
            if item.get("depth", 0) >= 0 and value.get("$type") == POST_ITEM:
                out.setdefault(value["post"]["author"]["did"], None)
    return list(out)
