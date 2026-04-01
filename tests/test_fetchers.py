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


from nexus_paper_fetcher.fetchers.openalex import OpenAlexFetcher, _reconstruct_abstract

OPENALEX_RESPONSE = {
    "meta": {"count": 2, "next_cursor": None},
    "results": [
        {
            "id": "https://openalex.org/W123",
            "title": "Single Cell RNA Sequencing Methods",
            "doi": "https://doi.org/10.1038/nmeth.001",
            "publication_year": 2023,
            "cited_by_count": 300,
            "abstract_inverted_index": {"Single": [0], "cell": [1], "method": [2]},
            "authorships": [{"author": {"display_name": "Smith, J."}}],
            "primary_location": {"source": {"display_name": "Nature Methods"}},
        },
        {
            "id": "https://openalex.org/W456",
            "title": "RNA Analysis Pipeline",
            "doi": None,
            "publication_year": 2022,
            "cited_by_count": 50,
            "abstract_inverted_index": None,
            "authorships": [],
            "primary_location": None,
        },
    ],
}


def test_reconstruct_abstract():
    inv = {"Single": [0], "cell": [1], "method": [2]}
    assert _reconstruct_abstract(inv) == "Single cell method"


def test_reconstruct_abstract_handles_gaps():
    inv = {"Hello": [0], "world": [2]}  # position 1 missing
    result = _reconstruct_abstract(inv)
    assert "Hello" in result and "world" in result


@respx.mock
async def test_openalex_fetcher_parses_papers():
    respx.get("https://api.openalex.org/works").mock(
        return_value=httpx.Response(200, json=OPENALEX_RESPONSE)
    )
    papers = await OpenAlexFetcher().fetch(SearchQuery(query="single cell rna", top_n=5))
    assert len(papers) == 2
    assert papers[0].title == "Single Cell RNA Sequencing Methods"
    assert papers[0].doi == "10.1038/nmeth.001"
    assert papers[0].abstract == "Single cell method"
    assert papers[0].openalex_id == "W123"
    assert papers[0].citation_count == 300
    assert "openalex" in papers[0].sources


@respx.mock
async def test_openalex_fetcher_handles_missing_fields():
    respx.get("https://api.openalex.org/works").mock(
        return_value=httpx.Response(200, json=OPENALEX_RESPONSE)
    )
    papers = await OpenAlexFetcher().fetch(SearchQuery(query="test", top_n=5))
    # Second paper has no doi, no abstract, no authors, no location
    p2 = next(p for p in papers if p.title == "RNA Analysis Pipeline")
    assert p2.doi is None
    assert p2.abstract is None
    assert p2.authors == []
