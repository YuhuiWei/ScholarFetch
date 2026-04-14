import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from scholar_fetch.domain import classify_domain, _keyword_classify


def test_keyword_classify_biology():
    assert "biology" in _keyword_classify("single cell RNA sequencing")
    assert "biology" in _keyword_classify("protein folding dynamics")
    assert "biology" in _keyword_classify("CRISPR gene editing")


def test_keyword_classify_chemistry():
    assert "chemistry" in _keyword_classify("organic synthesis reaction")
    assert "chemistry" in _keyword_classify("polymer catalyst")


def test_keyword_classify_default_cs_ml():
    assert _keyword_classify("attention mechanisms transformers") == ["cs_ml"]
    assert _keyword_classify("neural network optimization") == ["cs_ml"]


def test_keyword_classify_interdisciplinary():
    # "large language model" (cs_ml) + "medical" (biology)
    result = _keyword_classify("large language model for medical diagnosis")
    assert "cs_ml" in result
    assert "biology" in result


def test_keyword_classify_returns_list():
    result = _keyword_classify("single cell RNA")
    assert isinstance(result, list)
    assert len(result) >= 1


async def test_classify_uses_override_single():
    result = await classify_domain("any query", override="biology")
    assert result == ["biology"]


async def test_classify_uses_override_multi():
    result = await classify_domain("any query", override="cs_ml,biology")
    assert "cs_ml" in result
    assert "biology" in result


async def test_classify_invalid_override_raises():
    with pytest.raises(ValueError, match="Invalid domain categor"):
        await classify_domain("query", override="invalid_domain")


async def test_classify_no_api_key_uses_keywords(monkeypatch):
    import scholar_fetch.domain as dom
    monkeypatch.setattr(dom, "config", type("c", (), {"OPENAI_API_KEY": ""})())
    result = await classify_domain("protein folding")
    assert "biology" in result


async def test_classify_with_api_key_uses_openai(monkeypatch):
    import scholar_fetch.domain as dom
    monkeypatch.setattr(dom, "config", type("c", (), {"OPENAI_API_KEY": "fake"})())

    mock_response = MagicMock()
    mock_response.choices[0].message.content = "cs_ml,biology"

    with patch("scholar_fetch.domain.AsyncOpenAI") as mock_cls:
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
        mock_cls.return_value = mock_client
        result = await classify_domain("LLM for clinical diagnosis")
    assert "cs_ml" in result
    assert "biology" in result


async def test_classify_openai_single_domain(monkeypatch):
    import scholar_fetch.domain as dom
    monkeypatch.setattr(dom, "config", type("c", (), {"OPENAI_API_KEY": "fake"})())

    mock_response = MagicMock()
    mock_response.choices[0].message.content = "biology"

    with patch("scholar_fetch.domain.AsyncOpenAI") as mock_cls:
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
        mock_cls.return_value = mock_client
        result = await classify_domain("single cell RNA")
    assert result == ["biology"]


async def test_classify_openai_failure_falls_back_to_keywords(monkeypatch):
    import scholar_fetch.domain as dom
    monkeypatch.setattr(dom, "config", type("c", (), {"OPENAI_API_KEY": "fake"})())

    with patch("scholar_fetch.domain.AsyncOpenAI") as mock_cls:
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(side_effect=Exception("API down"))
        mock_cls.return_value = mock_client
        result = await classify_domain("gene expression analysis")
    assert "biology" in result  # keyword fallback
