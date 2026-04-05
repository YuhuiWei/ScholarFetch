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
    assert workflow_result.download_top == 5
    assert download_mock.await_args.kwargs["top_n"] == 5


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
