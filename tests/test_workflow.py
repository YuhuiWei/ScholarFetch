from __future__ import annotations

import importlib
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
import typer

from nexus_paper_fetcher.models import Paper, RunResult, SearchQuery


def _make_result(
    query: str,
    *,
    total_papers: int,
    query_intent: str = "domain_search",
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

    monkeypatch.setattr(workflow_module, "parse_natural_language_query", parse_mock)
    monkeypatch.setattr(workflow_module, "prepare_query", prepare_mock)
    monkeypatch.setattr(workflow_module, "run", run_mock)
    monkeypatch.setattr(workflow_module, "run_download_for_result", download_mock)
    monkeypatch.setattr(workflow_module.typer, "confirm", confirm_mock)

    saved_results_path = tmp_path / "ranked.json"
    workflow_result = await workflow_module.run_fetch_workflow(
        query="graph transformers",
        interactive=True,
        output=saved_results_path,
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

    monkeypatch.setattr(workflow_module, "parse_natural_language_query", parse_mock)
    monkeypatch.setattr(workflow_module, "prepare_query", prepare_mock)
    monkeypatch.setattr(workflow_module, "run", run_mock)
    monkeypatch.setattr(workflow_module, "run_download_for_result", download_mock)
    monkeypatch.setattr(
        workflow_module.typer,
        "confirm",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("unexpected prompt")),
    )

    workflow_result = await workflow_module.run_fetch_workflow(
        query="foundation models",
        interactive=False,
        download=True,
        output=tmp_path / "ranked.json",
        output_dir=tmp_path / "papers",
        download_top=4,
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

    monkeypatch.setattr(workflow_module, "parse_natural_language_query", parse_mock)
    monkeypatch.setattr(workflow_module, "prepare_query", prepare_mock)
    monkeypatch.setattr(workflow_module, "run", run_mock)
    monkeypatch.setattr(workflow_module, "run_download_for_result", download_mock)
    monkeypatch.setattr(workflow_module.typer, "confirm", confirm_mock)

    workflow_result = await workflow_module.run_fetch_workflow(
        query="Attention Is All You Need",
        interactive=True,
        output=tmp_path / "lookup.json",
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

    monkeypatch.setattr(workflow_module, "parse_natural_language_query", parse_mock)
    monkeypatch.setattr(workflow_module, "prepare_query", prepare_mock)
    monkeypatch.setattr(workflow_module, "run", run_mock)
    monkeypatch.setattr(workflow_module, "run_download_for_result", download_mock)
    monkeypatch.setattr(workflow_module.typer, "confirm", confirm_mock)
    monkeypatch.setattr(workflow_module.typer, "prompt", prompt_mock)

    workflow_result = await workflow_module.run_fetch_workflow(
        query="graph transformers",
        interactive=True,
        output=tmp_path / "ranked.json",
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

    monkeypatch.setattr(workflow_module, "parse_natural_language_query", parse_mock)
    monkeypatch.setattr(workflow_module, "prepare_query", prepare_mock)
    monkeypatch.setattr(workflow_module, "run", run_mock)
    monkeypatch.setattr(workflow_module, "run_download_for_result", download_mock)
    monkeypatch.setattr(workflow_module.typer, "confirm", confirm_mock)
    monkeypatch.setattr(workflow_module.typer, "prompt", prompt_mock)

    workflow_result = await workflow_module.run_fetch_workflow(
        query="Attention Is All You Need",
        interactive=True,
        output=tmp_path / "lookup.json",
    )

    assert workflow_result.saved_result_path == tmp_path / "lookup.json"
    assert workflow_result.download_requested is True
    assert workflow_result.download_executed is True
    assert workflow_result.output_dir == tmp_path / "papers"
    assert workflow_result.download_top == 3
    assert workflow_result.download_manifest is not None
    download_mock.assert_awaited_once()
    args = download_mock.await_args.args
    kwargs = download_mock.await_args.kwargs
    assert args[0] == result
    assert args[1] == tmp_path / "papers"
    assert kwargs["top_n"] == 3


async def test_empty_search_result_fails_before_prompting_or_downloading(
    tmp_path, monkeypatch, workflow_module
):
    empty_result = _make_result("empty query", total_papers=0)
    parse_mock = AsyncMock(return_value=(SearchQuery(query="empty query"), "cs_ml"))
    prepare_mock = AsyncMock(return_value=SimpleNamespace())
    run_mock = AsyncMock(return_value=empty_result)
    confirm_mock = Mock(side_effect=AssertionError("should not prompt on empty results"))
    prompt_mock = Mock(side_effect=AssertionError("should not prompt on empty results"))
    download_mock = AsyncMock(side_effect=AssertionError("should not download on empty results"))

    monkeypatch.setattr(workflow_module, "parse_natural_language_query", parse_mock)
    monkeypatch.setattr(workflow_module, "prepare_query", prepare_mock)
    monkeypatch.setattr(workflow_module, "run", run_mock)
    monkeypatch.setattr(workflow_module.typer, "confirm", confirm_mock)
    monkeypatch.setattr(workflow_module.typer, "prompt", prompt_mock)
    monkeypatch.setattr(workflow_module, "run_download_for_result", download_mock)

    with pytest.raises((typer.Exit, ValueError), match=r"(?i)no papers|no results"):
        await workflow_module.run_fetch_workflow(
            query="empty query",
            interactive=True,
            output=tmp_path / "empty.json",
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

    monkeypatch.setattr(workflow_module, "parse_natural_language_query", parse_mock)
    monkeypatch.setattr(workflow_module, "prepare_query", prepare_mock)
    monkeypatch.setattr(workflow_module, "run", run_mock)
    monkeypatch.setattr(workflow_module, "run_download_for_result", AsyncMock())
    monkeypatch.setattr(workflow_module.typer, "confirm", confirm_mock)

    workflow_result = await workflow_module.run_fetch_workflow(
        query="single-cell transformers",
        interactive=True,
        output=tmp_path / "domain.json",
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
