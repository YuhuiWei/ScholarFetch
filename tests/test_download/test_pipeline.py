from __future__ import annotations
import json
from pathlib import Path
import httpx
import respx
from nexus_paper_fetcher.models import Paper, RunResult, ScoreBreakdown, SearchQuery
from nexus_paper_fetcher.download.manifest import Manifest, ManifestEntry, load_manifest, save_manifest
from nexus_paper_fetcher.download.pipeline import run_download
from tests.test_download.constants import FAKE_PDF


def _make_results_file(tmp_path: Path, papers: list[Paper] | None = None) -> Path:
    if papers is None:
        papers = [
            Paper.create(
                title="Paper One Open Access",
                open_access_pdf_url="https://example.com/p1.pdf",
                year=2022,
                scores=ScoreBreakdown(composite=0.9),
            ),
            Paper.create(
                title="Paper Two DOI to Arxiv",
                doi="10.5555/p2",
                year=2022,
                scores=ScoreBreakdown(composite=0.8),
            ),
            Paper.create(
                title="Paper Three No Free Source",
                doi="10.1234/nope",
                year=2022,
                scores=ScoreBreakdown(composite=0.7),
            ),
        ]
    run_result = RunResult(
        query="test query",
        domain_category="cs_ml",
        params=SearchQuery(query="test query"),
        sources_used=["openalex"],
        papers=papers,
    )
    path = tmp_path / "results.json"
    path.write_text(
        json.dumps(run_result.model_dump(mode="json"), default=str)
    )
    return path


@respx.mock
async def test_full_run_produces_correct_manifest(tmp_path):
    respx.get("https://example.com/p1.pdf").mock(
        return_value=httpx.Response(200, content=FAKE_PDF)
    )
    respx.get("https://export.arxiv.org/api/query").mock(
        side_effect=lambda request: httpx.Response(
            200,
            text="""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"
      xmlns:arxiv="http://arxiv.org/schemas/atom">
  <entry>
    <id>http://arxiv.org/abs/2201.00001v1</id>
    <arxiv:doi>10.5555/p2</arxiv:doi>
  </entry>
</feed>"""
            if "10.5555/p2" in request.url.params.get("search_query", "")
            else """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"></feed>""",
        )
    )
    respx.get("https://arxiv.org/pdf/2201.00001v1.pdf").mock(
        return_value=httpx.Response(200, content=FAKE_PDF)
    )
    respx.get("https://api.unpaywall.org/v2/10.1234/nope").mock(
        return_value=httpx.Response(404, json={})
    )
    output_dir = tmp_path / "papers"
    manifest = await run_download(_make_results_file(tmp_path), output_dir)
    assert sum(1 for e in manifest.entries if e.status == "success") == 2
    assert sum(1 for e in manifest.entries if e.status == "failed") == 1
    assert len(manifest.entries) == 3


@respx.mock
async def test_manifest_written_to_disk(tmp_path):
    respx.get("https://example.com/p1.pdf").mock(
        return_value=httpx.Response(200, content=FAKE_PDF)
    )
    respx.get("https://export.arxiv.org/api/query").mock(
        side_effect=lambda request: httpx.Response(
            200,
            text="""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"
      xmlns:arxiv="http://arxiv.org/schemas/atom">
  <entry>
    <id>http://arxiv.org/abs/2201.00001v1</id>
    <arxiv:doi>10.5555/p2</arxiv:doi>
  </entry>
</feed>"""
            if "10.5555/p2" in request.url.params.get("search_query", "")
            else """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"></feed>""",
        )
    )
    respx.get("https://arxiv.org/pdf/2201.00001v1.pdf").mock(
        return_value=httpx.Response(200, content=FAKE_PDF)
    )
    respx.get("https://api.unpaywall.org/v2/10.1234/nope").mock(
        return_value=httpx.Response(404, json={})
    )
    output_dir = tmp_path / "papers"
    await run_download(_make_results_file(tmp_path), output_dir)
    saved = load_manifest(output_dir / "manifest.json")
    assert len(saved.entries) == 3


