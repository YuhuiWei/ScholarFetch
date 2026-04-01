import pytest
import respx
import httpx
from nexus_paper_fetcher.fetchers.base import BaseFetcher
from nexus_paper_fetcher.models import Paper, SearchQuery


class _ConcreteFetcher(BaseFetcher):
    """Minimal concrete fetcher for testing BaseFetcher behavior."""
    timeout = 5.0
    source_name = "test"

    async def _fetch(self, query: SearchQuery, client: httpx.AsyncClient) -> list[Paper]:
        response = await client.get("http://test.local/papers")
        response.raise_for_status()
        return [Paper.create(title="Test Paper", sources=["test"])]


SAMPLE_QUERY = SearchQuery(query="test query", top_n=5)


@respx.mock
async def test_base_fetcher_returns_papers_on_success():
    respx.get("http://test.local/papers").mock(return_value=httpx.Response(200))
    papers = await _ConcreteFetcher().fetch(SAMPLE_QUERY)
    assert len(papers) == 1
    assert papers[0].title == "Test Paper"


@respx.mock
async def test_base_fetcher_returns_empty_after_exhausted_retries():
    respx.get("http://test.local/papers").mock(
        side_effect=httpx.TimeoutException("timeout")
    )
    papers = await _ConcreteFetcher().fetch(SAMPLE_QUERY)
    assert papers == []


@respx.mock
async def test_base_fetcher_retries_on_timeout():
    # First two calls timeout, third succeeds
    route = respx.get("http://test.local/papers")
    route.side_effect = [
        httpx.TimeoutException("t1"),
        httpx.TimeoutException("t2"),
        httpx.Response(200),
    ]
    papers = await _ConcreteFetcher().fetch(SAMPLE_QUERY)
    assert len(papers) == 1
    assert route.call_count == 3
