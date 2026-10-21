from clip_monitor import clipper_rule as rule


def acct(**kw):
    base = {
        "screen_name": "someone",
        "name": "Some One",
        "description": "",
        "professional_type": "",
        "affiliate_badge": "",
        "is_blue_verified": "False",
        "statuses_count": "1000",
        "media_tweets_count": "100",
    }
    base.update(kw)
    return base


def test_marketplace_affiliate_badge_confirms():
    t = rule.tag_account(acct(affiliate_badge="Clipur.ai"))
    assert t.tier == "paid_confirmed"
    assert "affiliate_badge_marketplace" in t.signals


def test_unrelated_affiliate_badge_does_not_confirm():
    assert rule.tag_account(acct(affiliate_badge="Some Newspaper")).tier == "none"


def test_campaign_hashtag_in_post_confirms():
    t = rule.tag_account(acct(texts=["lol watch this #MW4partner"]), {"#mw4partner"})
    assert t.tier == "paid_confirmed"
    assert t.matched_campaign_tags == ["#mw4partner"]


def test_generic_disclosure_alone_is_not_enough():
    t = rule.tag_account(acct(texts=["great clip #ad"]), {"#mw4partner"})
    assert t.tier == "none"
    assert "generic_disclosure_hashtag" in t.signals


def test_doc_example_clip_pod_accounts():
    # Shapes of the three clip accounts that replied first under the parent clip
    # (see docs/clip-monitor/PAID_CLIPPER_RULE.md, worked examples). Handles are
    # stand-ins: the project does not publish ordinary repliers' handles.
    josh = acct(
        screen_name="replier_a",
        description="not impersonating anybody || daily streamers clips, Reactions too || DM for Ads/ Promo",
        professional_type="Business",
        is_blue_verified="True",
    )
    dirk = acct(
        screen_name="replier_mp4",
        description="Follow for Clips || Clipping All Streamers || DM for submissions || Not Impersonating",
        is_blue_verified="True",
    )
    sum_ = acct(
        screen_name="replierclipper",
        description="Streaming the chaos you missed, one epic moment at a time",
        professional_type="Business",
        is_blue_verified="True",
    )
    for a in (josh, dirk, sum_):
        assert rule.tag_account(a).tier == "paid_likely", a["screen_name"]


def test_single_medium_signal_is_only_possible():
    t = rule.tag_account(acct(screen_name="bestclips"))
    assert t.tier == "clip_possible"


def test_premium_alone_does_not_lift_a_medium_signal():
    t = rule.tag_account(acct(screen_name="bestclips", is_blue_verified="True"))
    assert t.tier == "clip_possible"


def test_media_heavy_account_supports():
    t = rule.tag_account(acct(screen_name="bestclips", statuses_count="1000", media_tweets_count="700"))
    assert t.tier == "paid_likely"
    assert "media_share_50pct" in t.signals


def test_false_friends_do_not_match():
    assert rule.tag_account(acct(name="ECLIPSE12345")).tier == "none"
    assert rule.tag_account(acct(name="LA Clippers fan")).tier == "none"


def test_campaign_hashtags_from_snapshot_rows_drop_generic():
    rows = [{"required_hashtags": "#paidpartnership;#TotalDramaRoblox"}, {"required_hashtags": "#ad"}, {}]
    assert rule.campaign_hashtags(rows) == {"#totaldramaroblox"}