@respx.mock
async def test_rerun_skips_successful_paper(tmp_path):
    papers = [
        Paper.create(
            title="Paper One Open Access",
            open_access_pdf_url="https://example.com/p1.pdf",
            year=2022,
            scores=ScoreBreakdown(composite=0.9),
        ),
        Paper.create(
            title="Paper Two DOI to Arxiv",
            doi="10.5555/p2",
            year=2022,
            scores=ScoreBreakdown(composite=0.8),
        ),
    ]
    output_dir = tmp_path / "papers"
    output_dir.mkdir()

    # Pre-populate manifest: paper 1 already done
    existing = Manifest(entries=[
        ManifestEntry(
            paper_id=papers[0].paper_id,
            title=papers[0].title,
            rank=1,
            score=0.9,
            status="success",
            source_used="open_access_url",
            file_path=str(output_dir / "rank_01_paper_one_open_access.pdf"),
            file_size_kb=100,
        )
    ])
    save_manifest(existing, output_dir / "manifest.json")

    # Only paper 2 should be downloaded
    respx.get("https://export.arxiv.org/api/query").mock(
        return_value=httpx.Response(
            200,
            text="""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"
      xmlns:arxiv="http://arxiv.org/schemas/atom">
  <entry>
    <id>http://arxiv.org/abs/2201.00001v1</id>
    <arxiv:doi>10.5555/p2</arxiv:doi>
  </entry>
</feed>""",
        )
    )
    respx.get("https://arxiv.org/pdf/2201.00001v1.pdf").mock(
        return_value=httpx.Response(200, content=FAKE_PDF)
    )

    manifest = await run_download(
        _make_results_file(tmp_path, papers=papers), output_dir
    )
    successes = {e.paper_id for e in manifest.entries if e.status == "success"}
    assert papers[0].paper_id in successes
    assert papers[1].paper_id in successes


@respx.mock
async def test_rerun_with_legacy_ezproxy_manifest_entry_skips_cleanly(tmp_path):
    papers = [
        Paper.create(
            title="Paper One Open Access",
            open_access_pdf_url="https://example.com/p1.pdf",
            year=2022,
            scores=ScoreBreakdown(composite=0.9),
        ),
    ]
    output_dir = tmp_path / "papers"
    output_dir.mkdir()

    (output_dir / "manifest.json").write_text(
        json.dumps(
            {
                "entries": [
                    {
                        "paper_id": papers[0].paper_id,
                        "title": papers[0].title,
                        "rank": 1,
                        "score": 0.9,
                        "status": "success",
                        "source_used": "ezproxy",
                        "file_path": str(output_dir / "rank_01_paper_one_open_access.pdf"),
                        "file_size_kb": 100,
                        "error": None,
                    }
                ]
            }
        )
    )

    manifest = await run_download(_make_results_file(tmp_path, papers=papers), output_dir)
    assert len(manifest.entries) == 1
    assert manifest.entries[0].status == "success"
    assert manifest.entries[0].source_used == "open_access_url"


@respx.mock
async def test_top_n_limits_papers_processed(tmp_path):
    respx.get("https://example.com/p1.pdf").mock(
        return_value=httpx.Response(200, content=FAKE_PDF)
    )
    output_dir = tmp_path / "papers"
    manifest = await run_download(
        _make_results_file(tmp_path), output_dir, top_n=1
    )
    assert len(manifest.entries) == 1


@respx.mock
async def test_run_download_recovers_doi_only_paper_without_ezproxy(tmp_path):
    papers = [
        Paper.create(
            title="Recovered Through DOI Resolver",
            doi="10.5555/test.paper",
            year=2022,
            scores=ScoreBreakdown(composite=0.9),
        ),
    ]
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
    output_dir = tmp_path / "papers"
    manifest = await run_download(_make_results_file(tmp_path, papers=papers), output_dir)
    assert manifest.entries[0].status == "success"
    assert manifest.entries[0].source_used == "arxiv"


