"""Builders for synthetic X captures.

Everything here is invented. Ids are made-up snowflakes, handles are fake,
and SENTINEL marks every place a real capture would hold a session secret,
so tests can prove those values never reach any output.
"""

from __future__ import annotations

import base64
import json
from urllib.parse import quote

SENTINEL = "SENTINELSECRET0123456789abcdef"

FOCAL_ID = "2000000000000000100"
ROOT_ID = "2000000000000000001"  # the focal tweet replies to this root


def user(uid, handle, *, blue=False, followers=10, verified_type=None, affiliate=None,
         professional=None, layout="new"):
    if layout == "new":
        u = {
            "__typename": "User",
            "rest_id": uid,
            "is_blue_verified": blue,
            "core": {"screen_name": handle, "name": handle.title(),
                     "created_at": "Thu Oct 04 05:22:25 +0000 2012"},
            "relationship_counts": {"followers": followers, "following": 5},
            "tweet_counts": {"tweets": 100, "media_tweets": 3},
        }
    else:
        u = {
            "__typename": "User",
            "rest_id": uid,
            "is_blue_verified": blue,
            "legacy": {"screen_name": handle, "name": handle.title(),
                       "created_at": "Thu Oct 04 05:22:25 +0000 2012",
                       "followers_count": followers, "friends_count": 5, "statuses_count": 100},
        }
    if verified_type:
        u["verification"] = {"verified_type": verified_type}
    if affiliate:
        u["affiliates_highlighted_label"] = {"label": {"description": affiliate}}
    if professional:
        u["professional"] = {"professional_type": professional}
    return u


def tweet(tid, author, *, reply_to=None, text="hello", likes=1, views=10, conversation=ROOT_ID,
          wrap_visibility=False, media=False):
    legacy = {
        "id_str": tid,
        "full_text": text,
        "created_at": "Tue Oct 20 18:37:59 +0000 2026",
        "conversation_id_str": conversation,
        "in_reply_to_status_id_str": reply_to,
        "lang": "en",
        "favorite_count": likes,
        "reply_count": 0,
        "retweet_count": 0,
        "quote_count": 0,
        "bookmark_count": 0,
        "is_quote_status": False,
        "user_id_str": author["rest_id"],
    }
    if media:
        legacy["extended_entities"] = {"media": [{"type": "photo"}]}
    t = {
        "__typename": "Tweet",
        "rest_id": tid,
        "core": {"user_results": {"result": author}},
        "views": {"count": str(views), "state": "EnabledWithCount"},
        "legacy": legacy,
    }
    if wrap_visibility:
        return {"__typename": "TweetWithVisibilityResults", "tweet": t}
    return t


def _item(tweet_obj, section="HighQuality", promoted=False):
    content = {"itemType": "TimelineTweet", "__typename": "TimelineTweet",
               "tweet_results": {"result": tweet_obj}}
    if promoted:
        content["promotedMetadata"] = {"advertiser_results": {}, "impressionId": "x"}
    return {"itemContent": content,
            "clientEventInfo": {"details": {"conversationDetails": {"conversationSection": section}}}}


def module(entry_suffix, tweets, sort_index, section="HighQuality", promoted_positions=()):
    return {
        "entryId": f"conversationthread-{entry_suffix}",
        "sortIndex": str(sort_index),
        "content": {
            "entryType": "TimelineTimelineModule",
            "items": [{"entryId": f"conversationthread-{entry_suffix}-tweet-{i}",
                       "item": _item(t, section, promoted=i in promoted_positions)}
                      for i, t in enumerate(tweets)],
        },
    }


def tweet_entry(tweet_obj, sort_index):
    tid = tweet_obj.get("rest_id") or tweet_obj["tweet"]["rest_id"]
    return {"entryId": f"tweet-{tid}", "sortIndex": str(sort_index),
            "content": {"entryType": "TimelineTimelineItem", "itemContent": {
                "itemType": "TimelineTweet", "tweet_results": {"result": tweet_obj}}}}


