from __future__ import annotations
import asyncio
import logging
from abc import ABC, abstractmethod

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from nexus_paper_fetcher.models import Paper, SearchQuery

logger = logging.getLogger(__name__)


class BaseFetcher(ABC):
    timeout: float = 30.0
    source_name: str = "base"

    @abstractmethod
    async def _fetch(self, query: SearchQuery, client: httpx.AsyncClient) -> list[Paper]:
        ...

    async def fetch(self, query: SearchQuery) -> list[Paper]:
        @retry(
            stop=stop_after_attempt(3),
            wait=wait_exponential(multiplier=1, min=1, max=8),
            retry=retry_if_exception_type((httpx.TimeoutException, httpx.TransportError)),
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
