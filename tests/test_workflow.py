from __future__ import annotations

import importlib
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
import typer

from nexus_paper_fetcher.download.manifest import DownloadSummary, Manifest, ManifestEntry
from nexus_paper_fetcher.models import Paper, RunResult, SearchQuery


def _make_result(
    query: str,
    *,
    total_papers: int,
    query_intent: str = "domain_search",
    not_found: bool = False,
) -> RunResult:
    papers = [
        Paper.create(
            title=f"Paper {idx:02d}",
            year=2020 + (idx % 5),
            sources=["openalex"],
        )
        for idx in range(1, total_papers + 1)
    ]
    return RunResult(
        query=query,
        domain_category="cs_ml",
        params=SearchQuery(query=query, top_n=50, query_intent=query_intent),
        sources_used=["openalex"],
        papers=papers,
        not_found=not_found,
    )


def _load_saved_result(path: Path) -> RunResult:
    return RunResult.model_validate(json.loads(path.read_text()))


@pytest.fixture
def workflow_module():
    return importlib.import_module("nexus_paper_fetcher.workflow")


async def test_interactive_saves_full_results_and_stops_when_download_declined(
    tmp_path, monkeypatch, workflow_module
):
    result = _make_result("graph transformers", total_papers=12)
    parse_mock = AsyncMock(return_value=(SearchQuery(query="graph transformers"), "cs_ml"))
    prepare_mock = AsyncMock(return_value=SimpleNamespace())
    run_mock = AsyncMock(return_value=result)
    download_mock = AsyncMock()
    confirm_mock = Mock(return_value=False)
    prompt_mock = Mock(side_effect=AssertionError("unexpected prompt"))
    prompt_io = SimpleNamespace(confirm=confirm_mock, prompt=prompt_mock)

    monkeypatch.setattr(workflow_module, "parse_natural_language_query", parse_mock)
    monkeypatch.setattr(workflow_module, "prepare_query", prepare_mock)
    monkeypatch.setattr(workflow_module, "run", run_mock)
    monkeypatch.setattr(workflow_module, "run_download_for_result", download_mock)

    saved_results_path = tmp_path / "ranked.json"
    workflow_result = await workflow_module.run_fetch_workflow(
        query="graph transformers",
        interactive=True,
        output=saved_results_path,
        prompt_io=prompt_io,
    )

    assert saved_results_path.exists()
    saved = _load_saved_result(saved_results_path)
    assert len(saved.papers) == 12
    assert workflow_result.saved_result_path == saved_results_path
    assert workflow_result.download_requested is False
    assert workflow_result.download_executed is False
    assert hasattr(workflow_result, "download_manifest")
    assert workflow_result.download_manifest is None
    parse_mock.assert_awaited_once_with("graph transformers")
    prepare_mock.assert_awaited_once()
    run_mock.assert_awaited_once()
    prepared_query = prepare_mock.await_args.args[0]
    assert isinstance(prepared_query, SearchQuery)
    assert prepared_query.query == "graph transformers"
    assert prepare_mock.await_args.kwargs["domain_category_override"] == "cs_ml"
    assert run_mock.await_args.args[0] is prepared_query
    assert run_mock.await_args.kwargs["domain_category_override"] == "cs_ml"
    confirm_mock.assert_called_once()
    download_mock.assert_not_awaited()


async def test_non_interactive_downloads_immediately_when_download_true(
    tmp_path, monkeypatch, workflow_module
):
    result = _make_result("foundation models", total_papers=6)
    parse_mock = AsyncMock(return_value=(SearchQuery(query="foundation models"), "cs_ml"))
    prepare_mock = AsyncMock(return_value=SimpleNamespace())
    run_mock = AsyncMock(return_value=result)
    download_mock = AsyncMock(return_value=SimpleNamespace(entries=[]))
    prompt_io = SimpleNamespace(
        confirm=Mock(side_effect=AssertionError("unexpected prompt")),
        prompt=Mock(side_effect=AssertionError("unexpected prompt")),
    )

    monkeypatch.setattr(workflow_module, "parse_natural_language_query", parse_mock)
    monkeypatch.setattr(workflow_module, "prepare_query", prepare_mock)
    monkeypatch.setattr(workflow_module, "run", run_mock)
    monkeypatch.setattr(workflow_module, "run_download_for_result", download_mock)

    workflow_result = await workflow_module.run_fetch_workflow(
        query="foundation models",
        interactive=False,
        download=True,
        output=tmp_path / "ranked.json",
        output_dir=tmp_path / "papers",
        download_top=4,
        prompt_io=prompt_io,
    )

    saved = _load_saved_result(tmp_path / "ranked.json")
    assert len(saved.papers) == 6
    assert workflow_result.saved_result_path == tmp_path / "ranked.json"
    assert workflow_result.download_requested is True
    assert workflow_result.download_executed is True
    assert workflow_result.download_top == 4
    assert workflow_result.output_dir == tmp_path / "papers"
    assert workflow_result.download_manifest is not None
    parse_mock.assert_awaited_once_with("foundation models")
    prepare_mock.assert_awaited_once()
    run_mock.assert_awaited_once()
    prepared_query = prepare_mock.await_args.args[0]
    assert isinstance(prepared_query, SearchQuery)
    assert prepared_query.query == "foundation models"
    assert prepare_mock.await_args.kwargs["domain_category_override"] == "cs_ml"
    assert run_mock.await_args.args[0] is prepared_query
    assert run_mock.await_args.kwargs["domain_category_override"] == "cs_ml"
    download_mock.assert_awaited_once()
    args = download_mock.await_args.args
    kwargs = download_mock.await_args.kwargs
    assert args[0] == result
    assert args[1] == tmp_path / "papers"
    assert kwargs["top_n"] == 4


