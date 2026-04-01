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
