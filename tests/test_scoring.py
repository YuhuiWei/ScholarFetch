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
