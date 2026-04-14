import pytest
from scholar_fetch.models import Paper, SearchQuery, ScoreBreakdown, RunResult, _derive_paper_id


def test_paper_id_uses_doi_first():
    pid = _derive_paper_id(doi="10.1038/test", arxiv_id="2301.00001", title="T", year=2023)
    pid2 = _derive_paper_id(doi="10.1038/test", arxiv_id=None, title="Other", year=2020)
    assert pid == pid2  # DOI takes priority, ignores arxiv/title/year


def test_paper_id_falls_back_to_arxiv():
    pid = _derive_paper_id(doi=None, arxiv_id="2301.00001", title="T", year=2023)
    pid2 = _derive_paper_id(doi=None, arxiv_id="2301.00001", title="Other", year=2020)
    assert pid == pid2  # arxiv_id takes priority over title+year


def test_paper_id_falls_back_to_title_year():
    pid = _derive_paper_id(doi=None, arxiv_id=None, title="My Paper", year=2023)
    pid2 = _derive_paper_id(doi=None, arxiv_id=None, title="My Paper", year=2023)
    assert pid == pid2  # deterministic
    assert len(pid) == 16


def test_paper_id_different_titles_differ():
    pid1 = _derive_paper_id(doi=None, arxiv_id=None, title="Paper A", year=2023)
    pid2 = _derive_paper_id(doi=None, arxiv_id=None, title="Paper B", year=2023)
    assert pid1 != pid2


def test_resolved_fetch_per_source_default():
    q = SearchQuery(query="test", top_n=20)
    assert q.resolved_fetch_per_source() == 100  # max(3*20, 100) = 100


def test_resolved_fetch_per_source_scales():
    q = SearchQuery(query="test", top_n=50)
    assert q.resolved_fetch_per_source() == 150  # max(3*50, 100) = 150


def test_resolved_fetch_per_source_explicit_override():
    q = SearchQuery(query="test", top_n=20, fetch_per_source=200)
    assert q.resolved_fetch_per_source() == 200


def test_paper_create_sets_sources():
    p = Paper.create(title="T", doi="10.1/x", sources=["openalex"])
    assert "openalex" in p.sources


def test_score_breakdown_defaults():
    s = ScoreBreakdown()
    assert s.relevance == 0.5  # default when no OpenAI key
    assert s.composite == 0.0


def test_paper_download_status_defaults_none():
    p = Paper.create(title="T", sources=["openalex"])
    assert p.download_status is None
    assert p.download_file_path is None
    assert p.domain_tags == []


def test_paper_download_status_roundtrips():
    p = Paper.create(title="T", sources=["openalex"])
    p.download_status = "success"
    p.download_file_path = "/papers/t.pdf"
    p.domain_tags = ["scRNA-seq", "cell atlas"]
    data = p.model_dump()
    p2 = Paper.model_validate(data)
    assert p2.download_status == "success"
    assert p2.download_file_path == "/papers/t.pdf"
    assert p2.domain_tags == ["scRNA-seq", "cell atlas"]


def test_searchquery_slug_and_expand_defaults():
    q = SearchQuery(query="attention mechanisms")
    assert q.query_slug == ""
    assert q.expand_existing is False


def test_runresult_expanded_from_defaults_none():
    from datetime import datetime, timezone
    r = RunResult(
        query="q", domain_category=["cs_ml"], params=SearchQuery(query="q"),
        sources_used=[], papers=[],
        timestamp=datetime.now(timezone.utc),
    )
    assert r.expanded_from is None
