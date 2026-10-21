from conftest import fixture_text

from clip_monitor.parsers import clipping_net, vyro
from clip_monitor.parsers.common import parse_count, parse_money, per_1k


def by_id(campaigns):
    return {c.campaign_id: c for c in campaigns}


def test_money_and_rate_helpers():
    assert parse_money("$2,100") == 2100
    assert parse_money("$1.5K") == 1500
    assert parse_money("no price") is None
    assert parse_count("100K") == 100_000
    assert parse_count("1.2M") == 1_200_000
    assert per_1k(2100, "per 1M views") == 2.1
    assert per_1k(300, "Up to per 100k") == 3
    assert per_1k(1.5, "per 1,000 views") == 1.5
    assert per_1k(5, "per post") is None


def test_vyro_board_json_fields():
    cs = by_id(vyro.parse(fixture_text("vyro_board.html"), url="https://vyro.com/campaigns"))
    c = cs["vyro:Ab12Cd34"]
    assert c.buyer == "Example PAC"
    assert c.name == "Senate debate night clips"
    assert c.payout_model == "cpm"
    assert c.rate_per_1k_usd == 3.25
    assert c.platforms == ["instagram", "tiktok", "x"]
    assert c.targets_x is True
    assert c.budget_total_usd == 20000 and c.budget_spent_usd == 5000.5
    assert c.required_hashtags == ["#paidpartnership", "#DebateNight"]
    assert c.min_views_per_clip == 5000
    assert c.end_date.startswith("2026-11-03")
    assert c.url == "https://vyro.com/campaigns/debate-night-clips-Ab12Cd34"


def test_vyro_board_platform_rates_and_range_flag():
    c = by_id(vyro.parse(fixture_text("vyro_board.html")))["vyro:Zz99Yy88"]
    assert c.platform_rates_per_1k == {"youtube": 1.05}
    assert c.rate_is_max is True
    assert c.is_locked is True
    assert c.targets_x is False


def test_vyro_board_falls_back_to_cards_for_campaigns_missing_from_json():
    cs = by_id(vyro.parse(fixture_text("vyro_board.html")))
    assert len(cs) == 3  # two from JSON, one card-only; the "Back to campaigns" link is ignored
    c = cs["vyro:Qq77Rr66"]
    assert c.buyer == "Example Casino"
    assert c.name == "Big win reactions"
    assert c.rate_per_1k_usd == 4.0
    assert c.platforms_known is False
    assert c.targets_x is None  # unknown, not "no"
    assert c.is_locked is True


def test_vyro_board_json_wins_over_card_for_same_campaign():
    c = by_id(vyro.parse(fixture_text("vyro_board.html")))["vyro:Ab12Cd34"]
    assert c.budget_total_usd == 20000  # only the JSON has budgets


def test_vyro_detail_page():
    [c] = vyro.parse(fixture_text("vyro_detail.html"), url="https://vyro.com/campaigns/rally-highlights-Mm55Nn44")
    assert c.campaign_id == "vyro:Mm55Nn44"
    assert c.name == "Rally highlights"
    assert c.buyer == "Example Campaign HQ"
    assert c.rate_per_1k_usd == 2.1
    assert c.platforms == ["instagram", "x"]


def test_vyro_detail_detected_without_url():
    [c] = vyro.parse(fixture_text("vyro_detail.html"))
    assert c.campaign_id == "vyro:Mm55Nn44"


def test_vyro_unrelated_page_gives_nothing():
    assert vyro.parse("<html><body><h1>Hello</h1></body></html>") == []


def test_clipping_net_cards():
    cs = clipping_net.parse(fixture_text("clipping_net_home.html"), observed_at="2026-10-21T12:00:00Z")
    assert len(cs) == 2  # carousel duplicate dropped
    sb, rap = cs
    assert sb.name == "Example Sportsbook Bounties"
    assert sb.payout_model == "cpm"
    assert sb.platform_rates_per_1k == {"tiktok": 3.0, "x": 2.5}
    assert sb.rate_per_1k_usd == 3.0 and sb.rate_is_max is True
    assert sb.platforms == ["tiktok", "x"] and sb.targets_x is True
    assert sb.min_views_per_clip == 10_000
    assert sb.status == "active"
    assert sb.end_date == "2026-11-30"

    assert rap.payout_model == "bounty"
    assert rap.rate_per_1k_usd is None
    assert rap.budget_total_usd == 4000
    assert rap.targets_x is False
    assert rap.min_views_per_clip == 500_000


def test_clipping_net_end_date_blank_without_observation_time():
    cs = clipping_net.parse(fixture_text("clipping_net_home.html"))
    assert cs[0].end_date == ""


def test_vyro_null_pay_rate_falls_back_to_headline():
    import json
    item = {"id": "1", "slug": "a-Aa11Bb22", "name": "n", "payoutModel": {"model": "CPM", "payRate": None}, "headlineRate": 2.5}
    payload = '0:{"initialPage":' + json.dumps({"data": [item]}) + "}"
    page = "<script>self.__next_f.push([1,%s])</script>" % json.dumps(payload)
    [c] = vyro.parse(page)
    assert c.rate_per_1k_usd == 2.5


def test_vyro_detail_with_related_cards_and_no_url_is_a_detail():
    page = fixture_text("vyro_detail.html").replace(
        "</body>", '<a href="/campaigns/other-Xx11Yy22"><h3>Other</h3><p>Other</p><span>$1,000</span><span>Per 1M Views</span></a></body>'
    )
    [c] = vyro.parse(page)
    assert c.campaign_id == "vyro:Mm55Nn44"


def test_clipping_net_singular_day_left():
    page = fixture_text("clipping_net_home.html").replace("40<!-- --> days left", "1<!-- --> day left", 1)
    cs = clipping_net.parse(page, observed_at="2026-10-21T12:00:00Z")
    assert cs[0].end_date == "2026-10-22"
