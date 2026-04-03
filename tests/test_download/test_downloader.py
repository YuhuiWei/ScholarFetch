from __future__ import annotations
import inspect
from pathlib import Path
import re
from urllib.parse import quote

import httpx
import respx
from nexus_paper_fetcher.models import Paper, ScoreBreakdown
from nexus_paper_fetcher.download.downloader import resolve, _sanitize_title
from tests.test_download.constants import FAKE_PDF, FAKE_HTML

ELSEVIER_FULL_TEXT_RESPONSE = """<?xml version="1.0" encoding="UTF-8"?>
<full-text-retrieval-response><coredata><dc:title xmlns:dc="http://purl.org/dc/elements/1.1/">Cell Paper</dc:title></coredata></full-text-retrieval-response>
"""


def _elsevier_api_pattern() -> re.Pattern[str]:
    return re.compile(r"^https://api\.elsevier\.com/content/article/doi/.*$")


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
async def test_source1_html_falls_through_to_doi_arxiv(tmp_path):
    respx.get("https://example.com/paper.pdf").mock(
        return_value=httpx.Response(200, content=FAKE_HTML)
    )
    respx.get("https://export.arxiv.org/api/query").mock(
        return_value=httpx.Response(
            200,
            text="""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"
      xmlns:arxiv="http://arxiv.org/schemas/atom">
  <entry>
    <id>http://arxiv.org/abs/1706.03762v7</id>
    <arxiv:doi>10.5555/test.paper</arxiv:doi>
  </entry>
</feed>""",
        )
    )
    respx.get("https://arxiv.org/pdf/1706.03762v7.pdf").mock(
        return_value=httpx.Response(200, content=FAKE_PDF)
    )
    async with httpx.AsyncClient() as client:
        entry = await resolve(_paper(), rank=1, output_dir=tmp_path, session=client)
    assert entry.status == "success"
    assert entry.source_used == "arxiv"


@respx.mock
async def test_doi_resolves_to_arxiv_pdf(tmp_path):
    respx.get("https://export.arxiv.org/api/query").mock(
        return_value=httpx.Response(
            200,
            text="""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"
      xmlns:arxiv="http://arxiv.org/schemas/atom">
  <entry>
    <id>http://arxiv.org/abs/1706.03762v7</id>
    <arxiv:doi>10.5555/test.paper</arxiv:doi>
  </entry>
</feed>""",
        )
    )
    respx.get("https://arxiv.org/pdf/1706.03762v7.pdf").mock(
        return_value=httpx.Response(200, content=FAKE_PDF)
    )
    paper = _paper(open_access_pdf_url=None, arxiv_id=None)
    async with httpx.AsyncClient() as client:
        entry = await resolve(paper, rank=2, output_dir=tmp_path, session=client)
    assert entry.status == "success"
    assert entry.source_used == "arxiv"


@respx.mock
async def test_openalex_metadata_fallback_recovers_open_access_pdf(tmp_path):
    respx.get("https://api.openalex.org/works/W123").mock(
        return_value=httpx.Response(
            200,
            json={
                "best_oa_location": {
                    "pdf_url": "https://example.com/from-openalex.pdf",
                }
            },
        )
    )
    respx.get("https://example.com/from-openalex.pdf").mock(
        return_value=httpx.Response(200, content=FAKE_PDF)
    )
    paper = _paper(open_access_pdf_url=None, arxiv_id=None, openalex_id="W123")
    async with httpx.AsyncClient() as client:
        entry = await resolve(paper, rank=2, output_dir=tmp_path, session=client)
    assert entry.status == "success"
    assert entry.source_used == "open_access_url"


@respx.mock
async def test_openalex_recovery_runs_after_saved_oa_url_fails(tmp_path):
    respx.get("https://example.com/paper.pdf").mock(
        return_value=httpx.Response(200, content=FAKE_HTML)
    )
    respx.get("https://api.openalex.org/works/W123").mock(
        return_value=httpx.Response(
            200,
            json={
                "best_oa_location": {
                    "pdf_url": "https://example.com/from-openalex.pdf",
                }
            },
        )
    )
    respx.get("https://example.com/from-openalex.pdf").mock(
        return_value=httpx.Response(200, content=FAKE_PDF)
    )
    paper = _paper(openalex_id="W123")
    async with httpx.AsyncClient() as client:
        entry = await resolve(paper, rank=1, output_dir=tmp_path, session=client)
    assert entry.status == "success"
    assert entry.source_used == "open_access_url"


