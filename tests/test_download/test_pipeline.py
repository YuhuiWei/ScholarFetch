from __future__ import annotations
import json
from pathlib import Path
import httpx
import pytest
import respx
import typer
from nexus_paper_fetcher.models import Paper, RunResult, ScoreBreakdown, SearchQuery
from nexus_paper_fetcher.download.manifest import (
    DownloadSummary,
    Manifest,
    ManifestEntry,
    load_manifest,
    save_manifest,
)
from nexus_paper_fetcher.download.pipeline import run_download, run_download_for_result
from tests.test_download.constants import FAKE_PDF


def _make_default_three_papers() -> list[Paper]:
    return [
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


def _mock_default_three_paper_routes() -> None:
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


def _make_results_file(tmp_path: Path, papers: list[Paper] | None = None) -> Path:
    if papers is None:
        papers = _make_default_three_papers()
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


def _entry_by_paper_id(manifest: Manifest) -> dict[str, ManifestEntry]:
    return {entry.paper_id: entry for entry in manifest.entries}


def _assert_success_entry_metadata(
    entry: ManifestEntry,
    paper: Paper,
    *,
    rank: int,
    score: float,
    source_used: str,
    output_dir: Path,
    suffix: str = ".pdf",
) -> None:
    assert entry.paper_id == paper.paper_id
    assert entry.title == paper.title
    assert entry.rank == rank
    assert entry.score == pytest.approx(score)
    assert entry.status == "success"
    assert entry.source_used == source_used
    assert entry.file_path is not None
    file_path = Path(entry.file_path)
    assert file_path.parent == output_dir
    assert file_path.suffix == suffix
    assert file_path.exists()


def _setup_rerun_skip_fixture(tmp_path: Path):
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
    existing_entry = ManifestEntry(
        paper_id=papers[0].paper_id,
        title=papers[0].title,
        rank=1,
        score=0.9,
        status="success",
        source_used="open_access_url",
        file_path=str(output_dir / "rank_01_paper_one_open_access.pdf"),
        file_size_kb=100,
    )
    save_manifest(Manifest(entries=[existing_entry]), output_dir / "manifest.json")
    open_access_route = respx.get("https://example.com/p1.pdf").mock(
        return_value=httpx.Response(200, content=FAKE_PDF)
    )
    arxiv_query_route = respx.get("https://export.arxiv.org/api/query").mock(
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
    arxiv_pdf_route = respx.get("https://arxiv.org/pdf/2201.00001v1.pdf").mock(
        return_value=httpx.Response(200, content=FAKE_PDF)
    )
    return papers, output_dir, existing_entry, open_access_route, arxiv_query_route, arxiv_pdf_route


@respx.mock
async def test_full_run_produces_correct_manifest(tmp_path):
    papers = _make_default_three_papers()
    _mock_default_three_paper_routes()
    output_dir = tmp_path / "papers"
    manifest = await run_download(_make_results_file(tmp_path, papers=papers), output_dir)
    assert sum(1 for e in manifest.entries if e.status == "success") == 2
    assert sum(1 for e in manifest.entries if e.status == "failed") == 1
    assert len(manifest.entries) == 3

    by_paper = {entry.paper_id: entry for entry in manifest.entries}
    assert set(by_paper) == {paper.paper_id for paper in papers}

    open_access_entry = by_paper[papers[0].paper_id]
    assert open_access_entry.title == papers[0].title
    assert open_access_entry.rank == 1
    assert open_access_entry.score == pytest.approx(0.9)
    assert open_access_entry.status == "success"
    assert open_access_entry.source_used == "open_access_url"
    assert open_access_entry.file_path is not None
    assert Path(open_access_entry.file_path).parent == output_dir
    assert Path(open_access_entry.file_path).suffix == ".pdf"
    assert Path(open_access_entry.file_path).exists()

    arxiv_entry = by_paper[papers[1].paper_id]
    assert arxiv_entry.title == papers[1].title
    assert arxiv_entry.rank == 2
    assert arxiv_entry.score == pytest.approx(0.8)
    assert arxiv_entry.status == "success"
    assert arxiv_entry.source_used == "arxiv"
    assert arxiv_entry.file_path is not None
    assert Path(arxiv_entry.file_path).parent == output_dir
    assert Path(arxiv_entry.file_path).suffix == ".pdf"
    assert Path(arxiv_entry.file_path).exists()

    failed_entry = by_paper[papers[2].paper_id]
    assert failed_entry.title == papers[2].title
    assert failed_entry.rank == 3
    assert failed_entry.score == pytest.approx(0.7)
    assert failed_entry.status == "failed"
    assert failed_entry.file_path is None
    assert failed_entry.error is not None


@respx.mock
async def test_manifest_written_to_disk(tmp_path):
    papers = _make_default_three_papers()
    _mock_default_three_paper_routes()
    output_dir = tmp_path / "papers"
    await run_download(_make_results_file(tmp_path, papers=papers), output_dir)
    saved = load_manifest(output_dir / "manifest.json")
    assert len(saved.entries) == 3

    by_paper = {entry.paper_id: entry for entry in saved.entries}
    assert set(by_paper) == {paper.paper_id for paper in papers}
    assert by_paper[papers[0].paper_id].rank == 1
    assert by_paper[papers[0].paper_id].score == pytest.approx(0.9)
    assert by_paper[papers[0].paper_id].source_used == "open_access_url"
    assert by_paper[papers[1].paper_id].rank == 2
    assert by_paper[papers[1].paper_id].score == pytest.approx(0.8)
    assert by_paper[papers[1].paper_id].source_used == "arxiv"
    assert by_paper[papers[2].paper_id].rank == 3
    assert by_paper[papers[2].paper_id].score == pytest.approx(0.7)
    assert by_paper[papers[2].paper_id].status == "failed"
    assert by_paper[papers[2].paper_id].error is not None


@respx.mock
async def test_rerun_skips_successful_paper(tmp_path):
    papers, output_dir, _, open_access_route, arxiv_query_route, arxiv_pdf_route = (
        _setup_rerun_skip_fixture(tmp_path)
    )

    manifest = await run_download(
        _make_results_file(tmp_path, papers=papers), output_dir
    )
    assert len(manifest.entries) == 2
    paper_ids = [entry.paper_id for entry in manifest.entries]
    assert set(paper_ids) == {papers[0].paper_id, papers[1].paper_id}
    assert paper_ids.count(papers[0].paper_id) == 1
    assert paper_ids.count(papers[1].paper_id) == 1
    successes = {e.paper_id for e in manifest.entries if e.status == "success"}
    assert papers[0].paper_id in successes
    assert papers[1].paper_id in successes
    assert open_access_route.call_count == 0
    assert arxiv_query_route.call_count == 1
    assert arxiv_pdf_route.call_count == 1


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

    open_access_route = respx.get("https://example.com/p1.pdf").mock(
        return_value=httpx.Response(200, content=FAKE_PDF)
    )
    arxiv_query_route = respx.get("https://export.arxiv.org/api/query").mock(
        return_value=httpx.Response(
            200,
            text="""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"></feed>""",
        )
    )
    unpaywall_route = respx.get("https://api.unpaywall.org/v2/10.1234/nope").mock(
        return_value=httpx.Response(404, json={})
    )

    manifest = await run_download(_make_results_file(tmp_path, papers=papers), output_dir)
    assert len(manifest.entries) == 1
    assert manifest.entries[0].status == "success"
    assert manifest.entries[0].source_used == "open_access_url"
    assert open_access_route.call_count == 0
    assert arxiv_query_route.call_count == 0
    assert unpaywall_route.call_count == 0


@respx.mock
async def test_top_n_limits_papers_processed(tmp_path):
    respx.get("https://example.com/p1.pdf").mock(
        return_value=httpx.Response(200, content=FAKE_PDF)
    )
    respx.get("https://api.unpaywall.org/v2/10.1234/nope").mock(
        return_value=httpx.Response(404, json={})
    )
    papers = _make_default_three_papers()
    output_dir = tmp_path / "papers"
    manifest = await run_download(
        _make_results_file(tmp_path, papers=papers), output_dir, top_n=1
    )
    assert len(manifest.entries) == 1
    kept = manifest.entries[0]
    assert kept.paper_id == papers[0].paper_id
    assert kept.rank == 1
    assert kept.title == papers[0].title
    assert kept.status == "success"
    assert kept.file_path is not None
    assert Path(kept.file_path).exists()
    assert manifest.download_summary == DownloadSummary(
        requested_success_count=1,
        candidate_count=3,
        attempted_count=1,
        already_downloaded_count=0,
        downloaded_count=1,
        available_count=1,
        failed_count=0,
        shortfall_count=0,
        backup_candidates=[],
    )


@respx.mock
async def test_top_n_targets_successful_downloads_instead_of_candidate_count(tmp_path):
    rank_2_route = respx.get("https://example.com/rank-2.pdf").mock(
        return_value=httpx.Response(200, content=FAKE_PDF)
    )
    rank_4_route = respx.get("https://example.com/rank-4.pdf").mock(
        return_value=httpx.Response(200, content=FAKE_PDF)
    )
    rank_5_route = respx.get("https://example.com/rank-5.pdf").mock(
        return_value=httpx.Response(200, content=FAKE_PDF)
    )

    papers = [
        Paper.create(title="Rank 1 No Download", year=2024, scores=ScoreBreakdown(composite=0.95)),
        Paper.create(
            title="Rank 2 Downloadable",
            open_access_pdf_url="https://example.com/rank-2.pdf",
            year=2024,
            scores=ScoreBreakdown(composite=0.9),
        ),
        Paper.create(title="Rank 3 No Download", year=2024, scores=ScoreBreakdown(composite=0.85)),
        Paper.create(
            title="Rank 4 Downloadable",
            open_access_pdf_url="https://example.com/rank-4.pdf",
            year=2024,
            scores=ScoreBreakdown(composite=0.8),
        ),
        Paper.create(
            title="Rank 5 Should Not Be Reached",
            open_access_pdf_url="https://example.com/rank-5.pdf",
            year=2024,
            scores=ScoreBreakdown(composite=0.75),
        ),
    ]

    output_dir = tmp_path / "papers"
    manifest = await run_download(
        _make_results_file(tmp_path, papers=papers),
        output_dir,
        top_n=2,
    )

    assert len(manifest.entries) == 4
    assert {entry.paper_id for entry in manifest.entries} == {paper.paper_id for paper in papers[:4]}
    assert sum(1 for entry in manifest.entries if entry.status == "success") == 2
    assert sum(1 for entry in manifest.entries if entry.status == "failed") == 2
    assert rank_2_route.call_count == 1
    assert rank_4_route.call_count == 1
    assert rank_5_route.call_count == 0
    assert manifest.download_summary == DownloadSummary(
        requested_success_count=2,
        candidate_count=5,
        attempted_count=4,
        already_downloaded_count=0,
        downloaded_count=2,
        available_count=2,
        failed_count=2,
        shortfall_count=0,
        backup_candidates=[
            ManifestEntry(
                paper_id=papers[0].paper_id,
                title=papers[0].title,
                rank=1,
                score=0.95,
                status="failed",
                error="no downloadable source found",
            ),
            ManifestEntry(
                paper_id=papers[2].paper_id,
                title=papers[2].title,
                rank=3,
                score=0.85,
                status="failed",
                error="no downloadable source found",
            ),
        ],
    )


@respx.mock
async def test_top_n_reports_shortfall_when_ranked_results_cannot_fill_target(tmp_path):
    _mock_default_three_paper_routes()
    output_dir = tmp_path / "papers"
    manifest = await run_download(
        _make_results_file(tmp_path, papers=_make_default_three_papers()),
        output_dir,
        top_n=3,
    )

    assert manifest.download_summary == DownloadSummary(
        requested_success_count=3,
        candidate_count=3,
        attempted_count=3,
        already_downloaded_count=0,
        downloaded_count=2,
        available_count=2,
        failed_count=1,
        shortfall_count=1,
        backup_candidates=[
            ManifestEntry(
                paper_id=_make_default_three_papers()[2].paper_id,
                title=_make_default_three_papers()[2].title,
                rank=3,
                score=0.7,
                status="failed",
                error="no downloadable source found",
            ),
        ],
    )


async def test_run_download_rejects_non_positive_top_n(tmp_path):
    with pytest.raises((ValueError, typer.BadParameter), match=r"(?i)top.*positive"):
        await run_download(_make_results_file(tmp_path), tmp_path / "papers", top_n=0)


async def test_run_download_for_result_rejects_non_positive_top_n(tmp_path):
    run_result = RunResult(
        query="in-memory query",
        domain_category="cs_ml",
        params=SearchQuery(query="in-memory query"),
        sources_used=["openalex"],
        papers=_make_default_three_papers(),
    )

    with pytest.raises((ValueError, typer.BadParameter), match=r"(?i)top.*positive"):
        await run_download_for_result(run_result, tmp_path / "papers", top_n=0)


@respx.mock
async def test_run_download_for_result_accepts_in_memory_run_result(tmp_path):
    papers = _make_default_three_papers()
    run_result = RunResult(
        query="in-memory query",
        domain_category="cs_ml",
        params=SearchQuery(query="in-memory query"),
        sources_used=["openalex"],
        papers=papers,
    )
    _mock_default_three_paper_routes()

    output_dir = tmp_path / "papers"
    manifest = await run_download_for_result(run_result, output_dir, top_n=1)

    assert len(manifest.entries) == 1
    _assert_success_entry_metadata(
        manifest.entries[0],
        papers[0],
        rank=1,
        score=0.9,
        source_used="open_access_url",
        output_dir=output_dir,
    )
    saved = load_manifest(output_dir / "manifest.json")
    assert len(saved.entries) == 1
    saved_entry = saved.entries[0]
    _assert_success_entry_metadata(
        saved_entry,
        papers[0],
        rank=1,
        score=0.9,
        source_used="open_access_url",
        output_dir=output_dir,
    )
    assert saved_entry.model_dump() == manifest.entries[0].model_dump()


@respx.mock
async def test_run_download_for_result_rerun_skips_existing_success_entries(tmp_path):
    papers, output_dir, existing_entry, open_access_route, arxiv_query_route, arxiv_pdf_route = (
        _setup_rerun_skip_fixture(tmp_path)
    )
    run_result = RunResult(
        query="in-memory rerun",
        domain_category="cs_ml",
        params=SearchQuery(query="in-memory rerun"),
        sources_used=["openalex"],
        papers=papers,
    )

    manifest = await run_download_for_result(run_result, output_dir)

    assert len(manifest.entries) == 2
    by_paper = _entry_by_paper_id(manifest)
    assert set(by_paper) == {papers[0].paper_id, papers[1].paper_id}
    assert by_paper[papers[0].paper_id].status == "success"
    _assert_success_entry_metadata(
        by_paper[papers[1].paper_id],
        papers[1],
        rank=2,
        score=0.8,
        source_used="arxiv",
        output_dir=output_dir,
    )
    saved = load_manifest(output_dir / "manifest.json")
    assert len(saved.entries) == 2
    saved_by_paper = _entry_by_paper_id(saved)
    skipped = by_paper[papers[0].paper_id]
    saved_skipped = saved_by_paper[papers[0].paper_id]
    assert skipped.paper_id == existing_entry.paper_id
    assert skipped.title == existing_entry.title
    assert skipped.rank == existing_entry.rank
    assert skipped.score == pytest.approx(existing_entry.score)
    assert skipped.status == existing_entry.status
    assert skipped.source_used == existing_entry.source_used
    assert skipped.file_path == existing_entry.file_path
    assert skipped.file_size_kb == existing_entry.file_size_kb
    assert skipped.error == existing_entry.error
    assert saved_skipped.model_dump() == existing_entry.model_dump()
    _assert_success_entry_metadata(
        saved_by_paper[papers[1].paper_id],
        papers[1],
        rank=2,
        score=0.8,
        source_used="arxiv",
        output_dir=output_dir,
    )
    assert saved_by_paper[papers[0].paper_id].model_dump() == by_paper[papers[0].paper_id].model_dump()
    assert saved_by_paper[papers[1].paper_id].model_dump() == by_paper[papers[1].paper_id].model_dump()
    assert open_access_route.call_count == 0
    assert arxiv_query_route.call_count == 1
    assert arxiv_pdf_route.call_count == 1


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
    elsevier_route = respx.get(
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
    assert elsevier_route.call_count >= 1
    assert entry.file_path is not None
    file_path = Path(entry.file_path)
    assert file_path.parent == output_dir
    assert file_path.suffix == ".xml"
    assert file_path.exists()


# ── CLI smoke tests ────────────────────────────────────────────────────────

@respx.mock
def test_cli_download_command(tmp_path):
    """nexus download results.json writes manifest/output for a valid input."""
    from typer.testing import CliRunner
    from nexus_paper_fetcher.cli import app

    _mock_default_three_paper_routes()

    results_path = _make_results_file(tmp_path)
    output_dir = tmp_path / "papers"
    runner = CliRunner()
    result = runner.invoke(
        app,
        ["download", str(results_path), "--output-dir", str(output_dir)],
    )
    assert result.exit_code == 0, result.output
    manifest_path = output_dir / "manifest.json"
    assert manifest_path.exists()
    saved_manifest = load_manifest(manifest_path)
    assert len(saved_manifest.entries) == 3
    assert sum(1 for entry in saved_manifest.entries if entry.status == "success") == 2
    assert sum(1 for entry in saved_manifest.entries if entry.status == "failed") == 1
    assert any(Path(entry.file_path).exists() for entry in saved_manifest.entries if entry.file_path)


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
