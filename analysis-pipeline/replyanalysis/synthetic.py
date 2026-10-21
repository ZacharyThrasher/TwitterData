"""Synthetic study data with known effects, for tests and the demo.

Every file it writes has the same shape as the real inputs: one reply table
per capture (schema v1), the tracker's threads.csv and captures.csv, reply
codes, root codes and an author file. Nothing here is real: ids, hashes and
counts are random.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from .schema import column_names

TOPICS = ["politics_government", "social_culture_war", "streamer_gaming", "sports", "news_events", "entertainment_celebrity"]
ACCOUNT_TYPES = ["paid_clipper", "organic_creator", "news_official"]
POLITICS = ["left", "right", "none_unclear"]
# Capture plan v1.1 (pre-registration amendment 2026-10-21): 6h and 24h, Relevance and Likes.
AGES = {"h06": 6.0, "h24": 24.0}
SORTS = ["relevance", "likes"]
WORDS = ("money award stream clip charity rigged show friend stunt fair joke point really never always "
         "people think honest views donate offer cringe based ratio take bad good sure").split()


@dataclass
class Effects:
    """Data-generating effects. Set any to 0 for a null world."""

    premium_boost: float = 3.0          # latent ranking score units under Relevance
    premium_like_boost: float = 1.0     # Premium replies draw extra likes (popularity, not placement)
    premium_wall: bool = False          # True: every Premium reply above every free one
    incivility_penalty: float = 1.0     # latent score units, within tier
    large_extra_penalty: float = 1.0    # multiplier added above 250k followers (T3)
    second_lang_factor: float = 0.2     # share of the penalty applied to Spanish replies (T10)
    outrage_reach: float = 0.5          # log views per follower (O1)
    clipper_outrage_logit: float = 1.5  # log-odds (O2)
    insult_penalty: float = 0.6         # reach lost by small-account insults (T9)
    insult_large_rescue: float = 0.6    # reach given back to large accounts (T9)
    contagion: float = 0.15             # extra incivility probability after a rude Premium top reply (A2)
    pileon_follower_growth: float = 0.05  # extra log-follower growth per day (A3)
    silencing: float = 0.6              # share of posting rate kept by piled-on pushback repliers (A4)
    pods: int = 1                       # number of 5-account reply pods (A7)


def null_effects() -> Effects:
    """A world with no planted effects."""
    zero = {k: 0 for k in Effects.__dataclass_fields__ if k not in ("premium_wall", "second_lang_factor", "silencing")}
    return Effects(**zero, second_lang_factor=1.0, silencing=1.0)


def _hash(*parts) -> str:
    return hashlib.sha256(":".join(map(str, parts)).encode()).hexdigest()[:24]


def _iso(ts: pd.Timestamp) -> str:
    return ts.strftime("%Y-%m-%dT%H:%M:%S.") + f"{ts.microsecond // 1000:03d}Z"


def generate(n_threads: int = 40, seed: int = 1, effects: Effects | None = None, include_text: bool = False,
             replies_per_thread: tuple[int, int] = (60, 140), viewer: str = "A") -> dict[str, pd.DataFrame]:
    fx = effects or Effects()
    rng = np.random.default_rng(seed)
    start = pd.Timestamp("2026-11-02T00:00:00Z")
    pod_members = [[_hash("pod", p, k) for k in range(5)] for p in range(fx.pods)]

    reply_rows, code_rows, thread_rows, root_rows, capture_rows = [], [], [], [], []
    authors: dict[str, dict] = {}

    for ti in range(n_threads):
        tid = str(2112000000000000000 + ti * 10_000_000)
        topic = TOPICS[ti % len(TOPICS)]
        acct = ACCOUNT_TYPES[(ti // len(TOPICS)) % len(ACCOUNT_TYPES)]
        lang = "es" if ti % 7 == 6 else "en"
        large = bool(rng.random() < 0.5)
        followers = int(rng.uniform(300_000, 3_000_000) if large else rng.uniform(15_000, 240_000))
        outrage = int(rng.random() < 1 / (1 + np.exp(-(-0.7 + (fx.clipper_outrage_logit if acct == "paid_clipper" else 0)))))
        insult = int(rng.random() < 0.4)
        posted = start + pd.Timedelta(hours=float(rng.uniform(0, 24 * 40)))
        log_vpf = (0.0 + fx.outrage_reach * outrage - fx.insult_penalty * insult
                   + fx.insult_large_rescue * insult * large + rng.normal(0, 0.3))
        root_views_24 = followers * np.exp(log_vpf)
        thread_rows.append({
            "thread_id": tid, "candidate_id": f"C{ti:04d}", "poster_handle": "", "poster_followers": followers,
            "posted_utc": _iso(posted), "selected_utc": _iso(posted + pd.Timedelta(minutes=20)), "session_id": "S0001",
            "source": "seed", "topic": topic, "account_type": acct, "poster_politics": POLITICS[int(rng.integers(3))],
            "language": lang, "follower_band": "250k_plus" if large else "under_250k", "cell": f"{topic}|{acct}",
            "selection_reason": "synthetic", "status": "complete", "status_reason": "",
        })
        root_rows.append({"thread_id": tid, "outrage_framing": outrage, "targeted_insult": insult,
                          "poster_motive": "farmer" if acct == "paid_clipper" else "ideologue"})
        focal_hash = _hash("author", "focal", ti)

        # Reply pool for the thread.
        n = int(rng.integers(*replies_per_thread))
        created_h = np.sort(np.minimum(rng.exponential(4.0, n), 23.5)) + 0.01
        rude_top_seed = rng.random() < 0.5  # half the threads get an early rude Premium reply
        pool = []
        for k in range(n):
            premium = int(rng.random() < 0.15)
            uncivil = int(rng.random() < 0.3)
            if k == 0 and rude_top_seed:
                premium, uncivil, created_h[k] = 1, 1, 0.05
            pool.append({
                "tweet_id": str(int(tid) + 10_000 + k), "created_h": float(created_h[k]),
                "author": _hash("author", ti, k), "premium": premium, "uncivil": uncivil,
                "quality": float(rng.normal()), "lang": lang if rng.random() < 0.95 else ("en" if lang == "es" else "es"),
                "stance": rng.choice(["pro", "anti", "neutral"], p=[0.45, 0.35, 0.2]),
                "pushback": int(rng.random() < 0.3), "followers0": int(rng.lognormal(6, 1.5)),
                "statuses0": int(rng.lognormal(8, 1)), "post_rate": float(rng.lognormal(2, 0.5)),
            })
        # Contagion: replies written after 1h in rude-top threads are ruder.
        if rude_top_seed and fx.contagion:
            for p in pool:
                if p["created_h"] > 1.0 and not p["uncivil"] and rng.random() < fx.contagion:
                    p["uncivil"] = 1
        # Reply pods: the same accounts reply within seconds in the first threads.
        for pi, members in enumerate(pod_members):
            if ti % max(fx.pods, 1) == pi % max(fx.pods, 1) and ti < 8 * fx.pods:
                t0 = float(rng.uniform(0.2, 0.8))
                for m_i, m in enumerate(members):
                    pool.append({**pool[0], "tweet_id": str(int(tid) + 500_000 + pi * 10 + m_i), "author": m,
                                 "created_h": t0 + m_i * 4 / 3600, "premium": 0, "uncivil": 0, "quality": 0.0,
                                 "lang": lang, "pushback": 0})
        for p in pool:
            p["piled_on"] = int(p["pushback"] and rng.random() < 0.5)
            p["attacks_op"] = int(p["uncivil"] and rng.random() < 0.5)
            p["nested"] = []
            if rng.random() < 0.25:
                for j in range(int(rng.integers(1, 3))):
                    by_op = rng.random() < 0.2
                    nested_uncivil = int(p["piled_on"] or rng.random() < 0.2) if not by_op else 0
                    p["nested"].append({"tweet_id": str(int(p["tweet_id"]) + 1_000_000 * (j + 1)),
                                        "author": focal_hash if by_op else _hash("nested", p["tweet_id"], j),
                                        "by_op": by_op, "uncivil": nested_uncivil})
            if p["piled_on"] and not p["nested"]:
                p["nested"].append({"tweet_id": str(int(p["tweet_id"]) + 1_000_000), "author": _hash("nested", p["tweet_id"], 0),
                                    "by_op": False, "uncivil": 1})
            code_rows.append({"tweet_id": p["tweet_id"], "incivility": p["uncivil"],
                              "attacks_op": p["attacks_op"],
                              "stance": p["stance"], "pushback": p["pushback"],
                              "toxicity": float(np.clip(0.15 + 0.5 * p["uncivil"] + rng.normal(0, 0.1), 0, 1))})
            for nr in p["nested"]:
                code_rows.append({"tweet_id": nr["tweet_id"], "incivility": nr["uncivil"], "attacks_op": 0,
                                  "stance": "neutral", "pushback": 0, "toxicity": 0.2 + 0.5 * nr["uncivil"]})
            authors.setdefault(p["author"], {
                "author_id_hash": p["author"], "motive": "farmer" if p["premium"] and rng.random() < 0.5 else "ideologue",
                "account_based_in": "united states", "claimed_location": rng.choice(["united states", "texas, united states", "nigeria"]),
            })

        for age, hours in AGES.items():
            cap_time = posted + pd.Timedelta(hours=hours)
            visible = [p for p in pool if p["created_h"] < hours]
            focal_views = int(root_views_24 * np.sqrt(hours / 24))
            # Relevance order decides views; all three sorts at one age share those views.
            for p in visible:
                frac = min(1.0, (hours - p["created_h"]) / 6)
                p["likes"] = int(rng.poisson(np.exp(1.0 + 0.8 * p["quality"]) * frac * (1 + fx.premium_like_boost * p["premium"])))
                pen = fx.incivility_penalty * (1 + fx.large_extra_penalty * large)
                if p["lang"] == "es":
                    pen *= fx.second_lang_factor
                p["score"] = (fx.premium_boost * p["premium"] + 0.8 * np.log1p(p["likes"]) + 0.3 * p["quality"]
                              - pen * p["uncivil"] + rng.normal(0, 0.5))
            rel = sorted(visible, key=lambda p: (-(p["premium"] if fx.premium_wall else 0), -p["score"]))
            for r_i, p in enumerate(rel):
                p["views"] = int(focal_views * 0.03 * np.exp(-r_i / 25) * rng.lognormal(0, 0.3)) + 1
            orders = {
                "relevance": rel,
                "likes": sorted(visible, key=lambda p: -p["likes"]),
            }
            for sort in SORTS:
                cid = f"{tid}_{age}_{sort}_{viewer}"
                capture_rows.append({"capture_id": cid, "thread_id": tid, "age_hours": int(hours), "sort": sort,
                                     "viewer": viewer, "status": "done", "captured_utc": _iso(cap_time),
                                     "file_ref": f"captures/{cid}.csv", "n_replies_captured": len(orders[sort][:200])})
                base = {
                    "schema_version": "1", "platform": "x", "capture_id": cid, "capture_file": f"{cid}.json",
                    "capture_session": 1, "capture_time_utc": _iso(cap_time), "page_index": 0, "viewer_type": "free",
                    "viewer_label": viewer, "sort_order": sort, "sort_order_source": "request", "age_bucket": age,
                    "thread_id": tid, "focal_tweet_id": tid, "focal_author_id_hash": focal_hash,
                    "focal_author_followers": followers, "focal_author_is_blue_verified": "true" if acct != "news_official" else "false",
                    "focal_author_verified_type": None, "focal_author_affiliate_label": "Clipur" if acct == "paid_clipper" else None,
                    "focal_view_count": focal_views, "focal_like_count": int(focal_views * 0.01),
                    "focal_reply_count": len(visible), "rank_is_absolute": "true",
                }
                idx, rank = 0, 0
                for p in orders[sort][:200]:
                    rank += 1
                    idx += 1
                    if rank == 6:  # one ad per list
                        reply_rows.append(_row(base, idx, None, "promoted", 0, {"tweet_id": str(int(tid) + 9_000_000 + idx),
                                               "author": _hash("ad", ti), "created_h": 0.0, "premium": 1, "lang": "en",
                                               "likes": 3, "views": 1000}, posted, hours, rng, include_text))
                        idx += 1
                    reply_rows.append(_row(base, idx, rank, "reply", 0, p, posted, hours, rng, include_text, fx))
                    for j, nr in enumerate(p["nested"]):
                        idx += 1
                        nested = {**p, "tweet_id": nr["tweet_id"], "author": nr["author"], "premium": 0,
                                  "created_h": min(p["created_h"] + 0.1, hours - 0.01), "likes": 1, "views": max(p["views"] // 5, 1)}
                        reply_rows.append(_row(base, idx, None, "nested_reply", j + 1, nested, posted, hours, rng,
                                               include_text, fx, by_op=nr["by_op"], in_reply_to=p["tweet_id"]))

    replies = pd.DataFrame(reply_rows)[column_names()]
    return {
        "replies": replies,
        "codes": pd.DataFrame(code_rows).drop_duplicates("tweet_id"),
        "threads": pd.DataFrame(thread_rows),
        "root_codes": pd.DataFrame(root_rows),
        "authors": pd.DataFrame(list(authors.values())),
        "captures": pd.DataFrame(capture_rows),
    }


def _row(base, idx, rank, row_type, module_pos, p, posted, hours, rng, include_text, fx: Effects | None = None,
         by_op=False, in_reply_to=None):
    created = posted + pd.Timedelta(hours=p["created_h"])
    age_days = max(hours - p.get("created_h", 0), 0) / 24
    followers0 = p.get("followers0", 100)
    statuses0 = p.get("statuses0", 1000)
    growth = 0.0
    rate = p.get("post_rate", 5.0)
    if fx is not None and row_type == "reply":
        if p.get("premium") and p.get("attacks_op"):
            growth = fx.pileon_follower_growth
        if p.get("piled_on"):
            rate *= fx.silencing
    followers = int(round(followers0 * np.exp((0.01 + growth) * hours / 24)))
    statuses = int(statuses0 + rate * hours / 24)
    return {
        **base,
        "row_type": row_type, "is_promoted": "true" if row_type == "promoted" else "false",
        "display_rank": rank, "display_index": idx, "module_position": module_pos,
        "conversation_section": "HighQuality", "sort_index": str(10**18 - idx),
        "tweet_id": p["tweet_id"], "in_reply_to_tweet_id": in_reply_to or base["focal_tweet_id"],
        "created_at_utc": _iso(created), "lang": p.get("lang", "en"), "is_quote": "false", "has_media": "false",
        "view_count": p.get("views"), "like_count": p.get("likes", 0), "reply_count": len(p.get("nested", [])),
        "repost_count": 0, "quote_count": 0, "bookmark_count": 0,
        "text": (" ".join(rng.choice(WORDS, 10)) if include_text else None),
        "author_id_hash": p["author"], "author_handle_hash": _hash("handle", p["author"]),
        "author_is_focal_author": "true" if by_op else "false",
        "author_is_blue_verified": "true" if p.get("premium") else "false",
        "author_verified_type": None, "author_affiliate_label": None, "author_professional_type": None,
        "author_followers": followers, "author_following": 200, "author_statuses": statuses,
        "author_created_at_utc": "2020-01-01T00:00:00.000Z",
    }


def write_dataset(out_dir: str | Path, data: dict[str, pd.DataFrame], overwrite: bool = False) -> dict[str, Path]:
    """Write the synthetic study the way the real one is laid out on disk."""
    out = Path(out_dir)
    old = list((out / "captures").glob("*.csv"))
    if old:
        if not overwrite:
            raise FileExistsError(f"{out / 'captures'} already holds reply tables; pass overwrite=True")
        for f in old:
            f.unlink()
    (out / "captures").mkdir(parents=True, exist_ok=True)
    for cid, g in data["replies"].groupby("capture_id"):
        g.to_csv(out / "captures" / f"{cid}.csv", index=False)
    paths = {"captures_dir": out / "captures"}
    for name in ("codes", "threads", "root_codes", "authors", "captures"):
        path = out / f"{name}.csv"
        data[name].to_csv(path, index=False)
        paths[name] = path
    return paths
