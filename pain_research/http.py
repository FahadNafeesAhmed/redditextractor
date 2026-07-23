"""Small HTTP client with per-host pacing and transparent retry behavior."""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from typing import Any
from urllib.parse import urlsplit

import requests


DEFAULT_HEADERS = {
    "Accept": "application/json",
    "User-Agent": "PainResearchCollector/1.0 (public research; respectful rate limits)",
}


class ApiError(RuntimeError):
    """A source API failed after the configured retry budget."""


class ApiClient:
    """Fetch public JSON endpoints without bypassing provider rate limits."""

    def __init__(
        self,
        session: requests.Session | None = None,
        *,
        min_interval: float = 1.0,
        max_attempts: int = 4,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.session = session or requests.Session()
        self.min_interval = min_interval
        self.max_attempts = max_attempts
        self.sleep = sleep
        self.clock = clock
        self._last_request_by_host: dict[str, float] = {}

    def get_json(
        self,
        url: str,
        *,
        params: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
        timeout: int = 30,
    ) -> Any:
        """Get JSON, retrying only transient failures and rate limits."""
        host = urlsplit(url).netloc
        merged_headers = {**DEFAULT_HEADERS, **(headers or {})}
        last_error: Exception | None = None
        for attempt in range(1, self.max_attempts + 1):
            self._pace(host)
            try:
                response = self.session.get(url, params=params, headers=merged_headers, timeout=timeout)
                self._last_request_by_host[host] = self.clock()
                if response.status_code == 429 or response.status_code >= 500:
                    last_error = requests.HTTPError(f"HTTP {response.status_code} from {url}")
                    if attempt < self.max_attempts:
                        self.sleep(self._retry_delay(response.headers, attempt))
                        continue
                    break
                response.raise_for_status()
                return response.json()
            except (ValueError, requests.RequestException) as error:
                last_error = error
                if attempt < self.max_attempts:
                    self.sleep(min(60.0, 2.0**attempt))
        raise ApiError(f"Could not collect {url}: {last_error}") from last_error

    def _pace(self, host: str) -> None:
        elapsed = self.clock() - self._last_request_by_host.get(host, 0.0)
        if elapsed < self.min_interval:
            self.sleep(self.min_interval - elapsed)

    def _retry_delay(self, headers: Mapping[str, str], attempt: int) -> float:
        try:
            return max(self.min_interval, float(headers.get("Retry-After", "")))
        except ValueError:
            return min(120.0, 15.0 * 2 ** (attempt - 1))