@respx.mock
async def test_openalex_metadata_fallback_uses_browser_headers_for_pdf_requests(tmp_path):
    respx.get("https://api.openalex.org/works/W123").mock(
        return_value=httpx.Response(
            200,
            json={
                "best_oa_location": {
                    "pdf_url": "https://example.com/from-openalex.pdf",
                }
            },
        )
    )
    respx.get("https://example.com/from-openalex.pdf").mock(
        side_effect=lambda request: httpx.Response(
            200 if request.headers.get("user-agent", "").startswith("Mozilla/5.0") else 418,
            content=FAKE_PDF if request.headers.get("user-agent", "").startswith("Mozilla/5.0") else FAKE_HTML,
        )
    )
    paper = _paper(open_access_pdf_url=None, arxiv_id=None, openalex_id="W123")
    async with httpx.AsyncClient() as client:
        entry = await resolve(paper, rank=2, output_dir=tmp_path, session=client)
    assert entry.status == "success"
    assert entry.source_used == "open_access_url"


@respx.mock
async def test_doi_mismatch_misses_arxiv(tmp_path):
    respx.get("https://export.arxiv.org/api/query").mock(
        return_value=httpx.Response(
            200,
            text="""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"
      xmlns:arxiv="http://arxiv.org/schemas/atom">
  <entry>
    <id>http://arxiv.org/abs/1706.03762v7</id>
    <arxiv:doi>10.0000/not-a-match</arxiv:doi>
  </entry>
</feed>""",
        )
    )
    respx.get("https://api.unpaywall.org/v2/10.5555/test.paper").mock(
        return_value=httpx.Response(404, json={})
    )
    paper = _paper(open_access_pdf_url=None, arxiv_id=None)
    async with httpx.AsyncClient() as client:
        entry = await resolve(paper, rank=3, output_dir=tmp_path, session=client)
    assert entry.status == "failed"


@respx.mock
async def test_doi_resolves_through_unpaywall_pdf(tmp_path):
    respx.get("https://export.arxiv.org/api/query").mock(
        return_value=httpx.Response(
            200,
            text="""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"></feed>""",
        )
    )
    respx.get("https://api.unpaywall.org/v2/10.5555/test.paper").mock(
        return_value=httpx.Response(
            200,
            json={
                "best_oa_location": {
                    "url_for_pdf": "https://example.com/unpaywall.pdf",
                }
            },
        )
    )
    respx.get("https://example.com/unpaywall.pdf").mock(
        return_value=httpx.Response(200, content=FAKE_PDF)
    )
    paper = _paper(open_access_pdf_url=None, arxiv_id=None)
    async with httpx.AsyncClient() as client:
        entry = await resolve(paper, rank=1, output_dir=tmp_path, session=client)
    assert entry.status == "success"
    assert entry.source_used == "open_access_url"


@respx.mock
async def test_doi_unpaywall_uses_env_configured_email(tmp_path, monkeypatch):
    monkeypatch.setenv("NEXUS_UNPAYWALL_EMAIL", "custom@example.edu")
    respx.get("https://export.arxiv.org/api/query").mock(
        return_value=httpx.Response(
            200,
            text="""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"></feed>""",
        )
    )
    respx.get("https://api.unpaywall.org/v2/10.5555/test.paper").mock(
        side_effect=lambda request: httpx.Response(
            200 if request.url.params.get("email") == "custom@example.edu" else 400,
            json={
                "best_oa_location": {
                    "url_for_pdf": "https://example.com/unpaywall.pdf",
                }
            },
        )
    )
    respx.get("https://example.com/unpaywall.pdf").mock(
        return_value=httpx.Response(200, content=FAKE_PDF)
    )
    paper = _paper(open_access_pdf_url=None, arxiv_id=None)
    async with httpx.AsyncClient() as client:
        entry = await resolve(paper, rank=1, output_dir=tmp_path, session=client)
    assert entry.status == "success"
    assert entry.source_used == "open_access_url"


