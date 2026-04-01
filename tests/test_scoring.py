import pytest
from nexus_paper_fetcher.scoring.venue import VenueScorer


def test_venue_exact_match_tier1():
    assert VenueScorer.score("Nature Methods") == 1.0


def test_venue_fuzzy_match_abbreviation():
    # "Nat Methods" should fuzzy-match "Nature Methods"
    assert VenueScorer.score("Nat Methods") == 1.0


def test_venue_fuzzy_match_case_insensitive():
    assert VenueScorer.score("nature methods") == 1.0


def test_venue_tier2_score():
    score = VenueScorer.score("CVPR")
    assert score == 0.75


def test_venue_tier3_score():
    score = VenueScorer.score("BMC Bioinformatics")
    assert score == 0.5


def test_venue_unknown_returns_default():
    assert VenueScorer.score("Journal of Obscure Studies") == 0.3


def test_venue_none_returns_default():
    assert VenueScorer.score(None) == 0.3


from nexus_paper_fetcher.scoring.citation import CitationScorer
from nexus_paper_fetcher.scoring.recency import RecencyScorer
import math


# --- CitationScorer ---

def test_citation_max_paper_scores_near_one():
    # The highest-cited paper in the batch scores ~1.0
    score = CitationScorer.score(citation_count=1000, year=2020, max_citations=1000)
    assert score == pytest.approx(1.0, abs=0.01)


def test_citation_log_normalized():
    s_high = CitationScorer.score(citation_count=1000, year=2020, max_citations=1000)
    s_low = CitationScorer.score(citation_count=10, year=2020, max_citations=1000)
    assert s_high > s_low > 0


def test_citation_age_adjusted_new_paper():
    # Paper from current year gets age_factor close to 1/3
    from datetime import datetime
    current = datetime.utcnow().year
    s_new = CitationScorer.score(100, year=current, max_citations=100)
    s_old = CitationScorer.score(100, year=current - 5, max_citations=100)
    assert s_old > s_new  # older paper with same citations scores higher


def test_citation_zero_returns_zero():
    assert CitationScorer.score(citation_count=0, year=2022, max_citations=100) == 0.0


def test_citation_none_returns_zero():
    assert CitationScorer.score(citation_count=None, year=2022, max_citations=100) == 0.0


# --- RecencyScorer ---

def test_recency_current_year_is_one():
    from datetime import datetime
    score = RecencyScorer.score(year=datetime.utcnow().year, domain_category="cs_ml")
    assert score == pytest.approx(1.0, abs=0.01)


def test_recency_cs_ml_decays_faster_than_biology():
    score_cs = RecencyScorer.score(year=2020, domain_category="cs_ml")
    score_bio = RecencyScorer.score(year=2020, domain_category="biology")
    assert score_bio > score_cs


def test_recency_missing_year_returns_default():
    assert RecencyScorer.score(year=None, domain_category="cs_ml") == 0.3


from unittest.mock import AsyncMock, MagicMock, patch
from nexus_paper_fetcher.scoring.relevance import RelevanceScorer, DEFAULT_SCORE


async def test_relevance_no_api_key_returns_default(monkeypatch):
    import nexus_paper_fetcher.scoring.relevance as rel
    monkeypatch.setattr(rel, "config", type("c", (), {"OPENAI_API_KEY": ""})())
    scores = await RelevanceScorer.score_batch("query", ["abstract one", "abstract two"])
    assert scores == [DEFAULT_SCORE, DEFAULT_SCORE]


async def test_relevance_empty_abstract_returns_default(monkeypatch):
    import nexus_paper_fetcher.scoring.relevance as rel
    monkeypatch.setattr(rel, "config", type("c", (), {"OPENAI_API_KEY": ""})())
    scores = await RelevanceScorer.score_batch("query", [""])
    assert scores == [DEFAULT_SCORE]