def promoted_entry(tweet_obj, sort_index):
    return {"entryId": f"promoted-tweet-{tweet_obj['rest_id']}", "sortIndex": str(sort_index),
            "content": {"entryType": "TimelineTimelineItem", "itemContent": {
                "itemType": "TimelineTweet", "tweet_results": {"result": tweet_obj},
                "promotedMetadata": {"impressionId": "y"}}}}


def tombstone_module(entry_suffix, sort_index):
    return {"entryId": f"conversationthread-{entry_suffix}", "sortIndex": str(sort_index),
            "content": {"entryType": "TimelineTimelineModule", "items": [{
                "entryId": "t", "item": {"itemContent": {
                    "itemType": "TimelineTweet",
                    "tweet_results": {"result": {"__typename": "TweetTombstone"}}}}}]}}


def cursor_entry(sort_index):
    return {"entryId": f"cursor-bottom-{sort_index}", "sortIndex": str(sort_index),
            "content": {"entryType": "TimelineTimelineItem", "itemContent": {
                "itemType": "TimelineTimelineCursor", "value": f"cursor-{sort_index}", "cursorType": "Bottom"}}}


def body(entries=(), module_items=None):
    instructions = [{"type": "TimelineClearCache"}]
    if entries:
        instructions.append({"type": "TimelineAddEntries", "entries": list(entries)})
    if module_items:
        instructions.append({"type": "TimelineAddToModule",
                             "moduleEntryId": module_items[0],
                             "moduleItems": [{"entryId": f"m-{i}", "item": _item(t)}
                                             for i, t in enumerate(module_items[1])]})
    return {"data": {"threaded_conversation_with_injections_v2": {"instructions": instructions}}}


def tweetdetail_url(focal_id=FOCAL_ID, ranking_mode="Relevance", cursor=None, host="x.com"):
    variables = {"focalTweetId": focal_id, "with_rux_injections": False, "includePromotedContent": True,
                 "withCommunity": True}
    if ranking_mode:
        variables["rankingMode"] = ranking_mode
    if cursor:
        variables["cursor"] = cursor
    return (f"https://{host}/i/api/graphql/AbC-123_xyz/TweetDetail?variables="
            f"{quote(json.dumps(variables))}&features={quote(json.dumps({'f': True}))}")


def secret_headers():
    return [
        {"name": "authorization", "value": f"Bearer AAAAAAAAAAAAAAAAAAAAA{SENTINEL}"},
        {"name": "x-csrf-token", "value": SENTINEL},
        {"name": "cookie", "value": f"auth_token={SENTINEL}; ct0={SENTINEL}; twid=u%3D{SENTINEL}"},
    ]


def har_entry(url, response_body, *, status=200, started="2026-10-21T13:33:13.123Z", base64_body=False):
    text = json.dumps(response_body) if not isinstance(response_body, str) else response_body
    content = {"size": len(text), "mimeType": "application/json"}
    if base64_body:
        content["text"] = base64.b64encode(text.encode()).decode()
        content["encoding"] = "base64"
    else:
        content["text"] = text
    return {
        "startedDateTime": started,
        "request": {
            "method": "GET",
            "url": url,
            "headers": secret_headers(),
            "cookies": [{"name": "auth_token", "value": SENTINEL}, {"name": "ct0", "value": SENTINEL}],
            "queryString": [{"name": "variables", "value": SENTINEL}],
        },
        "response": {
            "status": status,
            "headers": [{"name": "set-cookie", "value": f"ct0={SENTINEL}; Path=/"}],
            "cookies": [{"name": "ct0", "value": SENTINEL}],
            "content": content,
        },
    }


def har(entries):
    return {"log": {"version": "1.2", "creator": {"name": "synthetic"}, "entries": list(entries)}}


# A small cast of fake accounts.
OP = user("1000", "OriginalPoster", blue=True, followers=55953, verified_type="Business",
          affiliate="Example Clips Inc", professional="Creator")
