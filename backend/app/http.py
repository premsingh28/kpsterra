"""Shared HTTP client with timeout and exponential-backoff retries."""
import logging
import time

import httpx

from .config import HTTP_TIMEOUT

log = logging.getLogger("kpsterra.http")


class UpstreamError(Exception):
    pass


def get_text(url: str, params: dict | None = None, retries: int = 3, label: str = "") -> str:
    delay = 1.0
    for attempt in range(1, retries + 1):
        try:
            r = httpx.get(url, params=params, timeout=HTTP_TIMEOUT, follow_redirects=True)
            if r.status_code == 429 or r.status_code >= 500:
                raise UpstreamError(f"{label} HTTP {r.status_code}")
            if r.status_code != 200:
                raise UpstreamError(f"{label} HTTP {r.status_code}: {r.text[:120]}")
            return r.text
        except (httpx.HTTPError, UpstreamError) as exc:
            log.warning("%s attempt %d failed: %s", label, attempt, exc)
            if attempt == retries:
                raise UpstreamError(str(exc)) from exc
            time.sleep(delay)
            delay *= 2
    raise UpstreamError(label)
