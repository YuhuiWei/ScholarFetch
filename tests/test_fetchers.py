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
            "best_oa_location": {
                "pdf_url": "https://example.com/openalex-paper.pdf",
            },
            "open_access": {
                "oa_url": "https://example.com/openalex-paper.pdf",
            },
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
    assert papers[0].open_access_pdf_url == "https://example.com/openalex-paper.pdf"
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


from nexus_paper_fetcher.fetchers.semantic_scholar import SemanticScholarFetcher

S2_RESPONSE = {
    "total": 1,
    "data": [
        {
            "paperId": "ss_abc123",
            "title": "Scalable Transformer Architecture",
            "abstract": "We propose a scalable transformer.",
            "year": 2023,
            "venue": "NeurIPS",
            "authors": [{"name": "Doe, J."}, {"name": "Lee, A."}],
            "citationCount": 120,
            "influentialCitationCount": 45,
            "openAccessPdf": {"url": "https://arxiv.org/pdf/2301.00001"},
            "externalIds": {"DOI": "10.1145/test", "ArXiv": "2301.00001"},
            "tldr": {"text": "A scalable transformer."},
        }
    ],
}


@respx.mock
async def test_s2_fetcher_parses_papers():
    respx.get("https://api.semanticscholar.org/graph/v1/paper/search").mock(
        return_value=httpx.Response(200, json=S2_RESPONSE)
    )
    papers = await SemanticScholarFetcher().fetch(SearchQuery(query="transformer", top_n=5))
    assert len(papers) == 1
    p = papers[0]
    assert p.title == "Scalable Transformer Architecture"
    assert p.doi == "10.1145/test"
    assert p.arxiv_id == "2301.00001"
    assert p.semantic_scholar_id == "ss_abc123"
    assert p.open_access_pdf_url == "https://arxiv.org/pdf/2301.00001"
    assert p.citation_count == 45  # uses influentialCitationCount
    assert "semantic_scholar" in p.sources


@respx.mock
async def test_s2_fetcher_falls_back_to_citation_count():
    # influentialCitationCount == 0, should fall back to citationCount
    data = {
        "total": 1,
        "data": [{
            "paperId": "x", "title": "T", "year": 2022,
            "citationCount": 80, "influentialCitationCount": 0,
            "externalIds": {}, "authors": [], "openAccessPdf": None,
        }],
    }
    respx.get("https://api.semanticscholar.org/graph/v1/paper/search").mock(
        return_value=httpx.Response(200, json=data)
    )
    papers = await SemanticScholarFetcher().fetch(SearchQuery(query="test", top_n=5))
    assert papers[0].citation_count == 80


from nexus_paper_fetcher.fetchers.openreview import OpenReviewFetcher

OR_SUBMISSIONS = {
    "notes": [
        {
            "id": "note1",
            "forum": "forum1",
            "content": {
                "title": {"value": "FlashAttention: Fast Memory-Efficient Attention"},
                "abstract": {"value": "We propose FlashAttention."},
                "authors": {"value": ["Dao, T.", "Fu, D."]},
            },
        },
        {
            "id": "note2",
            "forum": "forum2",
            "content": {
                "title": {"value": "A Rejected Paper"},
                "abstract": {"value": "This was rejected."},
                "authors": {"value": ["Smith, J."]},
            },
        },
    ]
}

OR_DECISIONS = {
    "notes": [
        {
            "forum": "forum1",
            "content": {"decision": {"value": "Accept (Oral)"}},
        },
        {
            "forum": "forum2",
            "content": {"decision": {"value": "Reject"}},
        },
    ]
}


@respx.mock
async def test_openreview_fetcher_parses_accepted_papers():
    respx.get("https://api2.openreview.net/notes").mock(
        side_effect=lambda req: (
            httpx.Response(200, json=OR_SUBMISSIONS)
            if "Blind_Submission" in str(req.url)
            else httpx.Response(200, json=OR_DECISIONS)
        )
    )
    papers = await OpenReviewFetcher().fetch(
        SearchQuery(query="attention", top_n=5, year_from=2022, year_to=2022)
    )
    accepted = [p for p in papers if p.title == "FlashAttention: Fast Memory-Efficient Attention"]
    rejected = [p for p in papers if p.title == "A Rejected Paper"]
    assert len(accepted) >= 1
    assert len(rejected) == 0


@respx.mock
async def test_openreview_fetcher_sets_oral_tier():
    respx.get("https://api2.openreview.net/notes").mock(
        side_effect=lambda req: (
            httpx.Response(200, json=OR_SUBMISSIONS)
            if "Blind_Submission" in str(req.url)
            else httpx.Response(200, json=OR_DECISIONS)
        )
    )
    papers = await OpenReviewFetcher().fetch(
        SearchQuery(query="attention", top_n=5, year_from=2022, year_to=2022)
    )
    oral_papers = [p for p in papers if p.openreview_tier == "oral"]
    assert len(oral_papers) >= 1


