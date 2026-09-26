"""HTTP client with rate limiting and retries."""

from __future__ import annotations

import logging
import random
import time
from typing import Any

import httpx
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential_jitter,
)

from playstore_scraper.utils import jitter_sleep

logger = logging.getLogger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/128.0.0.0 Safari/537.36"
)


class HttpError(Exception):
    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class RateLimitedError(HttpError):
    pass


class TransientHttpError(HttpError):
    pass


def _is_retryable(exc: BaseException) -> bool:
    return isinstance(
        exc,
        (
            TransientHttpError,
            RateLimitedError,
            httpx.TimeoutException,
            httpx.NetworkError,
            httpx.RemoteProtocolError,
        ),
    )


class PlayStoreClient:
    def __init__(
        self,
        *,
        delay_seconds: float = 1.0,
        max_retries: int = 6,
        timeout_seconds: float = 30.0,
        proxy: str | None = None,
    ) -> None:
        self.delay_seconds = delay_seconds
        self.base_delay = delay_seconds
        self.max_retries = max_retries
        self.request_count = 0
        self.retry_count = 0
        kwargs: dict[str, Any] = {
            "http2": True,
            "timeout": timeout_seconds,
            "follow_redirects": True,
            "headers": {
                "User-Agent": USER_AGENT,
                "Origin": "https://play.google.com",
                "Referer": "https://play.google.com/",
                "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
                "Accept-Language": "en-US,en;q=0.9",
            },
        }
        if proxy:
            kwargs["proxy"] = proxy
        self._client = httpx.Client(**kwargs)

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> PlayStoreClient:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def _throttle(self) -> None:
        jitter_sleep(self.delay_seconds)

    def _on_429(self, response: httpx.Response) -> None:
        retry_after = response.headers.get("Retry-After")
        wait = None
        if retry_after:
            try:
                wait = float(retry_after)
            except ValueError:
                wait = None
        if wait is None:
            wait = min(60.0, self.delay_seconds * 4 + random.uniform(0, 2))
        logger.warning("HTTP 429 — sleeping %.1fs and slowing down", wait)
        time.sleep(wait)
        self.delay_seconds = min(self.delay_seconds * 2, 30.0)

    def get_text(self, url: str, *, lang: str | None = None) -> tuple[str, int]:
        self._throttle()
        headers = {}
        if lang:
            headers["Accept-Language"] = f"{lang},en;q=0.8"
        response = self._request("GET", url, headers=headers)
        return response.text, response.status_code

    def post_form(self, url: str, body: str, *, lang: str | None = None) -> tuple[str, int]:
        self._throttle()
        headers = {}
        if lang:
            headers["Accept-Language"] = f"{lang},en;q=0.8"
        response = self._request("POST", url, content=body, headers=headers)
        return response.text, response.status_code

    def _request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        @retry(
            retry=retry_if_exception(_is_retryable),
            stop=stop_after_attempt(self.max_retries),
            wait=wait_exponential_jitter(initial=1, max=60),
            reraise=True,
            before_sleep=self._before_sleep,
        )
        def _do() -> httpx.Response:
            self.request_count += 1
            try:
                resp = self._client.request(method, url, **kwargs)
            except (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError):
                raise

            if resp.status_code == 429:
                self._on_429(resp)
                raise RateLimitedError("Rate limited (429)", status_code=429)
            if resp.status_code in {500, 502, 503, 504}:
                raise TransientHttpError(
                    f"Server error {resp.status_code}", status_code=resp.status_code
                )
            if resp.status_code in {400, 404}:
                raise HttpError(
                    f"HTTP {resp.status_code} for {url}", status_code=resp.status_code
                )
            if resp.status_code >= 400:
                raise HttpError(
                    f"HTTP {resp.status_code} for {url}", status_code=resp.status_code
                )
            return resp

        return _do()

    def _before_sleep(self, retry_state: Any) -> None:
        self.retry_count += 1
        exc = retry_state.outcome.exception() if retry_state.outcome else None
        logger.warning(
            "Retry %s/%s after %s",
            retry_state.attempt_number,
            self.max_retries,
            type(exc).__name__ if exc else "error",
        )