@respx.mock
async def test_doi_unpaywall_landing_page_non_pdf_soft_fails(tmp_path):
    respx.get("https://export.arxiv.org/api/query").mock(
        return_value=httpx.Response(
            200,
            text="""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"></feed>""",
        )
    )
    respx.get("https://api.unpaywall.org/v2/10.5555/test.paper").mock(
        return_value=httpx.Response(
            200,
            json={
                "best_oa_location": {
                    "url": "https://example.com/landing-page",
                }
            },
        )
    )
    respx.get("https://example.com/landing-page").mock(
        return_value=httpx.Response(200, content=FAKE_HTML)
    )
    paper = _paper(open_access_pdf_url=None, arxiv_id=None)
    async with httpx.AsyncClient() as client:
        entry = await resolve(paper, rank=1, output_dir=tmp_path, session=client)
    assert entry.status == "failed"
    assert entry.file_path is None


@respx.mock
async def test_doi_arxiv_malformed_xml_soft_fails(tmp_path):
    respx.get("https://export.arxiv.org/api/query").mock(
        return_value=httpx.Response(200, text="<feed><entry>")
    )
    respx.get("https://api.unpaywall.org/v2/10.5555/test.paper").mock(
        return_value=httpx.Response(404, json={})
    )
    paper = _paper(open_access_pdf_url=None, arxiv_id=None)
    async with httpx.AsyncClient() as client:
        entry = await resolve(paper, rank=1, output_dir=tmp_path, session=client)
    assert entry.status == "failed"


@respx.mock
async def test_doi_unpaywall_invalid_json_soft_fails(tmp_path):
    respx.get("https://export.arxiv.org/api/query").mock(
        return_value=httpx.Response(
            200,
            text="""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"></feed>""",
        )
    )
    respx.get("https://api.unpaywall.org/v2/10.5555/test.paper").mock(
        return_value=httpx.Response(200, text="not-json")
    )
    paper = _paper(open_access_pdf_url=None, arxiv_id=None)
    async with httpx.AsyncClient() as client:
        entry = await resolve(paper, rank=1, output_dir=tmp_path, session=client)
    assert entry.status == "failed"


@respx.mock
async def test_all_sources_fail(tmp_path):
    respx.get("https://example.com/paper.pdf").mock(
        return_value=httpx.Response(200, content=FAKE_HTML)
    )
    respx.get("https://export.arxiv.org/api/query").mock(
        return_value=httpx.Response(
            200,
            text="""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"></feed>""",
        )
    )
    respx.get("https://api.unpaywall.org/v2/10.5555/test.paper").mock(
        return_value=httpx.Response(404, json={})
    )
    paper = _paper(arxiv_id=None)
    async with httpx.AsyncClient() as client:
        entry = await resolve(paper, rank=1, output_dir=tmp_path, session=client)
    assert entry.status == "failed"
    assert entry.file_path is None
    assert entry.error is not None


@respx.mock
async def test_elsevier_full_text_xml_fallback(tmp_path, monkeypatch):
    monkeypatch.setenv("ELSEVIER_API_KEY", "test-key")
    respx.get("https://export.arxiv.org/api/query").mock(
        return_value=httpx.Response(
            200,
            text="""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"></feed>""",
        )
    )
    respx.get("https://api.unpaywall.org/v2/10.1016/j.cell.2024.01.026").mock(
        return_value=httpx.Response(404, json={})
    )
    def elsevier_side_effect(request: httpx.Request) -> httpx.Response:
        expected_doi = "10.1016/j.cell.2024.01.026"
        encoded_doi = quote(expected_doi, safe="")
        path = request.url.path
        if expected_doi not in path and encoded_doi not in path:
            return httpx.Response(400)
        if request.headers.get("X-ELS-APIKey") != "test-key":
            return httpx.Response(401)
        if "application/xml" not in request.headers.get("Accept", ""):
            return httpx.Response(406)
        if request.url.params.get("view") != "FULL":
            return httpx.Response(400)
        return httpx.Response(
            200, content=ELSEVIER_FULL_TEXT_RESPONSE.encode("utf-8")
        )

    elsevier_route = respx.get(_elsevier_api_pattern()).mock(
        side_effect=elsevier_side_effect
    )
    paper = _paper(
        doi="10.1016/j.cell.2024.01.026",
        open_access_pdf_url=None,
        arxiv_id=None,
    )
    async with httpx.AsyncClient() as client:
        entry = await resolve(paper, rank=6, output_dir=tmp_path, session=client)
    assert elsevier_route.call_count == 1
    assert entry.status == "success"
    assert entry.source_used == "elsevier_api"
    assert entry.file_path is not None
    entry_path = Path(entry.file_path)
    assert entry_path.exists()
    assert entry_path.suffix == ".xml"
    entry_bytes = entry_path.read_bytes()
    assert entry_bytes.lstrip().startswith(b"<?xml")
    assert entry.file_size_kb == len(entry_bytes) // 1024
    assert entry.error is None