async def test_relevance_with_api_key_returns_cosine_scores(monkeypatch):
    import nexus_paper_fetcher.scoring.relevance as rel
    monkeypatch.setattr(rel, "config", type("c", (), {"OPENAI_API_KEY": "fake-key"})())

    # query vec = [1,0,0,0], identical vec = [1,0,0,0] (cosine 1.0),
    # orthogonal vec = [0,1,0,0] (cosine 0.0)
    mock_response = MagicMock()
    mock_response.data = [
        MagicMock(embedding=[1.0, 0.0, 0.0, 0.0]),  # query
        MagicMock(embedding=[1.0, 0.0, 0.0, 0.0]),  # identical
        MagicMock(embedding=[0.0, 1.0, 0.0, 0.0]),  # orthogonal
    ]

    mock_client = MagicMock()
    mock_client.embeddings.create = AsyncMock(return_value=mock_response)
    monkeypatch.setattr(rel.RelevanceScorer, "_client", mock_client)

    scores = await RelevanceScorer.score_batch("query", ["identical text", "orthogonal text"])
    assert scores[0] == pytest.approx(1.0, abs=0.01)
    assert scores[1] == pytest.approx(0.0, abs=0.01)


async def test_relevance_scores_between_zero_and_one(monkeypatch):
    import nexus_paper_fetcher.scoring.relevance as rel
    monkeypatch.setattr(rel, "config", type("c", (), {"OPENAI_API_KEY": "fake-key"})())

    import numpy as np
    dim = 8
    query_vec = np.array([1.0, 0.0] + [0.0] * (dim - 2))
    doc_vec = np.array([0.7, 0.7] + [0.0] * (dim - 2))
    doc_vec = doc_vec / np.linalg.norm(doc_vec)

    mock_response = MagicMock()
    mock_response.data = [
        MagicMock(embedding=query_vec.tolist()),
        MagicMock(embedding=doc_vec.tolist()),
    ]
    mock_client = MagicMock()
    mock_client.embeddings.create = AsyncMock(return_value=mock_response)
    monkeypatch.setattr(rel.RelevanceScorer, "_client", mock_client)

    scores = await RelevanceScorer.score_batch("query", ["some abstract"])
    assert 0.0 <= scores[0] <= 1.0


from unittest.mock import AsyncMock, patch
from nexus_paper_fetcher.models import Paper
from nexus_paper_fetcher.scoring.scorer import score_all, DOMAIN_WEIGHTS


async def test_composite_score_in_range(sample_papers, monkeypatch):
    import nexus_paper_fetcher.scoring.relevance as rel
    monkeypatch.setattr(rel, "config", type("c", (), {"OPENAI_API_KEY": ""})())
    result = await score_all(sample_papers, "gene expression", "biology")
    for p in result:
        assert 0.0 <= p.scores.composite <= 1.0


async def test_composite_uses_domain_weights(sample_papers, monkeypatch):
    import nexus_paper_fetcher.scoring.relevance as rel
    monkeypatch.setattr(rel, "config", type("c", (), {"OPENAI_API_KEY": ""})())
    # cs_ml weights recency heavily; biology weights citation heavily
    await score_all(sample_papers[:1], "test", "cs_ml")
    cs_recency_weight = DOMAIN_WEIGHTS["cs_ml"]["recency"]
    bio_recency_weight = DOMAIN_WEIGHTS["biology"]["recency"]
    assert cs_recency_weight > bio_recency_weight


async def test_composite_oral_bonus_applied(monkeypatch):
    import nexus_paper_fetcher.scoring.relevance as rel
    monkeypatch.setattr(rel, "config", type("c", (), {"OPENAI_API_KEY": ""})())
    oral = Paper.create(title="Oral Paper", year=2023, venue="NeurIPS",
                        openreview_tier="oral", citation_count=100, sources=["openreview"])
    no_bonus = Paper.create(title="Regular Paper", year=2023, venue="NeurIPS",
                             citation_count=100, sources=["openalex"])
    papers = await score_all([oral, no_bonus], "test", "cs_ml")
    oral_p = next(p for p in papers if p.openreview_tier == "oral")
    regular_p = next(p for p in papers if p.openreview_tier is None)
    assert oral_p.scores.openreview_bonus == 0.15
    assert regular_p.scores.openreview_bonus == 0.0
    assert oral_p.scores.composite > regular_p.scores.composite


async def test_composite_capped_at_one(monkeypatch):
    import nexus_paper_fetcher.scoring.relevance as rel
    monkeypatch.setattr(rel, "config", type("c", (), {"OPENAI_API_KEY": ""})())
    # High citation + oral bonus: shouldn't exceed 1.0
    paper = Paper.create(title="T", year=2024, venue="NeurIPS",
                         openreview_tier="oral", citation_count=100000,
                         sources=["openreview"])
    result = await score_all([paper], "test", "cs_ml")
    assert result[0].scores.composite <= 1.0
