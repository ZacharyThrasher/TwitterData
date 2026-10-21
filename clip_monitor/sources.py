"""Registry of clip-bounty marketplaces and what we may collect from each.

Every entry records what was checked and when, so a reader can audit why a
source is or is not collected. `automated_allowed` switches the fetcher on
for a source; robots.txt and the rate limits in fetch.py apply either way.
Vyro and Clipping.net forbid automated collection in their terms; the project
owner chose on 2026-10-21 to collect them automatically anyway.
"""

from __future__ import annotations

from dataclasses import dataclass, field

CHECKED_ON = "2026-10-21"


@dataclass(frozen=True)
class Source:
    key: str
    name: str
    # "public_listing", "login_required", "no_public_listing" or "unreachable"
    access: str
    listing_urls: tuple = ()
    parser: str = ""
    robots_allows_listing: bool = False
    terms_summary: str = ""
    terms_url: str = ""
    automated_allowed: bool = False
    permission_note: str = ""
    # Extra pages that list campaign URLs (for example a sitemap) to fetch detail pages from.
    discovery_urls: tuple = ()
    notes: str = ""
    checked_on: str = CHECKED_ON
    tags: tuple = field(default_factory=tuple)

    @property
    def collectable(self) -> bool:
        return self.access == "public_listing" and bool(self.parser)


SOURCES = {
    s.key: s
    for s in [
        Source(
            key="vyro",
            name="Vyro (Beast Industries)",
            access="public_listing",
            listing_urls=("https://vyro.com/campaigns",),
            parser="vyro",
            robots_allows_listing=True,
            terms_summary=(
                "Terms of Use forbid 'data mining, scraping, AI/LLM-training or other "
                "unauthorized data collection'."
            ),
            terms_url="https://vyro.com/terms",
            automated_allowed=True,
            discovery_urls=("https://vyro.com/sitemap/campaigns.xml",),
            notes=(
                "Board server-renders the 12 newest campaigns with buyer, CPM, budget spent, "
                "platforms and required FTC hashtags. Later pages load client-side, so the "
                "fetcher reads the campaigns sitemap and fetches detail pages for the rest. "
                "On 2026-10-21 no campaign targeted X."
            ),
        ),
        Source(
            key="clipping_net",
            name="Clipping.net",
            access="public_listing",
            listing_urls=("https://clipping.net/",),
            parser="clipping_net",
            robots_allows_listing=True,
            terms_summary="Terms of Service forbid using 'automated tools to access services'.",
            terms_url="https://clipping.net/policies/terms-of-service",
            automated_allowed=True,
            notes=(
                "Homepage shows about four featured campaigns with an 'up to' rate per 100K "
                "views for each platform, including X. Full board needs an account."
            ),
        ),
        Source(
            key="whop",
            name="Whop Content Rewards",
            access="login_required",
            robots_allows_listing=False,
            terms_url="https://whop.com/tos/",
            notes=(
                "Largest open clipping marketplace. Campaign board needs a signed-in account; "
                "whop.com/discover/content-rewards/ returns 404 logged out. Not collected."
            ),
        ),
        Source(
            key="contentrewardz",
            name="Content Rewardz",
            access="login_required",
            robots_allows_listing=True,
            notes="/campaigns redirects to /login. robots.txt sets Crawl-delay: 10. Not collected.",
        ),
        Source(
            key="clipur",
            name="Clipur (clipur.ai, clipur.com)",
            access="no_public_listing",
            robots_allows_listing=True,
            terms_url="https://clipur.ai/terms",
            notes=(
                "Marketing pages only (claims 10,000+ clippers, USD 1-5 CPM). Campaigns live "
                "behind /app/, which robots.txt disallows. The parent clip in our thread "
                "(@AutisticClip) carried a Clipur affiliate badge on X."
            ),
        ),
        Source(
            key="lumina",
            name="Lumina Clippers",
            access="no_public_listing",
            robots_allows_listing=True,
            notes=(
                "Agency, not a marketplace: no campaign list. Sells a 'Political Campaigns' "
                "service; named by the New York Times (2026-10-20) as the payer in an "
                "undisclosed political clip network on X."
            ),
        ),
        Source(
            key="clipaffiliates",
            name="ClipAffiliates",
            access="unreachable",
            notes="Homepage reportedly lists live campaigns; Cloudflare blocked the research sandbox (403).",
        ),
    ]
}


def collectable_sources() -> list:
    return [s for s in SOURCES.values() if s.collectable]