async def test_api_workflow_surfaces_download_summary_metadata(
    tmp_path, monkeypatch, workflow_module
):
    result = _make_result("connectome computer vision", total_papers=6)
    parse_mock = AsyncMock(return_value=(SearchQuery(query="connectome computer vision"), "cs_ml"))
    prepare_mock = AsyncMock(return_value=SimpleNamespace())
    run_mock = AsyncMock(return_value=result)
    manifest = Manifest(
        entries=[
            ManifestEntry(
                paper_id=result.papers[0].paper_id,
                title=result.papers[0].title,
                rank=1,
                score=0.0,
                status="failed",
                error="no downloadable source found",
            ),
            ManifestEntry(
                paper_id=result.papers[1].paper_id,
                title=result.papers[1].title,
                rank=2,
                score=0.0,
                status="success",
                source_used="open_access_url",
                file_path=str(tmp_path / "papers" / "rank_02_paper_02.pdf"),
                file_size_kb=128,
            ),
        ],
        download_summary=DownloadSummary(
            requested_success_count=3,
            candidate_count=6,
            attempted_count=4,
            already_downloaded_count=0,
            downloaded_count=2,
            available_count=2,
            failed_count=2,
            shortfall_count=1,
            backup_candidates=[
                ManifestEntry(
                    paper_id=result.papers[0].paper_id,
                    title=result.papers[0].title,
                    rank=1,
                    score=0.0,
                    status="failed",
                    error="no downloadable source found",
                )
            ],
        ),
    )
    download_mock = AsyncMock(return_value=manifest)
    prompt_io = SimpleNamespace(
        confirm=Mock(side_effect=AssertionError("unexpected prompt")),
        prompt=Mock(side_effect=AssertionError("unexpected prompt")),
    )

    monkeypatch.setattr(workflow_module, "parse_natural_language_query", parse_mock)
    monkeypatch.setattr(workflow_module, "prepare_query", prepare_mock)
    monkeypatch.setattr(workflow_module, "run", run_mock)
    monkeypatch.setattr(workflow_module, "run_download_for_result", download_mock)

    workflow_result = await workflow_module.run_fetch_workflow(
        query="connectome computer vision",
        interactive=False,
        download=True,
        output=tmp_path / "ranked.json",
        output_dir=tmp_path / "papers",
        download_top=3,
        prompt_io=prompt_io,
    )

    assert workflow_result.download_manifest == manifest
    assert workflow_result.download_summary == manifest.download_summary
    assert workflow_result.download_summary is not None
    assert workflow_result.download_summary.shortfall_count == 1
    assert workflow_result.download_summary.backup_candidates == [
        ManifestEntry(
            paper_id=result.papers[0].paper_id,
            title=result.papers[0].title,
            rank=1,
            score=0.0,
            status="failed",
            error="no downloadable source found",
        )
    ]


async def test_non_interactive_fails_fast_when_download_missing_required_args(
    monkeypatch, workflow_module
):
    parse_mock = AsyncMock(side_effect=AssertionError("search should not run"))
    monkeypatch.setattr(workflow_module, "parse_natural_language_query", parse_mock)

    with pytest.raises(
        (ValueError, typer.BadParameter),
        match=r"(?i)output[_\s-]*dir.*required",
    ):
        await workflow_module.run_fetch_workflow(
            query="attention",
            interactive=False,
            download=True,
            download_top=5,
        )


async def test_workflow_prompts_before_downloading_lookup_results(
    tmp_path, monkeypatch, workflow_module
):
    result = _make_result(
        "Attention Is All You Need",
        total_papers=3,
        query_intent="paper_lookup",
    )
    parse_mock = AsyncMock(
        return_value=(SearchQuery(query="Attention Is All You Need", query_intent="paper_lookup"), "cs_ml")
    )
    prepare_mock = AsyncMock(return_value=SimpleNamespace())
    run_mock = AsyncMock(return_value=result)
    download_mock = AsyncMock()
    confirm_mock = Mock(return_value=False)
    prompt_io = SimpleNamespace(confirm=confirm_mock, prompt=Mock())

    monkeypatch.setattr(workflow_module, "parse_natural_language_query", parse_mock)
    monkeypatch.setattr(workflow_module, "prepare_query", prepare_mock)
    monkeypatch.setattr(workflow_module, "run", run_mock)
    monkeypatch.setattr(workflow_module, "run_download_for_result", download_mock)

    workflow_result = await workflow_module.run_fetch_workflow(
        query="Attention Is All You Need",
        interactive=True,
        output=tmp_path / "lookup.json",
        prompt_io=prompt_io,
    )

    assert workflow_result.saved_result_path == tmp_path / "lookup.json"
    assert workflow_result.download_requested is False
    assert workflow_result.download_executed is False
    confirm_mock.assert_called_once()
    download_mock.assert_not_awaited()


