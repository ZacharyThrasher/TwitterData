"""Rule for tagging an X account as a paid clipper.

The full rule, with reasons and known failure modes, is in
docs/clip-monitor/PAID_CLIPPER_RULE.md. This module is the executable version;
the two must stay in sync (tests/test_clipper_rule.py checks the examples in
the doc).

Input is one account as a dict with the column names our capture CSVs already
use (screen_name, name, description, professional_type, affiliate_badge,
is_blue_verified, statuses_count, media_tweets_count) plus, optionally,
"texts": a list of that account's post texts.

Tiers, from strongest to weakest:

    paid_confirmed   public evidence of payment: a clipping-marketplace
                     affiliate badge, or a post carrying a campaign-specific
                     hashtag seen in a marketplace snapshot.
    paid_likely      clear clip-account identity (two or more medium signals,
                     or one medium plus a supporting signal).
    clip_possible    one medium signal only.
    none             nothing.

Only paid_confirmed is evidence that money changed hands. paid_likely means
the account behaves like bounty clippers do; many fan clip accounts are unpaid.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

RULE_VERSION = "1"

# Affiliate badges (X "affiliates_highlighted_label") naming a clipping
# marketplace or clipping agency.
MARKETPLACE_BADGES = [
    "clipur", "vyro", "clipping", "whop", "content rewards", "contentrewardz",
    "lumina", "clipfarm", "clipaffiliates", "reach.cat",
]

# Disclosure hashtags shared by many unrelated campaigns. They show the post
# is paid, but not by whom, so they count as supporting evidence only.
GENERIC_DISCLOSURE_TAGS = {"#ad", "#sponsored", "#paidpartnership", "#partner", "#promo"}

_BIO_PATTERNS = [
    ("bio_clips", re.compile(r"\bclip(s|per|pers|ping|ped)?\b", re.I)),
    ("bio_not_impersonating", re.compile(r"\bnot\s+imperson", re.I)),
    ("bio_fan_or_parody", re.compile(r"\b(fan\s*account|parody|not\s+affiliated)\b", re.I)),
    ("bio_dm_for_promo", re.compile(r"\bdm\b[^|]{0,20}\b(ads?|promo|promos|submissions?|removal)\b", re.I)),
]
_HANDLE_PATTERN = re.compile(r"(clip|mp4\b|highlights)", re.I)
# Words that contain "clip" but have nothing to do with clipping.
_FALSE_FRIENDS = re.compile(r"(eclips\w*|clipboard|paperclip|clippers?\s*(nation|fan|fans|basketball)|la\s*clippers)", re.I)


@dataclass
class Tag:
    tier: str
    signals: list = field(default_factory=list)
    matched_campaign_tags: list = field(default_factory=list)
    rule_version: str = RULE_VERSION


def _truthy(v) -> bool:
    return str(v).strip().lower() in {"true", "1", "yes"}


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def campaign_hashtags(rows) -> set:
    """Campaign-specific hashtags from campaign_snapshots.csv rows (generic ones dropped)."""
    tags = set()
    for r in rows:
        for t in (r.get("required_hashtags") or "").split(";"):
            t = t.strip().lower()
            if t.startswith("#") and t not in GENERIC_DISCLOSURE_TAGS:
                tags.add(t)
    return tags


def tag_account(account: dict, known_campaign_tags=frozenset()) -> Tag:
    strong, medium, support = [], [], []
    matched = []

    badge = (account.get("affiliate_badge") or "").lower()
    if badge and any(m in badge for m in MARKETPLACE_BADGES):
        strong.append("affiliate_badge_marketplace")

    texts = account.get("texts") or []
    known = {t.lower() for t in known_campaign_tags}
    post_tags = set()
    for text in texts:
        post_tags.update(t.lower() for t in re.findall(r"#\w+", text or ""))
    matched = sorted(post_tags & known)
    if matched:
        strong.append("campaign_hashtag_in_post")
    if post_tags & GENERIC_DISCLOSURE_TAGS:
        support.append("generic_disclosure_hashtag")

    bio = _FALSE_FRIENDS.sub(" ", account.get("description") or "")
    for name, pat in _BIO_PATTERNS:
        if pat.search(bio):
            medium.append(name)

    handle = f"{account.get('screen_name') or ''} {account.get('name') or ''}"
    handle = _FALSE_FRIENDS.sub(" ", handle)
    if _HANDLE_PATTERN.search(handle):
        medium.append("handle_or_name_clip")

    ptype = (account.get("professional_type") or "").strip().lower()
    if ptype in {"business", "creator"}:
        support.append("professional_account")
    statuses = _num(account.get("statuses_count"))
    media = _num(account.get("media_tweets_count"))
    if statuses and media is not None and statuses >= 50 and media / statuses >= 0.5:
        support.append("media_share_50pct")
    if _truthy(account.get("is_blue_verified")):
        # Needed to earn X creator payouts, so weak but relevant.
        support.append("premium_subscriber")

    signals = strong + medium + support
    if strong:
        tier = "paid_confirmed"
    elif len(medium) >= 2 or (medium and any(s != "premium_subscriber" for s in support)):
        tier = "paid_likely"
    elif medium:
        tier = "clip_possible"
    else:
        tier = "none"
    return Tag(tier=tier, signals=signals, matched_campaign_tags=matched)
