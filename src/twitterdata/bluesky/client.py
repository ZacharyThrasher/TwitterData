"""Polite read-only client for the public Bluesky AppView (no login).

Every request waits at least `min_interval` seconds after the previous one,
and 429 or 5xx answers are retried with exponential backoff that honours
Retry-After and RateLimit-Reset. The public AppView allows roughly 3000
requests per 5 minutes per IP; the default pace (1 request per second) stays
far below that.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable

PUBLIC_APPVIEW = "https://public.api.bsky.app"
USER_AGENT = "twitterdata-bluesky-collector/0.1 (academic research; read-only; +https://github.com/ZacharyThrasher/TwitterData)"
RETRY_STATUSES = {429, 500, 502, 503, 504}


class BlueskyError(Exception):
    """A request failed for good, or the API answered with an error body."""


@dataclass
class Response:
    endpoint: str
    params: dict
    status: int
    received_at: datetime
    body: dict


def _http_get(url: str, timeout: float) -> tuple[int, dict, bytes]:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, dict(resp.headers), resp.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers or {}), e.read() or b""


class Client:
    def __init__(self, base_url: str = PUBLIC_APPVIEW, min_interval: float = 1.0, max_retries: int = 4,
                 timeout: float = 30.0, http_get: Callable | None = None,
                 sleep: Callable[[float], None] = time.sleep, clock: Callable[[], float] = time.monotonic,
                 now: Callable[[], datetime] = lambda: datetime.now(timezone.utc)):
        self.base_url = base_url.rstrip("/")
        self.min_interval = min_interval
        self.max_retries = max_retries
        self.timeout = timeout
        self._http_get = http_get or _http_get
        self._sleep, self._clock, self._now = sleep, clock, now
        self._last: float | None = None
        self.requests = 0

    def now(self) -> datetime:
        return self._now()

    def _wait_turn(self) -> None:
        if self._last is not None:
            gap = self.min_interval - (self._clock() - self._last)
            if gap > 0:
                self._sleep(gap)
        self._last = self._clock()

    def _backoff(self, attempt: int, headers: dict) -> float:
        lower = {k.lower(): v for k, v in headers.items()}
        retry_after = lower.get("retry-after")
        if retry_after and str(retry_after).isdigit():
            return min(float(retry_after), 300.0)
        reset = lower.get("ratelimit-reset")
        if reset and str(reset).isdigit():
            return min(max(float(reset) - time.time(), 1.0), 300.0)
        return 2.0 * (2 ** attempt)

    def get(self, endpoint: str, params: dict) -> Response:
        """GET /xrpc/{endpoint}. List values become repeated query parameters."""
        url = f"{self.base_url}/xrpc/{endpoint}?{urllib.parse.urlencode(params, doseq=True)}"
        for attempt in range(self.max_retries + 1):
            self._wait_turn()
            self.requests += 1
            try:
                status, headers, raw = self._http_get(url, self.timeout)
            except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
                if attempt == self.max_retries:
                    raise BlueskyError(f"{endpoint}: network error: {e}") from e
                self._sleep(2.0 * (2 ** attempt))
                continue
            if status in RETRY_STATUSES and attempt < self.max_retries:
                self._sleep(self._backoff(attempt, headers))
                continue
            try:
                body = json.loads(raw.decode("utf-8")) if raw else {}
            except ValueError as e:
                raise BlueskyError(f"{endpoint}: HTTP {status}, body is not JSON") from e
            if status != 200:
                msg = body.get("message") or body.get("error") or "no message"
                raise BlueskyError(f"{endpoint}: HTTP {status}: {msg}")
            return Response(endpoint, dict(params), status, self._now(), body)
        raise BlueskyError(f"{endpoint}: gave up after {self.max_retries} retries")