async def test_interactive_accepts_download_and_forwards_prompted_values(
    tmp_path, monkeypatch, workflow_module
):
    result = _make_result("graph transformers", total_papers=9, query_intent="domain_search")
    parse_mock = AsyncMock(return_value=(SearchQuery(query="graph transformers"), "cs_ml"))
    prepare_mock = AsyncMock(return_value=SimpleNamespace())
    run_mock = AsyncMock(return_value=result)
    download_mock = AsyncMock(return_value=SimpleNamespace(entries=[]))
    call_order: list[str] = []

    def _confirm(*_args, **_kwargs):
        call_order.append("confirm")
        return True

    def _prompt(*_args, **_kwargs):
        call_order.append("prompt")
        if call_order.count("prompt") == 1:
            return str(tmp_path / "papers")
        return "6"

    confirm_mock = Mock(side_effect=_confirm)
    prompt_mock = Mock(side_effect=_prompt)
    prompt_io = SimpleNamespace(confirm=confirm_mock, prompt=prompt_mock)

    monkeypatch.setattr(workflow_module, "parse_natural_language_query", parse_mock)
    monkeypatch.setattr(workflow_module, "prepare_query", prepare_mock)
    monkeypatch.setattr(workflow_module, "run", run_mock)
    monkeypatch.setattr(workflow_module, "run_download_for_result", download_mock)

    workflow_result = await workflow_module.run_fetch_workflow(
        query="graph transformers",
        interactive=True,
        output=tmp_path / "ranked.json",
        prompt_io=prompt_io,
    )

    saved = _load_saved_result(tmp_path / "ranked.json")
    assert len(saved.papers) == 9
    assert workflow_result.saved_result_path == tmp_path / "ranked.json"
    assert workflow_result.download_requested is True
    assert workflow_result.download_executed is True
    assert workflow_result.download_top == 6
    assert workflow_result.output_dir == tmp_path / "papers"
    assert workflow_result.download_manifest is not None
    confirm_mock.assert_called_once()
    assert prompt_mock.call_count == 2
    assert call_order == ["confirm", "prompt", "prompt"]
    first_prompt_text = prompt_mock.call_args_list[0].args[0].lower()
    second_prompt_text = prompt_mock.call_args_list[1].args[0].lower()
    assert "directory" in first_prompt_text or "output" in first_prompt_text
    assert "how many" in second_prompt_text or "top" in second_prompt_text
    download_mock.assert_awaited_once()
    args = download_mock.await_args.args
    kwargs = download_mock.await_args.kwargs
    assert args[0] == result
    assert args[1] == tmp_path / "papers"
    assert kwargs["top_n"] == 6


async def test_interactive_download_flag_skips_confirmation_and_downloads(
    tmp_path, monkeypatch, workflow_module
):
    result = _make_result("graph transformers", total_papers=7, query_intent="domain_search")
    parse_mock = AsyncMock(return_value=(SearchQuery(query="graph transformers"), "cs_ml"))
    prepare_mock = AsyncMock(return_value=SimpleNamespace())
    run_mock = AsyncMock(return_value=result)
    download_mock = AsyncMock(return_value=SimpleNamespace(entries=[]))
    prompt_io = SimpleNamespace(
        confirm=Mock(side_effect=AssertionError("download flag should skip confirmation")),
        prompt=Mock(side_effect=[str(tmp_path / "papers"), "4"]),
    )

    monkeypatch.setattr(workflow_module, "parse_natural_language_query", parse_mock)
    monkeypatch.setattr(workflow_module, "prepare_query", prepare_mock)
    monkeypatch.setattr(workflow_module, "run", run_mock)
    monkeypatch.setattr(workflow_module, "run_download_for_result", download_mock)

    workflow_result = await workflow_module.run_fetch_workflow(
        query="graph transformers",
        interactive=True,
        download=True,
        output=tmp_path / "ranked.json",
        prompt_io=prompt_io,
    )

    assert workflow_result.download_requested is True
    assert workflow_result.download_executed is True
    assert workflow_result.download_top == 4
    assert workflow_result.output_dir == tmp_path / "papers"
    assert prompt_io.prompt.call_count == 2
    download_mock.assert_awaited_once()
    assert download_mock.await_args.args[1] == tmp_path / "papers"
    assert download_mock.await_args.kwargs["top_n"] == 4