@respx.mock
async def test_elsevier_skips_without_api_key(tmp_path, monkeypatch):
    monkeypatch.delenv("ELSEVIER_API_KEY", raising=False)
    respx.get("https://export.arxiv.org/api/query").mock(
        return_value=httpx.Response(
            200,
            text="""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"></feed>""",
        )
    )
    respx.get("https://api.unpaywall.org/v2/10.1016/j.cell.2024.01.026").mock(
        return_value=httpx.Response(404, json={})
    )
    elsevier_route = respx.get(_elsevier_api_pattern()).mock(
        return_value=httpx.Response(
            200,
            content=ELSEVIER_FULL_TEXT_RESPONSE.encode("utf-8"),
        )
    )
    paper = _paper(
        doi="10.1016/j.cell.2024.01.026",
        open_access_pdf_url=None,
        arxiv_id=None,
    )
    async with httpx.AsyncClient() as client:
        entry = await resolve(paper, rank=6, output_dir=tmp_path, session=client)
    assert entry.status == "failed"
    assert elsevier_route.call_count == 0


@respx.mock
async def test_non_elsevier_doi_does_not_call_elsevier(tmp_path, monkeypatch):
    monkeypatch.setenv("ELSEVIER_API_KEY", "test-key")
    respx.get("https://export.arxiv.org/api/query").mock(
        return_value=httpx.Response(
            200,
            text="""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"></feed>""",
        )
    )
    respx.get("https://api.unpaywall.org/v2/10.5555/test.paper").mock(
        return_value=httpx.Response(404, json={})
    )
    elsevier_route = respx.get(_elsevier_api_pattern()).mock(
        return_value=httpx.Response(
            200,
            content=ELSEVIER_FULL_TEXT_RESPONSE.encode("utf-8"),
        )
    )
    paper = _paper(open_access_pdf_url=None, arxiv_id=None)
    async with httpx.AsyncClient() as client:
        entry = await resolve(paper, rank=7, output_dir=tmp_path, session=client)
    assert entry.status == "failed"
    assert elsevier_route.call_count == 0


def test_resolve_signature_has_no_ezproxy_controls():
    params = inspect.signature(resolve).parameters
    assert "ezproxy" not in params
    assert "skip_ezproxy" not in params


@respx.mock
async def test_pdf_validation_rejects_html(tmp_path):
    # Both sources return HTML — must fail, not write HTML to disk
    respx.get("https://example.com/paper.pdf").mock(
        return_value=httpx.Response(200, content=FAKE_HTML)
    )
    respx.get("https://export.arxiv.org/api/query").mock(
        return_value=httpx.Response(
            200,
            text="""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"
      xmlns:arxiv="http://arxiv.org/schemas/atom">
  <entry>
    <id>http://arxiv.org/abs/1706.03762v7</id>
    <arxiv:doi>10.5555/test.paper</arxiv:doi>
  </entry>
</feed>""",
        )
    )
    respx.get("https://arxiv.org/pdf/1706.03762v7.pdf").mock(
        return_value=httpx.Response(200, content=FAKE_HTML)
    )
    respx.get("https://api.unpaywall.org/v2/10.5555/test.paper").mock(
        return_value=httpx.Response(
            200,
            json={
                "best_oa_location": {
                    "url_for_pdf": "https://example.com/unpaywall.pdf",
                }
            },
        )
    )
    respx.get("https://example.com/unpaywall.pdf").mock(
        return_value=httpx.Response(200, content=FAKE_HTML)
    )
    async with httpx.AsyncClient() as client:
        entry = await resolve(_paper(), rank=1, output_dir=tmp_path, session=client)
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