ROOT_AUTHOR = user("999", "RootAuthor", followers=7)
BLUE = user("1001", "BlueReplier", blue=True, followers=500)
FREE = user("1002", "FreeReplier", followers=20)
SPAMMY = user("1003", "Spammy12345", followers=1)
LATE = user("1004", "LateReplier", followers=3, layout="legacy")
ADVERTISER = user("1005", "BrandAds", blue=True, verified_type="Business")

FOCAL = tweet(FOCAL_ID, OP, reply_to=ROOT_ID, text="focal post", likes=900, views=40000)
ROOT = tweet(ROOT_ID, ROOT_AUTHOR, text="root post")
REPLY_A = tweet("2000000000000000201", BLUE, reply_to=FOCAL_ID, text="blue reply", likes=50, views=900)
NESTED_OP = tweet("2000000000000000202", OP, reply_to="2000000000000000201", text="op answers")
REPLY_B = tweet("2000000000000000203", FREE, reply_to=FOCAL_ID, text="free reply", likes=80, views=300,
                wrap_visibility=True, media=True)
REPLY_SPAM = tweet("2000000000000000204", SPAMMY, reply_to=FOCAL_ID, text="spam reply", likes=0)
REPLY_C = tweet("2000000000000000205", LATE, reply_to=FOCAL_ID, text="late reply", likes=2)
NESTED_LATE = tweet("2000000000000000206", FREE, reply_to="2000000000000000205", text="nested via module")
AD = tweet("2000000000000000300", ADVERTISER, text="buy things", conversation="2000000000000000300")
AD2 = tweet("2000000000000000301", ADVERTISER, text="buy more", conversation="2000000000000000301")


def page_top():
    """First page of the thread in relevance order."""
    return body([
        tweet_entry(ROOT, 9999),
        tweet_entry(FOCAL, 9998),
        module("a", [REPLY_A, NESTED_OP], 9000),
        promoted_entry(AD, 8900),
        module("b", [REPLY_B], 8800),
        tombstone_module("gone", 8700),
        module("spam", [REPLY_SPAM], 8600, section="LowQuality"),
        cursor_entry(1),
    ])


def page_next():
    """Second page: one new reply, one repeat, and an expanded module."""
    return body([
        module("c", [REPLY_C], 7000),
        module("a2", [REPLY_A], 6900),
        module("ad", [AD2], 6800, promoted_positions=(0,)),
        cursor_entry(2),
    ], module_items=("conversationthread-c", [NESTED_LATE]))


def page_likes():
    return body([
        tweet_entry(ROOT, 9999),
        tweet_entry(FOCAL, 9998),
        module("b", [REPLY_B], 9000),
        module("a", [REPLY_A], 8000),
    ])


def standard_har():
    """A capture holding two thread loads plus the noise a real HAR has."""
    return har([
        {"startedDateTime": "2026-10-21T13:30:00.000Z",
         "request": {"method": "GET", "url": f"https://example.com/?token={SENTINEL}",
                     "headers": secret_headers(), "cookies": []},
         "response": {"status": 200, "headers": [],
                      "content": {"mimeType": "text/html", "text": f"<html>{SENTINEL}</html>"}}},
        har_entry("https://x.com/i/api/graphql/Zz9/Viewer?variables=%7B%7D",
                  {"data": {"viewer": {"token": SENTINEL}}}),
        har_entry(tweetdetail_url(cursor=None), page_top(), started="2026-10-21T13:33:13.123Z"),
        har_entry(tweetdetail_url(cursor=SENTINEL), page_next(), started="2026-10-21T13:33:20.000Z"),
        har_entry(tweetdetail_url(cursor=SENTINEL), {"errors": [{"message": "Rate limit"}]}, status=429),
        har_entry(tweetdetail_url(ranking_mode="Likes"), page_likes(), started="2026-10-21T13:40:00.000Z",
                  base64_body=True),
        har_entry(tweetdetail_url(focal_id=FOCAL_ID).replace("TweetDetail", "TweetResultByRestId"),
                  {"data": {"tweetResult": {"result": FOCAL}}}),
    ])
