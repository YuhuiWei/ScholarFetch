import pytest
from unittest.mock import AsyncMock, patch
from nexus_paper_fetcher.models import SearchQuery
from nexus_paper_fetcher.pipeline import run


async def test_pipeline_returns_top_n_sorted(sample_papers, monkeypatch):
    import nexus_paper_fetcher.pipeline as pipe
    import nexus_paper_fetcher.evaluation as evaluation
    import nexus_paper_fetcher.scoring.relevance as rel
    monkeypatch.setattr(pipe, "cfg", type("c", (), {"OPENAI_API_KEY": ""})())
    monkeypatch.setattr(evaluation, "config", type("c", (), {"OPENAI_API_KEY": ""})())
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
    import nexus_paper_fetcher.evaluation as evaluation
    import nexus_paper_fetcher.scoring.relevance as rel
    monkeypatch.setattr(pipe, "cfg", type("c", (), {"OPENAI_API_KEY": ""})())
    monkeypatch.setattr(evaluation, "config", type("c", (), {"OPENAI_API_KEY": ""})())
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
    import nexus_paper_fetcher.evaluation as evaluation
    import nexus_paper_fetcher.scoring.relevance as rel
    monkeypatch.setattr(pipe, "cfg", type("c", (), {"OPENAI_API_KEY": ""})())
    monkeypatch.setattr(evaluation, "config", type("c", (), {"OPENAI_API_KEY": ""})())
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
    import nexus_paper_fetcher.evaluation as evaluation
    import nexus_paper_fetcher.scoring.relevance as rel
    monkeypatch.setattr(pipe, "cfg", type("c", (), {"OPENAI_API_KEY": ""})())
    monkeypatch.setattr(evaluation, "config", type("c", (), {"OPENAI_API_KEY": ""})())
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
    import nexus_paper_fetcher.evaluation as evaluation
    import nexus_paper_fetcher.scoring.relevance as rel
    monkeypatch.setattr(pipe, "cfg", type("c", (), {"OPENAI_API_KEY": ""})())
    monkeypatch.setattr(evaluation, "config", type("c", (), {"OPENAI_API_KEY": ""})())
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


async def test_pipeline_marks_lookup_not_found_when_exact_title_missing(monkeypatch):
    import nexus_paper_fetcher.pipeline as pipe
    import nexus_paper_fetcher.evaluation as evaluation
    import nexus_paper_fetcher.scoring.relevance as rel
    from nexus_paper_fetcher.models import Paper

    monkeypatch.setattr(pipe, "cfg", type("c", (), {"OPENAI_API_KEY": ""})())
    monkeypatch.setattr(evaluation, "config", type("c", (), {"OPENAI_API_KEY": ""})())
    monkeypatch.setattr(rel, "config", type("c", (), {"OPENAI_API_KEY": ""})())

    near_match = Paper.create(
        title="Attention Is Nearly All You Need",
        year=2018,
        venue="NeurIPS",
        citation_count=10,
        sources=["openalex"],
    )
    monkeypatch.setattr(pipe.OpenAlexFetcher, "fetch", AsyncMock(return_value=[near_match]))
    monkeypatch.setattr(pipe.SemanticScholarFetcher, "fetch", AsyncMock(return_value=[]))
    monkeypatch.setattr(pipe.OpenReviewFetcher, "fetch", AsyncMock(return_value=[]))
    monkeypatch.setattr(
        pipe,
        "score_all",
        AsyncMock(return_value=[near_match]),
    )

    result = await run(
        SearchQuery(
            query="Attention Is All You Need",
            top_n=1,
            paper_titles=["Attention Is All You Need"],
        ),
        domain_category_override="cs_ml",
    )

    assert getattr(result, "not_found", False) is True
    assert result.papers[0].title == "Attention Is Nearly All You Need"


async def test_pipeline_filters_review_like_results_by_default(monkeypatch):
    import nexus_paper_fetcher.pipeline as pipe
    import nexus_paper_fetcher.evaluation as evaluation
    import nexus_paper_fetcher.scoring.relevance as rel
    from nexus_paper_fetcher.models import Paper

    monkeypatch.setattr(pipe, "cfg", type("c", (), {"OPENAI_API_KEY": ""})())
    monkeypatch.setattr(evaluation, "config", type("c", (), {"OPENAI_API_KEY": ""})())
    monkeypatch.setattr(rel, "config", type("c", (), {"OPENAI_API_KEY": ""})())

    review = Paper.create(
        title="Cancer Progress Review",
        year=2024,
        venue="Nature Reviews Cancer",
        citation_count=500,
        sources=["openalex"],
    )
    primary = Paper.create(
        title="A Primary Vision Study",
        year=2024,
        venue="CVPR",
        citation_count=50,
        sources=["openalex"],
    )
    review.scores.composite = 0.95
    primary.scores.composite = 0.40

    monkeypatch.setattr(pipe.OpenAlexFetcher, "fetch", AsyncMock(return_value=[review, primary]))
    monkeypatch.setattr(pipe.SemanticScholarFetcher, "fetch", AsyncMock(return_value=[]))
    monkeypatch.setattr(pipe.OpenReviewFetcher, "fetch", AsyncMock(return_value=[]))
    monkeypatch.setattr(
        pipe,
        "score_all",
        AsyncMock(side_effect=lambda papers, *_args: papers),
    )

    result = await run(
        SearchQuery(query="recent computer vision study", top_n=5),
        domain_category_override="cs_ml",
    )

    assert [paper.title for paper in result.papers] == ["A Primary Vision Study"]
