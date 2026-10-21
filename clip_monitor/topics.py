"""Keyword topic tags for campaigns.

Deliberately simple and transparent: a campaign gets every topic whose
keywords appear (whole-word, case-insensitive) in its name, buyer or required
hashtags. The primary `topic` is the first match in TOPIC_ORDER, which puts
the topics most relevant to the outrage question (politics, gambling, crypto)
first. Unmatched campaigns get "other". Review "other" rows by hand and add
keywords here rather than recoding rows.
"""

from __future__ import annotations

import re

TOPIC_KEYWORDS = {
    "politics": [
        "election", "senate", "senator", "congress", "congressman", "congresswoman",
        "governor", "mayor", "candidate", "campaign trail", "vote", "voter", "voters",
        "ballot", "primary", "democrat", "democrats", "republican", "republicans",
        "gop", "maga", "trump", "biden", "harris", "vance", "newsom", "desantis",
        "politics", "political", "pac", "super pac", "policy", "immigration",
        "border", "abortion", "tariff", "tariffs",
    ],
    "gambling": [
        "stake", "casino", "bet", "bets", "betting", "sportsbook", "gamble",
        "gambling", "slots", "poker", "roulette", "igaming", "aviator", "draftkings",
        "fanduel", "rainbet", "roobet", "shuffle",
    ],
    "crypto": [
        "crypto", "bitcoin", "btc", "ethereum", "eth", "solana", "token", "memecoin",
        "web3", "nft", "defi", "okx", "binance", "coinbase", "polkadot", "algorand",
    ],
    "commentary": [
        "news", "debate", "exposed", "reacts", "reaction", "reactions", "commentary",
        "rant", "hot take", "hot takes", "talk show", "drama alert", "beef", "cancelled",
        "canceled", "woke", "feminist", "feminism", "manosphere", "alpha",
    ],
    "podcast": ["podcast", "podcasts", "interview", "episode"],
    "streamer": [
        "streamer", "streamers", "stream", "kick", "twitch", "mrbeast", "ishowspeed",
        "speed", "adin", "asmongold", "xqc", "kai cenat", "plaqueboymax", "sketch",
    ],
    "gaming": [
        "roblox", "valorant", "fortnite", "minecraft", "call of duty", "gta",
        "gaming", "esports", "league of legends", "warzone",
    ],
    "music": ["music", "album", "song", "single", "rapper", "drake", "tour", "concert"],
    "brand": [
        "supplement", "app", "saas", "ai", "startup", "skincare", "fitness",
        "ketone", "energy drink", "shop", "store",
    ],
}

TOPIC_ORDER = [
    "politics", "gambling", "crypto", "commentary", "podcast", "streamer", "gaming", "music", "brand",
]

_PATTERNS = {
    topic: [(kw, re.compile(r"(?<![a-z0-9])" + re.escape(kw) + r"(?![a-z0-9])", re.I)) for kw in kws]
    for topic, kws in TOPIC_KEYWORDS.items()
}


def tag(*texts: str) -> tuple:
    """Return (primary_topic, all_topics, matched_keywords) for the given texts."""
    raw = " ".join(t for t in texts if t).replace("#", " ")
    # Match both the text as written ("PlaqueBoyMax") and with camelCase split
    # into words ("#TotalDramaRoblox" -> "Total Drama Roblox").
    haystack = raw + " | " + re.sub(r"(?<=[a-z])(?=[A-Z])", " ", raw)
    topics, keywords = [], []
    for topic in TOPIC_ORDER:
        for kw, pat in _PATTERNS[topic]:
            if pat.search(haystack):
                if topic not in topics:
                    topics.append(topic)
                keywords.append(kw)
    primary = topics[0] if topics else "other"
    return primary, topics or ["other"], keywords


def apply(campaign) -> None:
    """Fill campaign.topic / topics / topic_keywords in place."""
    primary, topics, keywords = tag(
        campaign.name, campaign.buyer, " ".join(campaign.required_hashtags)
    )
    campaign.topic = primary
    campaign.topics = topics
    campaign.topic_keywords = keywords