async def test_paper_lookup_accepts_download_and_defaults_to_all_found_results(
    tmp_path, monkeypatch, workflow_module
):
    result = _make_result("Attention Is All You Need", total_papers=3, query_intent="paper_lookup")
    parse_mock = AsyncMock(
        return_value=(SearchQuery(query="Attention Is All You Need", query_intent="paper_lookup"), "cs_ml")
    )
    prepare_mock = AsyncMock(return_value=SimpleNamespace())
    run_mock = AsyncMock(return_value=result)
    download_mock = AsyncMock(return_value=SimpleNamespace(entries=[]))
    confirm_mock = Mock(return_value=True)
    prompt_mock = Mock(side_effect=[str(tmp_path / "papers"), ""])
    prompt_io = SimpleNamespace(confirm=confirm_mock, prompt=prompt_mock)

    monkeypatch.setattr(workflow_module, "parse_natural_language_query", parse_mock)
    monkeypatch.setattr(workflow_module, "prepare_query", prepare_mock)
    monkeypatch.setattr(workflow_module, "run", run_mock)
    monkeypatch.setattr(workflow_module, "run_download_for_result", download_mock)

    workflow_result = await workflow_module.run_fetch_workflow(
        query="Attention Is All You Need",
        interactive=True,
        output=tmp_path / "lookup.json",
        prompt_io=prompt_io,
    )

    assert workflow_result.saved_result_path == tmp_path / "lookup.json"
    assert workflow_result.download_requested is True
    assert workflow_result.download_executed is True
    assert workflow_result.output_dir == tmp_path / "papers"
    assert workflow_result.download_top is None
    assert workflow_result.download_manifest is not None
    download_mock.assert_awaited_once()
    args = download_mock.await_args.args
    kwargs = download_mock.await_args.kwargs
    assert args[0] == result
    assert args[1] == tmp_path / "papers"
    assert kwargs["top_n"] is None


async def test_paper_lookup_not_found_skips_api_download_even_when_requested(
    tmp_path, monkeypatch, workflow_module
):
    result = _make_result(
        "Attention Is All You Need",
        total_papers=3,
        query_intent="paper_lookup",
        not_found=True,
    )
    parse_mock = AsyncMock(
        return_value=(SearchQuery(query="Attention Is All You Need", query_intent="paper_lookup"), "cs_ml")
    )
    prepare_mock = AsyncMock(return_value=SimpleNamespace())
    run_mock = AsyncMock(return_value=result)
    download_mock = AsyncMock(side_effect=AssertionError("closest matches should not be downloaded"))
    prompt_io = SimpleNamespace(
        confirm=Mock(side_effect=AssertionError("non-interactive API should not prompt")),
        prompt=Mock(side_effect=AssertionError("non-interactive API should not prompt")),
    )

    monkeypatch.setattr(workflow_module, "parse_natural_language_query", parse_mock)
    monkeypatch.setattr(workflow_module, "prepare_query", prepare_mock)
    monkeypatch.setattr(workflow_module, "run", run_mock)
    monkeypatch.setattr(workflow_module, "run_download_for_result", download_mock)

    workflow_result = await workflow_module.run_fetch_workflow(
        query="Attention Is All You Need",
        interactive=False,
        download=True,
        output=tmp_path / "lookup.json",
        output_dir=tmp_path / "papers",
        prompt_io=prompt_io,
    )

    assert workflow_result.saved_result_path == tmp_path / "lookup.json"
    assert workflow_result.download_requested is True
    assert workflow_result.download_executed is False
    assert workflow_result.download_manifest is None
    download_mock.assert_not_awaited()


async def test_query_requested_download_skips_confirmation_and_uses_parsed_top_n(
    tmp_path, monkeypatch, workflow_module
):
    result = _make_result("graph transformers", total_papers=12, query_intent="domain_search")
    parse_mock = AsyncMock(
        return_value=(
            SearchQuery(
                query="graph transformers",
                query_intent="domain_search",
                download_requested=True,
                download_top_n=10,
            ),
            "cs_ml",
        )
    )
    prepare_mock = AsyncMock(return_value=SimpleNamespace())
    run_mock = AsyncMock(return_value=result)
    download_mock = AsyncMock(return_value=SimpleNamespace(entries=[]))
    prompt_io = SimpleNamespace(
        confirm=Mock(side_effect=AssertionError("query-driven download should not ask for confirmation")),
        prompt=Mock(return_value=str(tmp_path / "papers")),
    )

    monkeypatch.setattr(workflow_module, "parse_natural_language_query", parse_mock)
    monkeypatch.setattr(workflow_module, "prepare_query", prepare_mock)
    monkeypatch.setattr(workflow_module, "run", run_mock)
    monkeypatch.setattr(workflow_module, "run_download_for_result", download_mock)

    workflow_result = await workflow_module.run_fetch_workflow(
        query="download 10 papers about graph transformers",
        interactive=True,
        output=tmp_path / "ranked.json",
        prompt_io=prompt_io,
    )

    assert workflow_result.download_requested is True
    assert workflow_result.download_executed is True
    assert workflow_result.download_top == 10
    assert workflow_result.output_dir == tmp_path / "papers"
    assert prompt_io.prompt.call_count == 1
    download_mock.assert_awaited_once()
    assert download_mock.await_args.kwargs["top_n"] == 10


