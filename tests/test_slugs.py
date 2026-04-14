from scholar_fetch.slugs import make_query_slug


def test_slug_lowercases():
    assert make_query_slug("Single-Cell RNA Sequencing") == "single-cell-rna-sequencing"


def test_slug_strips_special_chars():
    assert make_query_slug("LLM: biology & pharmacology!") == "llm-biology-pharmacology"


def test_slug_collapses_whitespace():
    assert make_query_slug("attention   mechanisms") == "attention-mechanisms"


def test_slug_truncates_at_60():
    long = "a" * 100
    assert len(make_query_slug(long)) <= 60


def test_slug_no_leading_trailing_hyphens():
    slug = make_query_slug("  ---hello world---  ")
    assert not slug.startswith("-")
    assert not slug.endswith("-")


def test_slug_example_from_spec():
    assert make_query_slug("single-cell RNA sequencing") == "single-cell-rna-sequencing"
