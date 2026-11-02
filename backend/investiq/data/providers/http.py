"""Shared HTTP client with timeouts, retries with backoff and simple per-host rate limiting."""

from __future__ import annotations

import threading
import time
from typing import Any

import httpx

from investiq import __version__
from investiq.data.providers.base import ProviderError

DEFAULT_TIMEOUT = httpx.Timeout(20.0, connect=10.0)
RETRY_STATUS = {429, 500, 502, 503, 504}


class RateLimiter:
    def __init__(self, min_interval_s: float) -> None:
        self.min_interval_s = min_interval_s
        self._last = 0.0
        self._lock = threading.Lock()

    def wait(self) -> None:
        with self._lock:
            delay = self._last + self.min_interval_s - time.monotonic()
            if delay > 0:
                time.sleep(delay)
            self._last = time.monotonic()


class HttpClient:
    def __init__(self, *, user_agent: str | None = None, min_interval_s: float = 0.0, retries: int = 3,
                 transport: httpx.BaseTransport | None = None, sleep=time.sleep) -> None:
        headers = {"User-Agent": user_agent or f"InvestIQ/{__version__} (local research application)"}
        self._client = httpx.Client(timeout=DEFAULT_TIMEOUT, headers=headers, transport=transport,
                                    follow_redirects=True)
        self._limiter = RateLimiter(min_interval_s)
        self._retries = retries
        self._sleep = sleep

    def get(self, url: str, params: dict[str, Any] | None = None) -> httpx.Response:
        last_exc: Exception | None = None
        for attempt in range(self._retries):
            self._limiter.wait()
            try:
                resp = self._client.get(url, params=params)
            except httpx.TransportError as exc:
                last_exc = exc
            else:
                if resp.status_code < 400:
                    return resp
                if resp.status_code not in RETRY_STATUS:
                    raise ProviderError(f"HTTP {resp.status_code} from {httpx.URL(url).host}")
                last_exc = ProviderError(f"HTTP {resp.status_code} from {httpx.URL(url).host}")
                retry_after = resp.headers.get("retry-after")
                if retry_after and retry_after.isdigit():
                    self._sleep(min(int(retry_after), 30))
                    continue
            self._sleep(min(2 ** attempt, 8))
        raise ProviderError(f"request to {httpx.URL(url).host} failed after {self._retries} attempts: {last_exc}")

    def get_json(self, url: str, params: dict[str, Any] | None = None) -> Any:
        resp = self.get(url, params)
        try:
            return resp.json()
        except ValueError as exc:
            raise ProviderError(f"invalid JSON from {httpx.URL(url).host}") from exc

    def close(self) -> None:
        self._client.close()
