from __future__ import annotations
import asyncio
import logging
from abc import ABC, abstractmethod

import httpx
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

from nexus_paper_fetcher.models import Paper, SearchQuery

logger = logging.getLogger(__name__)


def _is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, (httpx.TimeoutException, httpx.TransportError)):
        return True
    if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code == 429:
        return True
    return False


def _retry_wait(retry_state) -> float:
    """Respect Retry-After header on 429, otherwise exponential backoff."""
    exc = retry_state.outcome.exception()
    if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code == 429:
        retry_after = exc.response.headers.get("Retry-After")
        if retry_after:
            try:
                return float(retry_after)
            except ValueError:
                pass
        return 60.0  # conservative default when no header
    # exponential backoff for timeouts
    attempt = retry_state.attempt_number
    return min(8.0, 1.0 * (2 ** (attempt - 1)))


class BaseFetcher(ABC):
    timeout: float = 30.0
    source_name: str = "base"

    @abstractmethod
    async def _fetch(self, query: SearchQuery, client: httpx.AsyncClient) -> list[Paper]:
        ...

    async def fetch(self, query: SearchQuery) -> list[Paper]:
        @retry(
            stop=stop_after_attempt(3),
            wait=_retry_wait,
            retry=retry_if_exception(_is_retryable),
            reraise=True,
        )
        async def _with_retry() -> list[Paper]:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                return await self._fetch(query, client)

        try:
            return await asyncio.wait_for(_with_retry(), timeout=self.timeout * 5)
        except Exception as e:
            logger.warning("[%s] failed after retries: %s", self.source_name, e)
            return []
