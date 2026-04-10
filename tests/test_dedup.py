import pytest
from nexus_paper_fetcher.models import Paper
from nexus_paper_fetcher.dedup import deduplicate, _normalize_doi, _normalize_title


def test_normalize_doi_strips_prefix():
    assert _normalize_doi("https://doi.org/10.1038/test") == "10.1038/test"
    assert _normalize_doi("http://doi.org/10.1038/test") == "10.1038/test"
    assert _normalize_doi("10.1038/TEST") == "10.1038/test"


def test_normalize_title_strips_articles():
    assert _normalize_title("A Novel Method") == "novel method"
    assert _normalize_title("An Introduction") == "introduction"
    assert _normalize_title("The Algorithm") == "algorithm"


def test_normalize_title_strips_punctuation():
    assert _normalize_title("BERT: Pre-training") == "bert pre training"


def test_doi_exact_dedup():
    p1 = Paper.create(title="Paper A", doi="10.1038/test", sources=["openalex"])
    p2 = Paper.create(title="Paper A", doi="https://doi.org/10.1038/test", sources=["semantic_scholar"])
    result = deduplicate([p1, p2])
    assert len(result) == 1
    assert set(result[0].sources) == {"openalex", "semantic_scholar"}


def test_fuzzy_title_dedup_matches():
    p1 = Paper.create(title="Scalable Methods for Single-Cell Analysis", year=2023, sources=["openalex"])
    p2 = Paper.create(title="Scalable Methods for Single Cell Analysis", year=2023, sources=["openreview"])
    result = deduplicate([p1, p2])
    assert len(result) == 1
    assert set(result[0].sources) == {"openalex", "openreview"}


def test_fuzzy_title_below_threshold_stays_separate():
    p1 = Paper.create(title="Attention Is All You Need", year=2017, sources=["openalex"])
    p2 = Paper.create(title="Recurrent Neural Networks Are All You Need", year=2022, sources=["openalex"])
    result = deduplicate([p1, p2])
    assert len(result) == 2


def test_merge_abstract_takes_longest():
    p1 = Paper.create(title="T", doi="10.1/x", abstract="Short.", sources=["openalex"])
    p2 = Paper.create(title="T", doi="10.1/x", abstract="Much longer abstract text here.", sources=["s2"])
    result = deduplicate([p1, p2])
    assert result[0].abstract == "Much longer abstract text here."


def test_merge_citation_count_takes_max():
    p1 = Paper.create(title="T", doi="10.1/x", citation_count=100, sources=["openalex"])
    p2 = Paper.create(title="T", doi="10.1/x", citation_count=250, sources=["s2"])
    result = deduplicate([p1, p2])
    assert result[0].citation_count == 250


def test_merge_open_access_url_from_any_source():
    p1 = Paper.create(title="T", doi="10.1/x", open_access_pdf_url=None, sources=["openalex"])
    p2 = Paper.create(title="T", doi="10.1/x",
                      open_access_pdf_url="https://arxiv.org/pdf/test", sources=["s2"])
    result = deduplicate([p1, p2])
    assert result[0].open_access_pdf_url == "https://arxiv.org/pdf/test"


def test_merge_openreview_tier_preserved():
    p1 = Paper.create(title="FlashAttention", year=2022, sources=["openalex"])
    p2 = Paper.create(title="FlashAttention", year=2022,
                      openreview_tier="oral", sources=["openreview"])
    result = deduplicate([p1, p2])
    assert result[0].openreview_tier == "oral"


def test_paper_id_rederived_after_merge():
    # p1 has no DOI, p2 has DOI — merged paper should use DOI-based paper_id
    p1 = Paper.create(title="My Paper", year=2023, sources=["openreview"])
    p2 = Paper.create(title="My Paper", year=2023, doi="10.1/myp", sources=["s2"])
    result = deduplicate([p1, p2])
    from nexus_paper_fetcher.models import _derive_paper_id
    expected_id = _derive_paper_id("10.1/myp", None, "My Paper", 2023)
    assert result[0].paper_id == expected_id


def test_three_source_merge():
    p1 = Paper.create(title="T", doi="10.1/x", sources=["openalex"], openalex_id="W1")
    p2 = Paper.create(title="T", doi="10.1/x", sources=["s2"], semantic_scholar_id="SS1")
    p3 = Paper.create(title="T", doi="10.1/x", sources=["openreview"], openreview_tier="spotlight")
    result = deduplicate([p1, p2, p3])
    assert len(result) == 1
    assert result[0].openalex_id == "W1"
    assert result[0].semantic_scholar_id == "SS1"
    assert result[0].openreview_tier == "spotlight"


def test_deduplicate_excludes_known_ids():
    p1 = Paper.create(title="Alpha Paper", doi="10.1/alpha", sources=["openalex"])
    p2 = Paper.create(title="Beta Paper", doi="10.1/beta", sources=["openalex"])
    result = deduplicate([p1, p2], exclude_ids={p1.paper_id})
    ids = {p.paper_id for p in result}
    assert p1.paper_id not in ids
    assert p2.paper_id in ids


def test_deduplicate_exclude_empty_set_is_noop():
    p1 = Paper.create(title="Alpha Paper", doi="10.1/alpha", sources=["openalex"])
    result = deduplicate([p1], exclude_ids=set())
    assert len(result) == 1
