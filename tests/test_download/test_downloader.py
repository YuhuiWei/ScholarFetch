from __future__ import annotations
from pathlib import Path
from unittest.mock import AsyncMock
import httpx
import pytest
import respx
from nexus_paper_fetcher.models import Paper, ScoreBreakdown
from nexus_paper_fetcher.download.downloader import resolve, _sanitize_title
from nexus_paper_fetcher.download.ezproxy import EZProxySession
from tests.test_download.constants import FAKE_PDF, FAKE_HTML


def _paper(**overrides) -> Paper:
    defaults = dict(
        title="Attention Is All You Need",
        doi="10.5555/test.paper",
        arxiv_id="1706.03762",
        open_access_pdf_url="https://example.com/paper.pdf",
        year=2017,
        scores=ScoreBreakdown(composite=0.95),
    )
    defaults.update(overrides)
    return Paper.create(**defaults)


# ── _sanitize_title ──────────────────────────────────────────────────────────

def test_sanitize_title_six_words():
    result = _sanitize_title("Attention Is All You Need And More Words Here")
    assert result == "attention_is_all_you_need_and"


def test_sanitize_title_fewer_than_six_words():
    assert _sanitize_title("BERT Language Model") == "bert_language_model"


def test_sanitize_title_punctuation_becomes_underscore():
    result = _sanitize_title("Highly-Variable Gene Selection: A Survey")
    assert result == "highly_variable_gene_selection_a_survey"


def test_sanitize_title_no_trailing_underscore():
    result = _sanitize_title("!!!Leading Punctuation")
    assert not result.startswith("_")
    assert not result.endswith("_")


# ── resolve ──────────────────────────────────────────────────────────────────

@respx.mock
async def test_source1_open_access_url_success(tmp_path):
    respx.get("https://example.com/paper.pdf").mock(
        return_value=httpx.Response(200, content=FAKE_PDF)
    )
    async with httpx.AsyncClient() as client:
        entry = await resolve(_paper(), rank=1, output_dir=tmp_path, session=client)
    assert entry.status == "success"
    assert entry.source_used == "open_access_url"
    assert entry.file_path is not None
    assert Path(entry.file_path).exists()


@respx.mock
async def test_source1_html_falls_through_to_arxiv(tmp_path):
    respx.get("https://example.com/paper.pdf").mock(
        return_value=httpx.Response(200, content=FAKE_HTML)
    )
    respx.get("https://arxiv.org/pdf/1706.03762.pdf").mock(
        return_value=httpx.Response(200, content=FAKE_PDF)
    )
    async with httpx.AsyncClient() as client:
        entry = await resolve(_paper(), rank=1, output_dir=tmp_path, session=client)
    assert entry.status == "success"
    assert entry.source_used == "arxiv"


@respx.mock
async def test_source2_arxiv_only(tmp_path):
    respx.get("https://arxiv.org/pdf/1706.03762.pdf").mock(
        return_value=httpx.Response(200, content=FAKE_PDF)
    )
    paper = _paper(open_access_pdf_url=None)
    async with httpx.AsyncClient() as client:
        entry = await resolve(paper, rank=2, output_dir=tmp_path, session=client)
    assert entry.status == "success"
    assert entry.source_used == "arxiv"


async def test_source3_ezproxy_fallback(tmp_path):
    paper = _paper(open_access_pdf_url=None, arxiv_id=None)
    mock_ez = AsyncMock(spec=EZProxySession)
    mock_ez.get_pdf.return_value = FAKE_PDF
    async with httpx.AsyncClient() as client:
        entry = await resolve(
            paper, rank=3, output_dir=tmp_path, session=client, ezproxy=mock_ez
        )
    assert entry.status == "success"
    assert entry.source_used == "ezproxy"
    mock_ez.get_pdf.assert_called_once_with("10.5555/test.paper")


@respx.mock
async def test_all_sources_fail(tmp_path):
    respx.get("https://example.com/paper.pdf").mock(
        return_value=httpx.Response(200, content=FAKE_HTML)
    )
    paper = _paper(arxiv_id=None)
    async with httpx.AsyncClient() as client:
        entry = await resolve(paper, rank=1, output_dir=tmp_path, session=client, skip_ezproxy=True)
    assert entry.status == "failed"
    assert entry.file_path is None
    assert entry.error is not None


async def test_skip_ezproxy_never_calls_get_pdf(tmp_path):
    paper = _paper(open_access_pdf_url=None, arxiv_id=None)
    mock_ez = AsyncMock(spec=EZProxySession)
    async with httpx.AsyncClient() as client:
        entry = await resolve(
            paper, rank=1, output_dir=tmp_path, session=client,
            ezproxy=mock_ez, skip_ezproxy=True,
        )
    assert entry.status == "failed"
    mock_ez.get_pdf.assert_not_called()


@respx.mock
async def test_pdf_validation_rejects_html(tmp_path):
    # Both sources return HTML — must fail, not write HTML to disk
    respx.get("https://example.com/paper.pdf").mock(
        return_value=httpx.Response(200, content=FAKE_HTML)
    )
    respx.get("https://arxiv.org/pdf/1706.03762.pdf").mock(
        return_value=httpx.Response(200, content=FAKE_HTML)
    )
    async with httpx.AsyncClient() as client:
        entry = await resolve(_paper(), rank=1, output_dir=tmp_path, session=client, skip_ezproxy=True)
    assert entry.status == "failed"
    assert not any(tmp_path.iterdir())  # no file written


@respx.mock
async def test_file_named_by_rank_and_title(tmp_path):
    respx.get("https://example.com/paper.pdf").mock(
        return_value=httpx.Response(200, content=FAKE_PDF)
    )
    paper = _paper(title="Attention Is All You Need Extended")
    async with httpx.AsyncClient() as client:
        entry = await resolve(paper, rank=5, output_dir=tmp_path, session=client)
    assert entry.file_path is not None
    assert Path(entry.file_path).name == "rank_05_attention_is_all_you_need_extended.pdf"


@respx.mock
async def test_file_size_kb_recorded(tmp_path):
    respx.get("https://example.com/paper.pdf").mock(
        return_value=httpx.Response(200, content=FAKE_PDF)
    )
    async with httpx.AsyncClient() as client:
        entry = await resolve(_paper(), rank=1, output_dir=tmp_path, session=client)
    assert entry.file_size_kb == len(FAKE_PDF) // 1024