@respx.mock
async def test_openreview_fetcher_handles_404_venue():
    # Venue+year not found → returns empty, no crash
    respx.get("https://api2.openreview.net/notes").mock(
        return_value=httpx.Response(404)
    )
    papers = await OpenReviewFetcher().fetch(
        SearchQuery(query="test", top_n=5, year_from=2022, year_to=2022)
    )
    assert papers == []


@respx.mock
async def test_openreview_fetcher_uses_query_search_route():
    search_route = respx.get("https://api2.openreview.net/notes/search").mock(
        return_value=httpx.Response(
            200,
            json={
                "notes": [
                    {
                        "id": "srch1",
                        "forum": "srch1",
                        "content": {
                            "title": {"value": "Deep Visual Representation Learning"},
                            "abstract": {"value": "We present a vision representation model."},
                            "authors": {"value": ["Lee, A."]},
                            "venue": {"value": "ICLR 2025"},
                        },
                        "cdate": 1735689600000,
                    }
                ]
            },
        )
    )
    respx.get("https://api2.openreview.net/notes").mock(return_value=httpx.Response(404))

    papers = await OpenReviewFetcher().fetch(
        SearchQuery(query="recent computer vision deep representation study", top_n=5)
    )

    assert search_route.called
    assert any(p.title == "Deep Visual Representation Learning" for p in papers)


async def test_openreview_fetcher_defaults_year_to_current_year(monkeypatch):
    import nexus_paper_fetcher.fetchers.openreview as openreview

    years_seen = []

    async def fake_search_query(self, client, query_text, year_from, year_to, limit):
        return []

    async def fake_fetch_venue_year(self, client, venue, year):
        years_seen.append(year)
        return []

    monkeypatch.setattr(openreview.OpenReviewFetcher, "_search_query", fake_search_query)
    monkeypatch.setattr(openreview.OpenReviewFetcher, "_fetch_venue_year", fake_fetch_venue_year)

    papers = await openreview.OpenReviewFetcher().fetch(
        SearchQuery(query="vision transformers", top_n=5, year_from=2025)
    )

    assert papers == []
    assert years_seen
    assert max(years_seen) >= 2025


async def test_openreview_fetcher_uses_authenticated_v2_search_in_pages(monkeypatch):
    import nexus_paper_fetcher.fetchers.openreview as openreview

    class FakeNote:
        def __init__(self, title: str, year: int):
            self._payload = {
                "id": title,
                "forum": title,
                "content": {
                    "title": {"value": title},
                    "abstract": {"value": f"{title} abstract"},
                    "authors": {"value": ["Lee, A."]},
                    "venue": {"value": f"ICLR {year}"},
                },
                "cdate": 1735689600000 if year == 2025 else 1704067200000,
            }

        def to_json(self):
            return self._payload

    class FakeClient:
        def __init__(self):
            self.calls = []

        def search_notes(self, term, content="all", group="all", source="all", limit=None, offset=None):
            self.calls.append(
                {
                    "term": term,
                    "content": content,
                    "group": group,
                    "source": source,
                    "limit": limit,
                    "offset": offset,
                }
            )
            if offset == 0:
                return [FakeNote("Vision Transformer A", 2025), FakeNote("Vision Transformer B", 2025)]
            if offset == 2:
                return [FakeNote("Vision Transformer C", 2025)]
            return []

    fake_client = FakeClient()
    monkeypatch.setattr(
        openreview,
        "config",
        type(
            "c",
            (),
            {
                "OPENREVIEW_TIMEOUT": 15.0,
                "OPENREVIEW_USERNAME": "user@example.com",
                "OPENREVIEW_PASSWORD": "secret",
                "OPENREVIEW_BASEURL": "https://api2.openreview.net",
                "OPENREVIEW_SEARCH_PAGE_SIZE": 2,
            },
        )(),
    )
    monkeypatch.setattr(openreview.OpenReviewFetcher, "_get_api_v2_client", lambda self: fake_client)

    papers = await openreview.OpenReviewFetcher().fetch(
        SearchQuery(query="transformer computer vision", top_n=5, fetch_per_source=3)
    )

    assert [paper.title for paper in papers[:3]] == [
        "Vision Transformer A",
        "Vision Transformer B",
        "Vision Transformer C",
    ]
    assert fake_client.calls[:2] == [
        {
            "term": "transformer computer vision",
            "content": "all",
            "group": "all",
            "source": "all",
            "limit": 2,
            "offset": 0,
        },
        {
            "term": "transformer computer vision",
            "content": "all",
            "group": "all",
            "source": "all",
            "limit": 2,
            "offset": 2,
        },
    ]