@respx.mock
async def test_run_download_recovers_openalex_pdf_for_saved_results(tmp_path):
    papers = [
        Paper.create(
            title="Recovered From OpenAlex",
            doi="10.1234/recovered",
            openalex_id="W999",
            year=2022,
            scores=ScoreBreakdown(composite=0.9),
        ),
    ]
    respx.get("https://api.openalex.org/works/W999").mock(
        return_value=httpx.Response(
            200,
            json={
                "best_oa_location": {
                    "pdf_url": "https://example.com/recovered.pdf",
                }
            },
        )
    )
    respx.get("https://example.com/recovered.pdf").mock(
        return_value=httpx.Response(200, content=FAKE_PDF)
    )
    output_dir = tmp_path / "papers"
    manifest = await run_download(_make_results_file(tmp_path, papers=papers), output_dir)
    assert len(manifest.entries) == 1
    assert manifest.entries[0].status == "success"
    assert manifest.entries[0].source_used == "open_access_url"


@respx.mock
async def test_run_download_falls_back_to_elsevier_xml_after_oa_failures(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("ELSEVIER_API_KEY", "test-key")
    papers = [
        Paper.create(
            title="Elsevier XML Fallback",
            doi="10.1016/j.cell.2024.01.026",
            year=2024,
            scores=ScoreBreakdown(composite=0.9),
        ),
    ]
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
    respx.get(
        "https://api.elsevier.com/content/article/doi/10.1016/j.cell.2024.01.026"
    ).mock(
        return_value=httpx.Response(
            200,
            content=(
                b'<?xml version="1.0" encoding="UTF-8"?>'
                b"<full-text-retrieval-response><coredata>"
                b"</coredata></full-text-retrieval-response>"
            ),
        )
    )

    output_dir = tmp_path / "papers"
    manifest = await run_download(_make_results_file(tmp_path, papers=papers), output_dir)

    assert len(manifest.entries) == 1
    entry = manifest.entries[0]
    assert entry.status == "success"
    assert entry.source_used == "elsevier_api"
    assert entry.file_path is not None
    file_path = Path(entry.file_path)
    assert file_path.suffix == ".xml"
    assert file_path.exists()


# ── CLI smoke tests ────────────────────────────────────────────────────────

@respx.mock
def test_cli_download_command(tmp_path):
    """nexus download results.json runs without error for a valid input."""
    from typer.testing import CliRunner
    from nexus_paper_fetcher.cli import app

    respx.get("https://example.com/p1.pdf").mock(
        return_value=httpx.Response(200, content=FAKE_PDF)
    )
    respx.get("https://export.arxiv.org/api/query").mock(
        side_effect=lambda request: httpx.Response(
            200,
            text="""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"
      xmlns:arxiv="http://arxiv.org/schemas/atom">
  <entry>
    <id>http://arxiv.org/abs/2201.00001v1</id>
    <arxiv:doi>10.5555/p2</arxiv:doi>
  </entry>
</feed>"""
            if "10.5555/p2" in request.url.params.get("search_query", "")
            else """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"></feed>""",
        )
    )
    respx.get("https://arxiv.org/pdf/2201.00001v1.pdf").mock(
        return_value=httpx.Response(200, content=FAKE_PDF)
    )
    respx.get("https://api.unpaywall.org/v2/10.1234/nope").mock(
        return_value=httpx.Response(404, json={})
    )

    results_path = _make_results_file(tmp_path)
    output_dir = tmp_path / "papers"
    runner = CliRunner()
    result = runner.invoke(
        app,
        ["download", str(results_path), "--output-dir", str(output_dir)],
    )
    assert result.exit_code == 0, result.output


def test_cli_missing_results_file_exits_1(tmp_path):
    from typer.testing import CliRunner
    from nexus_paper_fetcher.cli import app

    runner = CliRunner()
    result = runner.invoke(
        app,
        ["download", str(tmp_path / "nonexistent.json")],
    )
    assert result.exit_code == 1


def test_cli_skip_ezproxy_option_rejected(tmp_path):
    from typer.testing import CliRunner
    from nexus_paper_fetcher.cli import app

    runner = CliRunner()
    result = runner.invoke(
        app,
        ["download", str(tmp_path / "results.json"), "--skip-ezproxy"],
    )
    assert result.exit_code == 2
    assert "No such option: --skip-ezproxy" in result.output


def test_cli_output_dir_help_mentions_downloaded_files():
    from typer.testing import CliRunner
    from nexus_paper_fetcher.cli import app

    runner = CliRunner()
    result = runner.invoke(app, ["download", "--help"])
    assert result.exit_code == 0
    assert "Directory to save downloaded files" in result.output
    assert "Directory to save PDFs" not in result.output