async def test_results_json_query_routes_to_download_without_search(
    tmp_path, monkeypatch, workflow_module
):
    run_result = _make_result("graph transformers", total_papers=4, query_intent="domain_search")
    results_path = tmp_path / "saved-results.json"
    results_path.write_text(run_result.model_dump_json(indent=2))

    parse_mock = AsyncMock(side_effect=AssertionError("results json route should skip NLP parsing"))
    prepare_mock = AsyncMock(side_effect=AssertionError("results json route should skip query preparation"))
    run_mock = AsyncMock(side_effect=AssertionError("results json route should skip search execution"))
    download_mock = AsyncMock(return_value=SimpleNamespace(entries=[]))
    prompt_io = SimpleNamespace(
        confirm=Mock(side_effect=AssertionError("non-interactive results-file download should not prompt")),
        prompt=Mock(side_effect=AssertionError("non-interactive results-file download should not prompt")),
    )

    monkeypatch.setattr(workflow_module, "parse_natural_language_query", parse_mock)
    monkeypatch.setattr(workflow_module, "prepare_query", prepare_mock)
    monkeypatch.setattr(workflow_module, "run", run_mock)
    monkeypatch.setattr(workflow_module, "run_download_for_result", download_mock)

    workflow_result = await workflow_module.run_fetch_workflow(
        query=str(results_path),
        interactive=False,
        output_dir=tmp_path / "papers",
        prompt_io=prompt_io,
    )

    assert workflow_result.saved_result_path == results_path
    assert workflow_result.download_requested is True
    assert workflow_result.download_executed is True
    assert workflow_result.output_dir == tmp_path / "papers"
    assert len(workflow_result.preview_papers) == 4
    assert workflow_result.download_top is None
    download_mock.assert_awaited_once()
    assert download_mock.await_args.args[1] == tmp_path / "papers"
    assert download_mock.await_args.kwargs["top_n"] is None


async def test_empty_search_result_fails_before_prompting_or_downloading(
    tmp_path, monkeypatch, workflow_module
):
    empty_result = _make_result("empty query", total_papers=0)
    parse_mock = AsyncMock(return_value=(SearchQuery(query="empty query"), "cs_ml"))
    prepare_mock = AsyncMock(return_value=SimpleNamespace())
    run_mock = AsyncMock(return_value=empty_result)
    confirm_mock = Mock(side_effect=AssertionError("should not prompt on empty results"))
    prompt_mock = Mock(side_effect=AssertionError("should not prompt on empty results"))
    prompt_io = SimpleNamespace(confirm=confirm_mock, prompt=prompt_mock)
    download_mock = AsyncMock(side_effect=AssertionError("should not download on empty results"))

    monkeypatch.setattr(workflow_module, "parse_natural_language_query", parse_mock)
    monkeypatch.setattr(workflow_module, "prepare_query", prepare_mock)
    monkeypatch.setattr(workflow_module, "run", run_mock)
    monkeypatch.setattr(workflow_module, "run_download_for_result", download_mock)

    with pytest.raises((typer.Exit, ValueError), match=r"(?i)no papers|no results"):
        await workflow_module.run_fetch_workflow(
            query="empty query",
            interactive=True,
            output=tmp_path / "empty.json",
            prompt_io=prompt_io,
        )

    download_mock.assert_not_awaited()


async def test_domain_search_preview_top_10_while_saved_results_keep_full_set(
    tmp_path, monkeypatch, workflow_module
):
    result = _make_result("single-cell transformers", total_papers=15, query_intent="domain_search")
    parse_mock = AsyncMock(
        return_value=(SearchQuery(query="single-cell transformers", query_intent="domain_search"), "bioinformatics")
    )
    prepare_mock = AsyncMock(return_value=SimpleNamespace())
    run_mock = AsyncMock(return_value=result)
    confirm_mock = Mock(return_value=False)
    prompt_io = SimpleNamespace(confirm=confirm_mock, prompt=Mock())

    monkeypatch.setattr(workflow_module, "parse_natural_language_query", parse_mock)
    monkeypatch.setattr(workflow_module, "prepare_query", prepare_mock)
    monkeypatch.setattr(workflow_module, "run", run_mock)
    monkeypatch.setattr(workflow_module, "run_download_for_result", AsyncMock())

    workflow_result = await workflow_module.run_fetch_workflow(
        query="single-cell transformers",
        interactive=True,
        output=tmp_path / "domain.json",
        prompt_io=prompt_io,
    )

    assert len(workflow_result.preview_papers) == 10
    assert [paper.paper_id for paper in workflow_result.preview_papers] == [
        paper.paper_id for paper in result.papers[:10]
    ]
    assert workflow_result.saved_result_path == tmp_path / "domain.json"
    assert workflow_result.download_requested is False
    assert workflow_result.download_executed is False
    parse_mock.assert_awaited_once_with("single-cell transformers")
    prepare_mock.assert_awaited_once()
    run_mock.assert_awaited_once()
    prepared_query = prepare_mock.await_args.args[0]
    assert isinstance(prepared_query, SearchQuery)
    assert prepared_query.query == "single-cell transformers"
    assert prepare_mock.await_args.kwargs["domain_category_override"] == "bioinformatics"
    assert run_mock.await_args.args[0] is prepared_query
    assert run_mock.await_args.kwargs["domain_category_override"] == "bioinformatics"
    saved = _load_saved_result(tmp_path / "domain.json")
    assert len(saved.papers) == 15
    assert [paper.paper_id for paper in saved.papers] == [paper.paper_id for paper in result.papers]


