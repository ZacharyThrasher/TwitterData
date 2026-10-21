"""Polite fetcher, used only for sources whose terms allow automated access.

Rules it enforces:
* the source must have automated_allowed=True in sources.py;
* robots.txt must allow the URL for our user agent;
* at least `min_interval` seconds between requests to the same host (or the
  site's Crawl-delay, whichever is larger);
* no cookies, no logins, no auth headers; plain GET of public pages only.
"""

from __future__ import annotations

import time
import urllib.request
import urllib.robotparser
from urllib.parse import urlparse

USER_AGENT = (
    "TwitterHate-clip-monitor/1.0 (academic research; public listings only; "
    "+https://github.com/ZacharyThrasher/TwitterData)"
)


class NotPermitted(Exception):
    """Raised when terms or robots.txt do not allow fetching a URL."""


class PoliteFetcher:
    def __init__(self, min_interval: float = 10.0, timeout: float = 30.0, opener=None, sleep=time.sleep, clock=time.monotonic):
        self.min_interval = min_interval
        self.timeout = timeout
        # A bare opener: no cookie jar, so no session state is ever sent.
        self._opener = opener or urllib.request.build_opener()
        self._sleep = sleep
        self._clock = clock
        self._last = {}
        self._robots = {}

    def check_source(self, source) -> None:
        if not source.automated_allowed:
            raise NotPermitted(
                f"{source.name}: automated fetching is off. {source.terms_summary} "
                "Save the page from a browser and use `ingest` instead, or record written "
                "permission in sources.py first."
            )

    def robots_for(self, url: str):
        parts = urlparse(url)
        base = f"{parts.scheme}://{parts.netloc}"
        if base not in self._robots:
            rp = urllib.robotparser.RobotFileParser()
            try:
                body = self._get(base + "/robots.txt").decode("utf-8", "replace")
                rp.parse(body.splitlines())
            except Exception:
                # No readable robots.txt: be conservative and refuse.
                rp.parse(["User-agent: *", "Disallow: /"])
            self._robots[base] = rp
        return self._robots[base]

    def fetch(self, source, url: str) -> bytes:
        self.check_source(source)
        rp = self.robots_for(url)
        if not rp.can_fetch(USER_AGENT, url):
            raise NotPermitted(f"robots.txt disallows {url}")
        delay = rp.crawl_delay(USER_AGENT)
        return self._get(url, min_gap=max(self.min_interval, float(delay or 0)))

    def _get(self, url: str, min_gap: float | None = None) -> bytes:
        host = urlparse(url).netloc
        gap = self.min_interval if min_gap is None else min_gap
        last = self._last.get(host)
        if last is not None:
            wait = gap - (self._clock() - last)
            if wait > 0:
                self._sleep(wait)
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html"})
        try:
            with self._opener.open(req, timeout=self.timeout) as resp:
                return resp.read()
        finally:
            self._last[host] = self._clock()
