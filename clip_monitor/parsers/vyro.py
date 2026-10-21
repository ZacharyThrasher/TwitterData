"""Parser for Vyro (vyro.com) campaign pages.

Two page kinds are supported:

* the board, https://vyro.com/campaigns . The server ships the first page of
  campaigns as JSON inside the Next.js payload (`"initialPage":{"data":[...]}`),
  which carries buyer, CPM, budget, platforms and required hashtags. When that
  payload is missing (a browser save of a later page, or a layout change) the
  parser falls back to the visible cards, which give buyer, name and rate only.
* a single campaign, https://vyro.com/campaigns/<slug> . Gives buyer, name,
  platforms and rate.

Vyro quotes `payRate` in dollars per 1,000 views and shows it on screen as
dollars per 1M views; both are normalized to dollars per 1,000 views.
"""

from __future__ import annotations

import re

from ..models import Campaign, normalize_platform
from .common import (
    balanced_json_after,
    next_flight_payload,
    parse_money,
    per_1k,
    text_tokens,
)

SOURCE = "vyro"
BASE = "https://vyro.com"


def parse(page: str, url: str = "", observed_at: str = "") -> list:
    """Parse either page kind. Returns a list of Campaign."""
    if re.search(r"/campaigns/[^/?#]+", url or ""):
        detail = parse_detail(page, url)
        return [detail] if detail else []
    campaigns = parse_board(page)
    if not campaigns and _looks_like_detail(page):
        detail = parse_detail(page, url)
        return [detail] if detail else []
    return campaigns


def parse_board(page: str) -> list:
    by_id = {}
    blob = next_flight_payload(page)
    initial = balanced_json_after(blob, "initialPage") if blob else None
    if isinstance(initial, dict):
        for item in initial.get("data") or []:
            c = _from_json(item)
            if c:
                by_id[c.campaign_id] = c
    # Cards fill in anything the JSON did not cover (for example page 2 saved
    # from a browser after clicking "next").
    for c in _from_cards(page):
        by_id.setdefault(c.campaign_id, c)
    return list(by_id.values())


def _from_json(item: dict):
    if not isinstance(item, dict) or not item.get("id"):
        return None
    payout = item.get("payoutModel") or {}
    budget = item.get("budget") or {}
    targeting = item.get("targeting") or {}
    reqs = item.get("requirements") or {}
    text_reqs = reqs.get("text") or {}
    platforms = sorted(
        {p for p in (normalize_platform(x) for x in targeting.get("platforms") or []) if p}
    )
    platform_rates = {}
    for name, spec in (payout.get("platformRates") or {}).items():
        p = normalize_platform(name)
        if p and isinstance(spec, dict) and spec.get("payRate") is not None:
            platform_rates[p] = float(spec["payRate"])
    rate = payout.get("payRate", item.get("headlineRate"))
    hashtags = []
    for tag in (text_reqs.get("ftcDisclosureHashtags") or []) + (text_reqs.get("hashtags") or []):
        if tag and tag not in hashtags:
            hashtags.append(tag)
    slug = item.get("slug") or ""
    if not slug:
        return None
    min_views = reqs.get("minViewsPerClip")
    return Campaign(
        source=SOURCE,
        campaign_id=_slug_id(slug),
        name=(item.get("name") or "").strip(),
        buyer=((item.get("workspace") or {}).get("name") or "").strip(),
        payout_model=str(payout.get("model") or "").lower(),
        rate_per_1k_usd=float(rate) if rate is not None else None,
        rate_is_max=bool(item.get("headlineRateIsRange")),
        platform_rates_per_1k=platform_rates,
        platforms=platforms,
        platforms_known=bool(targeting.get("platforms")),
        budget_total_usd=_num(budget.get("value")),
        budget_spent_usd=_num(budget.get("spent")),
        budget_remaining_usd=_num(budget.get("remaining")),
        status=((item.get("status") or {}).get("id") or ""),
        is_locked=item.get("isLocked"),
        start_date=item.get("startDate") or "",
        end_date=item.get("endDate") or "",
        min_views_per_clip=int(min_views) if isinstance(min_views, (int, float)) else None,
        required_hashtags=hashtags,
        url=f"{BASE}/campaigns/{slug}",
    )


