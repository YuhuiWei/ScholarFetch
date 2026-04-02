import json
from unittest.mock import AsyncMock, MagicMock, patch

from nexus_paper_fetcher.methodology import classify_methodology
from nexus_paper_fetcher.models import Paper


async def test_classify_methodology_uses_compact_codes(monkeypatch):
    import nexus_paper_fetcher.methodology as methodology

    monkeypatch.setattr(methodology, "config", type("c", (), {"OPENAI_API_KEY": "fake-key"})())
    papers = [
        Paper.create(title="A Review of MRI Methods", abstract="Survey of prior work.", sources=["openalex"]),
        Paper.create(title="New MRI Reconstruction Method", abstract="We propose an algorithm.", sources=["openalex"]),
    ]

    mock_response = MagicMock()
    mock_response.choices[0].message.content = json.dumps({"categories": ["V", "M"]})

    with patch("nexus_paper_fetcher.methodology.AsyncOpenAI") as mock_cls:
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
        mock_cls.return_value = mock_client

        await classify_methodology(papers)

    assert papers[0].methodology_category == "review"
    assert papers[1].methodology_category == "method"


async def test_classify_methodology_falls_back_on_bad_json(monkeypatch):
    import nexus_paper_fetcher.methodology as methodology

    monkeypatch.setattr(methodology, "config", type("c", (), {"OPENAI_API_KEY": "fake-key"})())
    paper = Paper.create(
        title="MRI Atlas Resource",
        abstract="We release a benchmark dataset and atlas.",
        sources=["openalex"],
    )

    mock_response = MagicMock()
    mock_response.choices[0].message.content = '{"categories": ["D"'

    with patch("nexus_paper_fetcher.methodology.AsyncOpenAI") as mock_cls:
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
        mock_cls.return_value = mock_client

        await classify_methodology([paper])

    assert paper.methodology_category == "data"