async def test_keyword_strategy_defaults_to_specific_without_scope_prompt(
    tmp_path, monkeypatch, workflow_module
):
    result = _make_result("vision transformers", total_papers=5, query_intent="domain_search")
    parse_mock = AsyncMock(return_value=(SearchQuery(query="vision transformers"), "cs_ml"))
    prepare_mock = AsyncMock(return_value=SimpleNamespace())
    run_mock = AsyncMock(return_value=result)

    monkeypatch.setattr(workflow_module, "parse_natural_language_query", parse_mock)
    monkeypatch.setattr(workflow_module, "prepare_query", prepare_mock)
    monkeypatch.setattr(workflow_module, "run", run_mock)
    monkeypatch.setattr(workflow_module, "run_download_for_result", AsyncMock())
    prompt_io = SimpleNamespace(
        confirm=Mock(return_value=False),
        prompt=Mock(side_effect=AssertionError("unexpected prompt")),
    )

    await workflow_module.run_fetch_workflow(
        query="vision transformers",
        interactive=True,
        output=tmp_path / "ranked.json",
        prompt_io=prompt_io,
    )

    prepared_query = prepare_mock.await_args.args[0]
    assert prepared_query.search_scope == "specific"
    assert prepared_query.keyword_count == 3


async def test_keyword_strategy_honors_cli_overrides(
    tmp_path, monkeypatch, workflow_module
):
    result = _make_result("vision transformers", total_papers=5, query_intent="domain_search")
    parse_mock = AsyncMock(return_value=(SearchQuery(query="vision transformers", keyword_count=8), "cs_ml"))
    prepare_mock = AsyncMock(return_value=SimpleNamespace())
    run_mock = AsyncMock(return_value=result)

    monkeypatch.setattr(workflow_module, "parse_natural_language_query", parse_mock)
    monkeypatch.setattr(workflow_module, "prepare_query", prepare_mock)
    monkeypatch.setattr(workflow_module, "run", run_mock)
    monkeypatch.setattr(workflow_module, "run_download_for_result", AsyncMock())
    prompt_io = SimpleNamespace(confirm=Mock(return_value=False), prompt=Mock())

    await workflow_module.run_fetch_workflow(
        query="vision transformers",
        interactive=True,
        output=tmp_path / "ranked.json",
        keyword_count=2,
        no_keyword_expansion=True,
        prompt_io=prompt_io,
    )

    prepared_query = prepare_mock.await_args.args[0]
    assert prepared_query.search_scope == "specific"
    assert prepared_query.keyword_count == 0


async def test_non_interactive_download_defaults_to_all_results_without_prompting(
    tmp_path, monkeypatch, workflow_module
):
    result = _make_result("non interactive all", total_papers=5)
    parse_mock = AsyncMock(return_value=(SearchQuery(query="non interactive all"), "cs_ml"))
    prepare_mock = AsyncMock(return_value=SimpleNamespace())
    run_mock = AsyncMock(return_value=result)
    download_mock = AsyncMock(return_value=SimpleNamespace(entries=[]))
    prompt_io = SimpleNamespace(
        confirm=Mock(side_effect=AssertionError("unexpected confirm")),
        prompt=Mock(side_effect=AssertionError("unexpected prompt")),
    )

    monkeypatch.setattr(workflow_module, "parse_natural_language_query", parse_mock)
    monkeypatch.setattr(workflow_module, "prepare_query", prepare_mock)
    monkeypatch.setattr(workflow_module, "run", run_mock)
    monkeypatch.setattr(workflow_module, "run_download_for_result", download_mock)

    workflow_result = await workflow_module.run_fetch_workflow(
        query="non interactive all",
        interactive=False,
        download=True,
        output=tmp_path / "ranked.json",
        output_dir=tmp_path / "papers",
        prompt_io=prompt_io,
    )

    assert workflow_result.download_requested is True
    assert workflow_result.download_executed is True
    assert workflow_result.download_top is None
    assert download_mock.await_args.kwargs["top_n"] is None


async def test_yes_does_not_bypass_interactive_download_confirmation(
    tmp_path, monkeypatch, workflow_module
):
    result = _make_result("yes should not bypass", total_papers=4)
    parse_mock = AsyncMock(return_value=(SearchQuery(query="yes should not bypass"), "cs_ml"))
    prepare_mock = AsyncMock(return_value=SimpleNamespace())
    run_mock = AsyncMock(return_value=result)
    download_mock = AsyncMock()
    confirm_mock = Mock(return_value=False)
    prompt_io = SimpleNamespace(confirm=confirm_mock, prompt=Mock())

    monkeypatch.setattr(workflow_module, "parse_natural_language_query", parse_mock)
    monkeypatch.setattr(workflow_module, "prepare_query", prepare_mock)
    monkeypatch.setattr(workflow_module, "run", run_mock)
    monkeypatch.setattr(workflow_module, "run_download_for_result", download_mock)

    workflow_result = await workflow_module.run_fetch_workflow(
        query="yes should not bypass",
        interactive=True,
        yes=True,
        output=tmp_path / "ranked.json",
        prompt_io=prompt_io,
    )

    assert workflow_result.download_requested is False
    assert workflow_result.download_executed is False
    confirm_mock.assert_called_once()
    download_mock.assert_not_awaited()


