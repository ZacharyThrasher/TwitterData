from clip_monitor import topics
from clip_monitor.models import Campaign


def test_politics_outranks_other_topics():
    primary, all_topics, kws = topics.tag("Senate debate night clips", "Example PAC", "#DebateNight")
    assert primary == "politics"
    assert "commentary" in all_topics
    assert "senate" in kws and "pac" in kws


def test_hashtag_camel_case_is_split():
    primary, _, kws = topics.tag("#TotalDramaRoblox")
    assert primary == "gaming" and "roblox" in kws


def test_joined_names_still_match():
    primary, _, _ = topics.tag("PlaqueBoyMax")
    assert primary == "streamer"


def test_whole_words_only():
    # "stake" must not fire inside "mistakes"; "ai" not inside "said"
    assert topics.tag("Funny mistakes she said")[0] == "other"


def test_apply_fills_campaign():
    c = Campaign(source="t", campaign_id="1", name="Stake Bounties", required_hashtags=["#ad"])
    topics.apply(c)
    assert c.topic == "gambling" and c.topics == ["gambling"] and c.topic_keywords == ["stake"]
