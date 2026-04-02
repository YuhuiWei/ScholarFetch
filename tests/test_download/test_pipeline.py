from __future__ import annotations
import json
from pathlib import Path
import httpx
import pytest
import respx
from nexus_paper_fetcher.models import Paper, RunResult, ScoreBreakdown, SearchQuery
from nexus_paper_fetcher.download.manifest import Manifest, ManifestEntry, load_manifest, save_manifest
from nexus_paper_fetcher.download.pipeline import run_download
from nexus_paper_fetcher.download.ezproxy import EZPROXY_LOGIN_URL
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
                title="Paper Two Arxiv Only",
                arxiv_id="2201.00001",
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
    respx.get("https://arxiv.org/pdf/2201.00001.pdf").mock(
        return_value=httpx.Response(200, content=FAKE_PDF)
    )
    output_dir = tmp_path / "papers"
    manifest = await run_download(
        _make_results_file(tmp_path), output_dir, skip_ezproxy=True
    )
    assert sum(1 for e in manifest.entries if e.status == "success") == 2
    assert sum(1 for e in manifest.entries if e.status == "failed") == 1
    assert len(manifest.entries) == 3


@respx.mock
async def test_manifest_written_to_disk(tmp_path):
    respx.get("https://example.com/p1.pdf").mock(
        return_value=httpx.Response(200, content=FAKE_PDF)
    )
    respx.get("https://arxiv.org/pdf/2201.00001.pdf").mock(
        return_value=httpx.Response(200, content=FAKE_PDF)
    )
    output_dir = tmp_path / "papers"
    await run_download(_make_results_file(tmp_path), output_dir, skip_ezproxy=True)
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
            title="Paper Two Arxiv Only",
            arxiv_id="2201.00001",
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
    respx.get("https://arxiv.org/pdf/2201.00001.pdf").mock(
        return_value=httpx.Response(200, content=FAKE_PDF)
    )

    manifest = await run_download(
        _make_results_file(tmp_path, papers=papers), output_dir, skip_ezproxy=True
    )
    successes = {e.paper_id for e in manifest.entries if e.status == "success"}
    assert papers[0].paper_id in successes
    assert papers[1].paper_id in successes


@respx.mock
async def test_top_n_limits_papers_processed(tmp_path):
    respx.get("https://example.com/p1.pdf").mock(
        return_value=httpx.Response(200, content=FAKE_PDF)
    )
    output_dir = tmp_path / "papers"
    manifest = await run_download(
        _make_results_file(tmp_path), output_dir, top_n=1, skip_ezproxy=True
    )
    assert len(manifest.entries) == 1


@respx.mock
async def test_ezproxy_auth_failure_still_downloads_free_sources(tmp_path, monkeypatch):
    monkeypatch.setenv("OHSU_USERNAME", "user")
    monkeypatch.setenv("OHSU_PASSWORD", "pass")
    respx.post(EZPROXY_LOGIN_URL).mock(return_value=httpx.Response(401))
    respx.get("https://example.com/p1.pdf").mock(
        return_value=httpx.Response(200, content=FAKE_PDF)
    )
    respx.get("https://arxiv.org/pdf/2201.00001.pdf").mock(
        return_value=httpx.Response(200, content=FAKE_PDF)
    )
    output_dir = tmp_path / "papers"
    manifest = await run_download(
        _make_results_file(tmp_path), output_dir, skip_ezproxy=False
    )
    assert sum(1 for e in manifest.entries if e.status == "success") == 2
