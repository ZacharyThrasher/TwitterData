"""Normalized record for one clip-bounty campaign as seen in one snapshot."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Optional

PLATFORMS = ("x", "tiktok", "youtube", "instagram")

# Column order for campaign_snapshots.csv. Keep in sync with Campaign.to_row().
CSV_COLUMNS = [
    "snapshot_id",
    "observed_at",
    "source",
    "campaign_id",
    "name",
    "buyer",
    "payout_model",
    "rate_per_1k_usd",
    "rate_is_max",
    "platform_rates_per_1k",
    "platforms",
    "platforms_known",
    "targets_x",
    "budget_total_usd",
    "budget_spent_usd",
    "budget_remaining_usd",
    "status",
    "is_locked",
    "start_date",
    "end_date",
    "min_views_per_clip",
    "required_hashtags",
    "topic",
    "topics",
    "topic_keywords",
    "url",
]


def normalize_platform(name: str) -> Optional[str]:
    """Map a site's platform label to one of PLATFORMS, or None if unknown."""
    key = name.strip().lower()
    aliases = {
        "x": "x",
        "twitter": "x",
        "x/twitter": "x",
        "tiktok": "tiktok",
        "youtube": "youtube",
        "youtube shorts": "youtube",
        "shorts": "youtube",
        "instagram": "instagram",
        "instagram reels": "instagram",
        "reels": "instagram",
    }
    return aliases.get(key)


@dataclass
class Campaign:
    source: str
    campaign_id: str
    name: str
    buyer: str = ""
    # "cpm" (paid per view), "bounty" (fixed pot shared by winning clips) or "" if unknown.
    payout_model: str = ""
    # Headline payout in US dollars per 1,000 verified views.
    rate_per_1k_usd: Optional[float] = None
    # True when the site shows an "up to" ceiling rather than a flat rate.
    rate_is_max: bool = False
    platform_rates_per_1k: dict = field(default_factory=dict)
    platforms: list = field(default_factory=list)
    # False when the page did not say which platforms count (we must not guess "no X").
    platforms_known: bool = True
    budget_total_usd: Optional[float] = None
    budget_spent_usd: Optional[float] = None
    budget_remaining_usd: Optional[float] = None
    status: str = ""
    is_locked: Optional[bool] = None
    start_date: str = ""
    end_date: str = ""
    min_views_per_clip: Optional[int] = None
    required_hashtags: list = field(default_factory=list)
    url: str = ""
    topic: str = ""
    topics: list = field(default_factory=list)
    topic_keywords: list = field(default_factory=list)

    @property
    def targets_x(self) -> Optional[bool]:
        if not self.platforms_known:
            return None
        return "x" in self.platforms

    def to_row(self, snapshot_id: str, observed_at: str) -> dict:
        d = asdict(self)
        row = {
            "snapshot_id": snapshot_id,
            "observed_at": observed_at,
            "targets_x": _fmt(self.targets_x),
        }
        for col in CSV_COLUMNS:
            if col in row:
                continue
            row[col] = _fmt(d.get(col))
        return row


def _fmt(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        return f"{value:.4f}".rstrip("0").rstrip(".")
    if isinstance(value, dict):
        return ";".join(f"{k}={_fmt(v)}" for k, v in sorted(value.items()))
    if isinstance(value, list):
        return ";".join(str(v) for v in value)
    return str(value)
