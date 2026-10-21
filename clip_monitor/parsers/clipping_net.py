"""Parser for the featured campaign cards on https://clipping.net/ .

Each card shows the campaign (usually the buyer's name, e.g. "Stake Bounties"),
a status badge, days left, an "Up to per 100k" rate for each platform (or a
fixed "Bounty pot"), the platforms that count, and a minimum view count to
qualify. Rates are ceilings ("up to"), so rate_is_max is set. The page has no buyer field separate from
the campaign name, so buyer repeats the name.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from ..models import Campaign, normalize_platform
from .common import parse_count, parse_money, per_1k, text_tokens

SOURCE = "clipping_net"
BASE = "https://clipping.net"

_ICON = re.compile(r'<img\b[^>]*alt="([^"]+) campaign icon"[^>]*>')
_PLATFORM_SVG = re.compile(r'class="text-(x|tiktok|instagram|youtube)\b')
_RATE_PAIR = re.compile(
    r'class="text-(x|tiktok|instagram|youtube)\b[^"]*"[^>]*>.*?</svg>\s*<span[^>]*>([^<]+)</span>', re.S
)


def parse(page: str, url: str = "", observed_at: str = "") -> list:
    icons = list(_ICON.finditer(page))
    out = {}
    for n, m in enumerate(icons):
        end = icons[n + 1].start() if n + 1 < len(icons) else len(page)
        card = page[m.start() : end]
        c = _card(card, observed_at)
        if c and c.campaign_id not in out:
            out[c.campaign_id] = c
    return list(out.values())


def _card(card: str, observed_at: str):
    h2 = re.search(r"<h2\b[^>]*>(.*?)</h2>", card, re.S)
    if not h2:
        return None
    name = " ".join(text_tokens(h2.group(1)))
    tokens = text_tokens(card)

    status = ""
    for tok in tokens:
        if tok.lower() in {"active", "paused", "ended", "completed", "full"}:
            status = tok.lower()
            break

    end_date = ""
    m = re.search(r"(\d+)\s*days?\s+left", " ".join(tokens), re.I)
    if m:
        end_date = _days_left_to_date(int(m.group(1)), observed_at)

    rate_label = next((t for t in tokens if "per 100k" in t.lower() or "per 1" in t.lower()), "per 100k")
    rate_block = card
    platforms_at = card.find(">Platforms<")
    if platforms_at > 0:
        rate_block = card[:platforms_at]
    platform_rates = {}
    for plat, amount in _RATE_PAIR.findall(rate_block):
        p = normalize_platform(plat)
        value = per_1k(parse_money(amount), rate_label)
        if p and value is not None:
            platform_rates[p] = value

    platforms = []
    if platforms_at > 0:
        tail = card[platforms_at:]
        ul_end = tail.find("</ul>")
        platforms = sorted(
            {p for p in (normalize_platform(x) for x in _PLATFORM_SVG.findall(tail[: ul_end if ul_end > 0 else None])) if p}
        )
    if not platforms:
        platforms = sorted(platform_rates)

    pot = None
    for i, tok in enumerate(tokens):
        if tok.lower() == "bounty pot" and i + 1 < len(tokens):
            pot = parse_money("".join(tokens[i + 1 : i + 3]))
            break

    min_views = None
    for i, tok in enumerate(tokens):
        if tok == "Min" and i + 1 < len(tokens):
            min_views = parse_count(tokens[i + 1])
            break

    return Campaign(
        source=SOURCE,
        campaign_id="name:" + re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-"),
        name=name,
        buyer=name,
        payout_model="cpm" if platform_rates else ("bounty" if pot is not None else ""),
        rate_per_1k_usd=max(platform_rates.values()) if platform_rates else None,
        rate_is_max=bool(platform_rates),
        platform_rates_per_1k=platform_rates,
        platforms=platforms,
        platforms_known=bool(platforms),
        budget_total_usd=pot,
        status=status,
        end_date=end_date,
        min_views_per_clip=min_views,
        url=BASE + "/",
    )


def _days_left_to_date(days: int, observed_at: str) -> str:
    try:
        base = datetime.fromisoformat(observed_at.replace("Z", "+00:00")) if observed_at else None
    except ValueError:
        base = None
    if base is None:
        return ""
    if base.tzinfo is None:
        base = base.replace(tzinfo=timezone.utc)
    return (base + timedelta(days=days)).date().isoformat()