_CARD = re.compile(r'<a\b[^>]*href="(?:https://vyro\.com)?/campaigns/([^"/?#]+)"[^>]*>(.*?)</a>', re.S)


def _from_cards(page: str) -> list:
    out = []
    for slug, body in _CARD.findall(page):
        h3 = re.search(r"<h3\b[^>]*>(.*?)</h3>", body, re.S)
        para = re.search(r"<p\b[^>]*>(.*?)</p>", body, re.S)
        tokens = text_tokens(body)
        rate = None
        for i, tok in enumerate(tokens):
            if tok.startswith("$") and i + 1 < len(tokens) and "views" in tokens[i + 1].lower():
                rate = per_1k(parse_money(tok), tokens[i + 1])
                break
        if not h3 and rate is None:
            continue  # a plain link, not a campaign card
        out.append(
            Campaign(
                source=SOURCE,
                campaign_id=_slug_id(slug),
                name=" ".join(text_tokens(para.group(1))) if para else "",
                buyer=" ".join(text_tokens(h3.group(1))) if h3 else "",
                payout_model="cpm" if rate is not None else "",
                rate_per_1k_usd=rate,
                platforms_known=False,
                is_locked=True if "Locked" in tokens else None,
                url=f"{BASE}/campaigns/{slug}",
            )
        )
    return out


def _looks_like_detail(page: str) -> bool:
    return ">Payout<" in page or '"Payout"' in next_flight_payload(page)


def parse_detail(page: str, url: str = ""):
    blob = next_flight_payload(page)
    slug = ""
    m = re.search(r"/campaigns/([^/?#]+)", url or "")
    if m:
        slug = m.group(1)
    else:
        m = re.search(r'rel="canonical" href="https://vyro\.com/campaigns/([^"]+)"', page)
        if m:
            slug = m.group(1)

    name = ""
    m = re.search(r"<h1\b[^>]*>(.*?)</h1>", page, re.S)
    if m:
        name = " ".join(text_tokens(m.group(1)))

    buyer = ""
    m = re.search(r'alt="([^"]+) logo"', page) or re.search(r'"alt":"([^"]+) logo"', blob)
    if m:
        buyer = m.group(1).strip()

    platforms = []
    m = re.search(r'"platforms":(\[[^\]]*\])', blob)
    if m:
        platforms = sorted(
            {p for p in (normalize_platform(x) for x in re.findall(r'"([^"]+)"', m.group(1))) if p}
        )

    rate = None
    tokens = text_tokens(page)
    for i, tok in enumerate(tokens):
        if tok.lower() == "payout" and i + 2 < len(tokens):
            rate = per_1k(parse_money(tokens[i + 1]), tokens[i + 2])
            break

    if not (name or slug):
        return None
    return Campaign(
        source=SOURCE,
        campaign_id=_slug_id(slug) if slug else "name:" + name,
        name=name,
        buyer=buyer,
        payout_model="cpm" if rate is not None else "",
        rate_per_1k_usd=rate,
        platforms=platforms,
        platforms_known=bool(platforms),
        url=f"{BASE}/campaigns/{slug}" if slug else "",
    )


def _slug_id(slug: str) -> str:
    # Vyro slugs end in an 8-character key, e.g. "speed-vegas-lC81wXFS". The
    # key is the one id shared by board JSON, board cards and detail pages
    # (the board JSON's database id is not shown on detail pages).
    return "vyro:" + slug.rsplit("-", 1)[-1]


def _num(v):
    return float(v) if isinstance(v, (int, float)) else None
