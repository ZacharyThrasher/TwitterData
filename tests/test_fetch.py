import io

import pytest

from clip_monitor.fetch import NotPermitted, PoliteFetcher, USER_AGENT
from clip_monitor.sources import SOURCES, Source


class FakeResp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class FakeOpener:
    def __init__(self, pages):
        self.pages = pages
        self.requests = []

    def open(self, req, timeout=None):
        self.requests.append(req)
        if req.full_url not in self.pages:
            raise OSError("404")
        return FakeResp(self.pages[req.full_url])


class Clock:
    def __init__(self):
        self.t = 0.0
        self.slept = []

    def now(self):
        return self.t

    def sleep(self, s):
        self.slept.append(s)
        self.t += s


ALLOWED = Source(key="ok", name="Permitted site", access="public_listing", parser="vyro",
                 automated_allowed=True, permission_note="test")


def make(pages, interval=10):
    clock = Clock()
    opener = FakeOpener(pages)
    return PoliteFetcher(min_interval=interval, opener=opener, sleep=clock.sleep, clock=clock.now), opener, clock


def test_registry_has_no_automated_sources_by_default():
    assert not any(s.automated_allowed for s in SOURCES.values())


def test_refuses_source_without_permission():
    f, opener, _ = make({})
    with pytest.raises(NotPermitted):
        f.fetch(SOURCES["vyro"], "https://vyro.com/campaigns")
    assert opener.requests == []  # not even robots.txt is requested


def test_respects_robots_disallow():
    f, _, _ = make({"https://e.com/robots.txt": b"User-agent: *\nDisallow: /private\n"})
    with pytest.raises(NotPermitted):
        f.fetch(ALLOWED, "https://e.com/private/list")


def test_missing_robots_means_no():
    f, _, _ = make({"https://e.com/list": b"<html></html>"})
    with pytest.raises(NotPermitted):
        f.fetch(ALLOWED, "https://e.com/list")


def test_min_interval_applies_without_crawl_delay():
    pages = {"https://e.com/robots.txt": b"User-agent: *\nAllow: /\n", "https://e.com/a": b"A"}
    f, _, clock = make(pages, interval=10)
    f.fetch(ALLOWED, "https://e.com/a")
    assert clock.slept == [10]


def test_rate_limit_and_crawl_delay_and_headers():
    pages = {
        "https://e.com/robots.txt": b"User-agent: *\nCrawl-delay: 15\nAllow: /\n",
        "https://e.com/a": b"A",
        "https://e.com/b": b"B",
    }
    f, opener, clock = make(pages, interval=10)
    assert f.fetch(ALLOWED, "https://e.com/a") == b"A"
    assert f.fetch(ALLOWED, "https://e.com/b") == b"B"
    # The 15s Crawl-delay beats our 10s floor, between robots.txt and /a and between /a and /b.
    assert clock.slept == [15, 15]
    for req in opener.requests:
        assert req.get_header("User-agent") == USER_AGENT
        assert req.get_header("Cookie") is None and req.get_header("Authorization") is None