async def test_non_interactive_rejects_non_positive_download_top_before_pipeline(
    monkeypatch, workflow_module
):
    parse_mock = AsyncMock(side_effect=AssertionError("search should not run"))
    monkeypatch.setattr(workflow_module, "parse_natural_language_query", parse_mock)

    with pytest.raises((ValueError, typer.BadParameter), match=r"(?i)download.*top.*positive"):
        await workflow_module.run_fetch_workflow(
            query="invalid top",
            interactive=False,
            download=True,
            output_dir=Path("papers"),
            download_top=0,
        )


async def test_interactive_rejects_non_positive_prompted_download_top(
    tmp_path, monkeypatch, workflow_module
):
    result = _make_result("prompted invalid top", total_papers=5)
    parse_mock = AsyncMock(return_value=(SearchQuery(query="prompted invalid top"), "cs_ml"))
    prepare_mock = AsyncMock(return_value=SimpleNamespace())
    run_mock = AsyncMock(return_value=result)
    download_mock = AsyncMock(side_effect=AssertionError("download should not run"))
    prompt_io = SimpleNamespace(
        confirm=Mock(return_value=True),
        prompt=Mock(side_effect=[str(tmp_path / "papers"), "0"]),
    )

    monkeypatch.setattr(workflow_module, "parse_natural_language_query", parse_mock)
    monkeypatch.setattr(workflow_module, "prepare_query", prepare_mock)
    monkeypatch.setattr(workflow_module, "run", run_mock)
    monkeypatch.setattr(workflow_module, "run_download_for_result", download_mock)

    with pytest.raises((ValueError, typer.BadParameter), match=r"(?i)download.*top.*positive"):
        await workflow_module.run_fetch_workflow(
            query="prompted invalid top",
            interactive=True,
            output=tmp_path / "ranked.json",
            prompt_io=prompt_io,
        )

    download_mock.assert_not_awaited()


async def test_interactive_rejects_non_numeric_prompted_download_top(
    tmp_path, monkeypatch, workflow_module
):
    result = _make_result("prompted non numeric top", total_papers=5)
    parse_mock = AsyncMock(return_value=(SearchQuery(query="prompted non numeric top"), "cs_ml"))
    prepare_mock = AsyncMock(return_value=SimpleNamespace())
    run_mock = AsyncMock(return_value=result)
    download_mock = AsyncMock(side_effect=AssertionError("download should not run"))
    prompt_io = SimpleNamespace(
        confirm=Mock(return_value=True),
        prompt=Mock(side_effect=[str(tmp_path / "papers"), "abc"]),
    )

    monkeypatch.setattr(workflow_module, "parse_natural_language_query", parse_mock)
    monkeypatch.setattr(workflow_module, "prepare_query", prepare_mock)
    monkeypatch.setattr(workflow_module, "run", run_mock)
    monkeypatch.setattr(workflow_module, "run_download_for_result", download_mock)

    with pytest.raises((ValueError, typer.BadParameter), match=r"(?i)download.*top.*integer"):
        await workflow_module.run_fetch_workflow(
            query="prompted non numeric top",
            interactive=True,
            output=tmp_path / "ranked.json",
            prompt_io=prompt_io,
        )

    download_mock.assert_not_awaited()


async def test_non_interactive_expands_explicit_output_dir(
    tmp_path, monkeypatch, workflow_module
):
    result = _make_result("explicit output dir", total_papers=2)
    parse_mock = AsyncMock(return_value=(SearchQuery(query="explicit output dir"), "cs_ml"))
    prepare_mock = AsyncMock(return_value=SimpleNamespace())
    run_mock = AsyncMock(return_value=result)
    download_mock = AsyncMock(return_value=SimpleNamespace(entries=[]))
    prompt_io = SimpleNamespace(
        confirm=Mock(side_effect=AssertionError("unexpected confirm")),
        prompt=Mock(side_effect=AssertionError("unexpected prompt")),
    )

    monkeypatch.setattr(workflow_module, "parse_natural_language_query", parse_mock)
    monkeypatch.setattr(workflow_module, "prepare_query", prepare_mock)
    monkeypatch.setattr(workflow_module, "run", run_mock)
    monkeypatch.setattr(workflow_module, "run_download_for_result", download_mock)

    workflow_result = await workflow_module.run_fetch_workflow(
        query="explicit output dir",
        interactive=False,
        download=True,
        output=tmp_path / "ranked.json",
        output_dir=Path("~/papers"),
        download_top=1,
        prompt_io=prompt_io,
    )

    expected_output_dir = Path("~/papers").expanduser()
    assert workflow_result.output_dir == expected_output_dir
    assert download_mock.await_args.args[1] == expected_output_dir


