import json
from unittest.mock import AsyncMock, MagicMock, patch

from scholar_fetch.nlp import parse_natural_language_query


async def test_parse_natural_language_query_reads_keyword_count(monkeypatch):
    import scholar_fetch.nlp as nlp

    monkeypatch.setattr(nlp, "config", type("c", (), {"OPENAI_API_KEY": "fake"})())

    mock_response = MagicMock()
    mock_response.choices[0].message.content = json.dumps(
        {
            "query": "transformer",
            "top_n": 10,
            "year_from": 2016,
            "keyword_count": 7,
            "domain_category": "cs_ml",
        }
    )

    with patch("openai.AsyncOpenAI") as mock_cls:
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
        mock_cls.return_value = mock_client

        search_query, domain = await parse_natural_language_query("top 10 transformer papers with 7 expansion keywords")

    assert search_query.query == "transformer"
    assert search_query.top_n == 10
    assert search_query.year_from == 2016
    assert search_query.keyword_count == 7
    assert domain == "cs_ml"


async def test_parse_natural_language_query_keeps_zero_keyword_count(monkeypatch):
    import scholar_fetch.nlp as nlp

    monkeypatch.setattr(nlp, "config", type("c", (), {"OPENAI_API_KEY": "fake"})())

    mock_response = MagicMock()
    mock_response.choices[0].message.content = json.dumps(
        {
            "query": "transformer",
            "keyword_count": 0,
        }
    )

    with patch("openai.AsyncOpenAI") as mock_cls:
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
        mock_cls.return_value = mock_client

        search_query, _ = await parse_natural_language_query("transformer papers with no keyword expansion")

    assert search_query.keyword_count == 0


async def test_parse_natural_language_query_reads_lookup_weight_and_venue_fields(monkeypatch):
    import scholar_fetch.nlp as nlp

    monkeypatch.setattr(nlp, "config", type("c", (), {"OPENAI_API_KEY": "fake"})())

    mock_response = MagicMock()
    mock_response.choices[0].message.content = json.dumps(
        {
            "query": "transformer papers",
            "paper_titles": ["Attention Is All You Need"],
            "weight_preferences": ["citation", "high_impact"],
            "venue_preferences": ["top tier cs conference"],
        }
    )

    with patch("openai.AsyncOpenAI") as mock_cls:
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
        mock_cls.return_value = mock_client

        search_query, _ = await parse_natural_language_query("find Attention Is All You Need and emphasize cited papers")

    assert search_query.paper_titles == ["Attention Is All You Need"]
    assert search_query.weight_preferences == ["citation", "high_impact"]
    assert search_query.venue_preferences == ["top tier cs conference"]


async def test_parse_natural_language_query_reads_publication_categories_and_logic(monkeypatch):
    import scholar_fetch.nlp as nlp

    monkeypatch.setattr(nlp, "config", type("c", (), {"OPENAI_API_KEY": "fake"})())

    mock_response = MagicMock()
    mock_response.choices[0].message.content = json.dumps(
        {
            "query": "single-cell RNA",
            "publication_categories": ["review", "methods"],
            "keyword_logic": "OR",
        }
    )

    with patch("openai.AsyncOpenAI") as mock_cls:
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
        mock_cls.return_value = mock_client

        search_query, _ = await parse_natural_language_query("review papers OR methods papers on single-cell RNA")

    assert search_query.publication_categories == ["review", "methods"]
    assert search_query.keyword_logic == "OR"


async def test_parse_natural_language_query_fallback_detects_exact_venue_and_auto_logic(monkeypatch):
    import scholar_fetch.nlp as nlp

    monkeypatch.setattr(nlp, "config", type("c", (), {"OPENAI_API_KEY": ""})())

    search_query, domain = await parse_natural_language_query("find 10 best paper from neurips")

    assert domain is None
    assert "NeurIPS" in search_query.venue_preferences
    assert search_query.keyword_logic == "AUTO"
    assert "citation" in search_query.weight_preferences
    assert "high_impact" in search_query.weight_preferences


async def test_parse_natural_language_query_fallback_detects_lookup_intent(monkeypatch):
    import scholar_fetch.nlp as nlp

    monkeypatch.setattr(nlp, "config", type("c", (), {"OPENAI_API_KEY": ""})())

    search_query, domain = await parse_natural_language_query(
        'find the paper "Attention Is All You Need"'
    )

    assert domain is None
    assert search_query.paper_titles == ["Attention Is All You Need"]
    assert getattr(search_query, "query_intent", None) == "paper_lookup"


async def test_parse_natural_language_query_fallback_reads_requested_result_count(monkeypatch):
    import scholar_fetch.nlp as nlp

    monkeypatch.setattr(nlp, "config", type("c", (), {"OPENAI_API_KEY": ""})())

    search_query, _ = await parse_natural_language_query(
        "find 10 paper in recent computer vision deep representation study"
    )

    assert search_query.top_n == 10


async def test_parse_natural_language_query_fallback_detects_domain_download_intent(monkeypatch):
    import scholar_fetch.nlp as nlp

    monkeypatch.setattr(nlp, "config", type("c", (), {"OPENAI_API_KEY": ""})())

    search_query, domain = await parse_natural_language_query(
        "download 10 papers about graph transformers"
    )

    assert domain is None
    assert search_query.query == "graph transformers"
    assert search_query.top_n == 10
    assert search_query.download_requested is True
    assert search_query.download_top_n == 10
    assert search_query.query_intent == "domain_search"


async def test_parse_natural_language_query_fallback_detects_lookup_download_intent(monkeypatch):
    import scholar_fetch.nlp as nlp

    monkeypatch.setattr(nlp, "config", type("c", (), {"OPENAI_API_KEY": ""})())

    search_query, domain = await parse_natural_language_query(
        'download the paper "Attention Is All You Need"'
    )

    assert domain is None
    assert search_query.query == "Attention Is All You Need"
    assert search_query.paper_titles == ["Attention Is All You Need"]
    assert search_query.download_requested is True
    assert search_query.download_top_n is None
    assert search_query.query_intent == "paper_lookup"
