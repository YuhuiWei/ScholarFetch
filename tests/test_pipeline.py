import pytest
from unittest.mock import AsyncMock, patch
from nexus_paper_fetcher.models import SearchQuery
from nexus_paper_fetcher.pipeline import run


async def test_pipeline_returns_top_n_sorted(sample_papers, monkeypatch):
    import nexus_paper_fetcher.pipeline as pipe
    import nexus_paper_fetcher.scoring.relevance as rel
    monkeypatch.setattr(rel, "config", type("c", (), {"OPENAI_API_KEY": ""})())
    monkeypatch.setattr(pipe.OpenAlexFetcher, "fetch", AsyncMock(return_value=sample_papers[:3]))
    monkeypatch.setattr(pipe.SemanticScholarFetcher, "fetch", AsyncMock(return_value=sample_papers[3:]))

    result = await run(
        SearchQuery(query="gene expression", top_n=3),
        domain_category_override="biology",
    )
    assert len(result.papers) == 3
    scores = [p.scores.composite for p in result.papers]
    assert scores == sorted(scores, reverse=True)


async def test_pipeline_partial_source_failure(sample_papers, monkeypatch):
    import nexus_paper_fetcher.pipeline as pipe
    import nexus_paper_fetcher.scoring.relevance as rel
    monkeypatch.setattr(rel, "config", type("c", (), {"OPENAI_API_KEY": ""})())
    monkeypatch.setattr(pipe.OpenAlexFetcher, "fetch", AsyncMock(return_value=sample_papers))
    monkeypatch.setattr(pipe.SemanticScholarFetcher, "fetch", AsyncMock(return_value=[]))

    result = await run(
        SearchQuery(query="test", top_n=5),
        domain_category_override="biology",
    )
    assert len(result.papers) > 0  # run continues despite one empty source


async def test_pipeline_openreview_not_called_for_biology(sample_papers, monkeypatch):
    import nexus_paper_fetcher.pipeline as pipe
    import nexus_paper_fetcher.scoring.relevance as rel
    monkeypatch.setattr(rel, "config", type("c", (), {"OPENAI_API_KEY": ""})())
    monkeypatch.setattr(pipe.OpenAlexFetcher, "fetch", AsyncMock(return_value=sample_papers))
    monkeypatch.setattr(pipe.SemanticScholarFetcher, "fetch", AsyncMock(return_value=[]))
    or_mock = AsyncMock(return_value=[])
    monkeypatch.setattr(pipe.OpenReviewFetcher, "fetch", or_mock)

    await run(
        SearchQuery(query="protein folding", top_n=5),
        domain_category_override="biology",
    )
    or_mock.assert_not_called()


async def test_pipeline_openreview_called_for_cs_ml(sample_papers, monkeypatch):
    import nexus_paper_fetcher.pipeline as pipe
    import nexus_paper_fetcher.scoring.relevance as rel
    monkeypatch.setattr(rel, "config", type("c", (), {"OPENAI_API_KEY": ""})())
    monkeypatch.setattr(pipe.OpenAlexFetcher, "fetch", AsyncMock(return_value=sample_papers))
    monkeypatch.setattr(pipe.SemanticScholarFetcher, "fetch", AsyncMock(return_value=[]))
    or_mock = AsyncMock(return_value=[])
    monkeypatch.setattr(pipe.OpenReviewFetcher, "fetch", or_mock)

    await run(
        SearchQuery(query="attention mechanisms", top_n=5),
        domain_category_override="cs_ml",
    )
    or_mock.assert_called_once()


async def test_pipeline_result_has_run_metadata(sample_papers, monkeypatch):
    import nexus_paper_fetcher.pipeline as pipe
    import nexus_paper_fetcher.scoring.relevance as rel
    monkeypatch.setattr(rel, "config", type("c", (), {"OPENAI_API_KEY": ""})())
    monkeypatch.setattr(pipe.OpenAlexFetcher, "fetch", AsyncMock(return_value=sample_papers))
    monkeypatch.setattr(pipe.SemanticScholarFetcher, "fetch", AsyncMock(return_value=[]))

    result = await run(
        SearchQuery(query="test query", top_n=3),
        domain_category_override="general",
    )
    assert result.query == "test query"
    assert result.domain_category == "general"
    assert result.timestamp is not None
    assert isinstance(result.sources_used, list)