async def test_expands_explicit_output_path_before_writing(
    monkeypatch, workflow_module
):
    result = _make_result("explicit output path", total_papers=1)
    parse_mock = AsyncMock(return_value=(SearchQuery(query="explicit output path"), "cs_ml"))
    prepare_mock = AsyncMock(return_value=SimpleNamespace())
    run_mock = AsyncMock(return_value=result)
    captured: dict[str, Path] = {}

    def _capture_write(_result, out_path: Path):
        captured["out_path"] = out_path

    prompt_io = SimpleNamespace(confirm=Mock(return_value=False), prompt=Mock())

    monkeypatch.setattr(workflow_module, "parse_natural_language_query", parse_mock)
    monkeypatch.setattr(workflow_module, "prepare_query", prepare_mock)
    monkeypatch.setattr(workflow_module, "run", run_mock)
    monkeypatch.setattr(workflow_module, "run_download_for_result", AsyncMock())
    monkeypatch.setattr(workflow_module, "_write_result", _capture_write)

    workflow_result = await workflow_module.run_fetch_workflow(
        query="explicit output path",
        interactive=True,
        output=Path("~/result.json"),
        prompt_io=prompt_io,
    )

    expected_output = Path("~/result.json").expanduser()
    assert workflow_result.saved_result_path == expected_output
    assert captured["out_path"] == expected_output


# --- slug-based path tests ---

async def test_expand_existing_excludes_prior_papers(tmp_path, monkeypatch):
    """When expand_existing=True, previously found paper_ids are excluded from dedup."""
    import json
    from nexus_paper_fetcher.models import Paper, RunResult, SearchQuery
    from datetime import datetime, timezone

    monkeypatch.chdir(tmp_path)

    existing_paper = Paper.create(
        title="Old Paper", doi="10.1/old", year=2024, sources=["openalex"]
    )
    existing_result = RunResult(
        query="attention mechanisms", domain_category=["cs_ml"],
        params=SearchQuery(query="attention mechanisms"),
        sources_used=["openalex"], papers=[existing_paper],
        timestamp=datetime.now(timezone.utc),
    )
    slug_dir = tmp_path / "results" / "attention-mechanisms"
    slug_dir.mkdir(parents=True)
    result_file = slug_dir / "2026-04-01_top20.json"
    result_file.write_text(json.dumps(existing_result.model_dump(mode="json"), default=str))

    import nexus_paper_fetcher.workflow as wf

    new_paper = Paper.create(
        title="New Paper", doi="10.1/new", year=2025, sources=["openalex"]
    )
    mock_run = AsyncMock(return_value=RunResult(
        query="attention mechanisms", domain_category=["cs_ml"],
        params=SearchQuery(query="attention mechanisms"),
        sources_used=["openalex"], papers=[new_paper],
        timestamp=datetime.now(timezone.utc),
    ))
    monkeypatch.setattr(wf, "run", mock_run)

    parse_mock = AsyncMock(return_value=(SearchQuery(query="attention mechanisms"), "cs_ml"))
    prepare_mock = AsyncMock(return_value=None)
    download_mock = AsyncMock(return_value=None)
    monkeypatch.setattr(wf, "parse_natural_language_query", parse_mock)
    monkeypatch.setattr(wf, "prepare_query", prepare_mock)
    monkeypatch.setattr(wf, "run_download_for_result", download_mock)

    from nexus_paper_fetcher.workflow import run_fetch_workflow
    result = await run_fetch_workflow(
        query="attention mechanisms",
        top_n=20,
        expand_existing=True,
        interactive=False,
        output_dir=None,
    )
    # The run() call should have received a SearchQuery with expand_existing=True
    called_sq = mock_run.call_args[0][0]
    assert called_sq.expand_existing is True
    # Final result should contain BOTH old and new papers merged
    titles = {p.title for p in result.result.papers}
    assert "Old Paper" in titles
    assert "New Paper" in titles


def test_make_result_path_uses_slug(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from nexus_paper_fetcher.workflow import _make_result_path
    p = _make_result_path("single-cell RNA sequencing", 20)
    assert "single-cell-rna-sequencing" in str(p)
    assert p.suffix == ".json"
    assert p.parent.name == "single-cell-rna-sequencing"


def test_find_existing_results_none_when_dir_missing(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from nexus_paper_fetcher.workflow import _find_existing_results
    assert _find_existing_results("attention mechanisms") is None


def test_find_existing_results_returns_sorted_files(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from nexus_paper_fetcher.workflow import _find_existing_results
    slug_dir = tmp_path / "results" / "attention-mechanisms"
    slug_dir.mkdir(parents=True)
    old = slug_dir / "2026-04-01_top20.json"
    new = slug_dir / "2026-04-08_top20.json"
    old.write_text("{}")
    new.write_text("{}")
    found = _find_existing_results("attention mechanisms")
    assert found is not None
    files = found[1]
    assert files[0].name == "2026-04-08_top20.json"  # most recent first
