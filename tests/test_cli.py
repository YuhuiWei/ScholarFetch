from types import SimpleNamespace
from unittest.mock import AsyncMock

from typer.testing import CliRunner

from nexus_paper_fetcher import cli
from nexus_paper_fetcher.models import Paper, RunResult, SearchQuery


def _workflow_result(tmp_path):
    return SimpleNamespace(
        result=SimpleNamespace(papers=[]),
        preview_papers=[],
        saved_result_path=tmp_path / "result.json",
        download_requested=False,
        download_executed=False,
    )


def _make_result(query: str) -> RunResult:
    params = SearchQuery(query=query, top_n=3)
    return RunResult(
        query=query,
        domain_category="cs_ml",
        params=params,
        sources_used=["openalex"],
        papers=[Paper.create(title="Graph Transformers", year=2024, sources=["openalex"])],
    )


def test_fetch_delegates_to_run_fetch_workflow(tmp_path, monkeypatch):
    workflow_mock = AsyncMock(return_value=_workflow_result(tmp_path))
    monkeypatch.setattr(cli, "run_fetch_workflow", workflow_mock, raising=False)
    monkeypatch.setattr(
        cli,
        "parse_natural_language_query",
        AsyncMock(side_effect=AssertionError("fetch should delegate to workflow layer")),
    )
    monkeypatch.setattr(
        cli,
        "prepare_query",
        AsyncMock(side_effect=AssertionError("fetch should delegate to workflow layer")),
    )

    runner = CliRunner()
    result = runner.invoke(
        cli.app,
        ["fetch", "graph transformers", "--output", str(tmp_path / "result.json")],
    )

    assert result.exit_code == 0
    workflow_mock.assert_awaited_once()
    assert workflow_mock.await_args.kwargs["query"] == "graph transformers"


def test_fetch_forwards_non_interactive_download_flags(tmp_path, monkeypatch):
    workflow_mock = AsyncMock(return_value=_workflow_result(tmp_path))
    monkeypatch.setattr(cli, "run_fetch_workflow", workflow_mock, raising=False)
    monkeypatch.setattr(
        cli,
        "parse_natural_language_query",
        AsyncMock(side_effect=AssertionError("fetch should delegate to workflow layer")),
    )
    monkeypatch.setattr(
        cli,
        "prepare_query",
        AsyncMock(side_effect=AssertionError("fetch should delegate to workflow layer")),
    )

    output_dir = tmp_path / "papers"
    runner = CliRunner()
    result = runner.invoke(
        cli.app,
        [
            "fetch",
            "graph transformers",
            "--download",
            "--download-top",
            "7",
            "--output-dir",
            str(output_dir),
            "--yes",
            "--output",
            str(tmp_path / "result.json"),
        ],
    )

    assert result.exit_code == 0
    workflow_mock.assert_awaited_once()
    kwargs = workflow_mock.await_args.kwargs
    assert kwargs["download"] is True
    assert kwargs["download_top"] == 7
    assert kwargs["output_dir"] == output_dir
    assert kwargs["yes"] is True


def test_fetch_forwards_existing_fetch_controls_to_workflow(tmp_path, monkeypatch):
    workflow_mock = AsyncMock(return_value=_workflow_result(tmp_path))
    monkeypatch.setattr(cli, "run_fetch_workflow", workflow_mock, raising=False)
    monkeypatch.setattr(
        cli,
        "parse_natural_language_query",
        AsyncMock(side_effect=AssertionError("fetch should delegate to workflow layer")),
    )
    monkeypatch.setattr(
        cli,
        "prepare_query",
        AsyncMock(side_effect=AssertionError("fetch should delegate to workflow layer")),
    )

    out_path = tmp_path / "forwarded.json"
    runner = CliRunner()
    result = runner.invoke(
        cli.app,
        [
            "fetch",
            "graph transformers",
            "--top-n",
            "42",
            "--year-from",
            "2019",
            "--year-to",
            "2024",
            "--author",
            "Jane Doe",
            "--journal",
            "NeurIPS",
            "--domain-category",
            "cs_ml",
            "--fetch-per-source",
            "123",
            "--output",
            str(out_path),
        ],
    )

    assert result.exit_code == 0
    workflow_mock.assert_awaited_once()
    kwargs = workflow_mock.await_args.kwargs
    assert kwargs["top_n"] == 42
    assert kwargs["year_from"] == 2019
    assert kwargs["year_to"] == 2024
    assert kwargs["author"] == "Jane Doe"
    assert kwargs["journal"] == "NeurIPS"
    assert kwargs["domain_category"] == "cs_ml"
    assert kwargs["fetch_per_source"] == 123
    assert kwargs["output"] == out_path


def test_fetch_forwards_keyword_count_to_workflow(tmp_path, monkeypatch):
    workflow_mock = AsyncMock(return_value=_workflow_result(tmp_path))
    monkeypatch.setattr(cli, "run_fetch_workflow", workflow_mock, raising=False)
    monkeypatch.setattr(
        cli,
        "parse_natural_language_query",
        AsyncMock(side_effect=AssertionError("fetch should delegate to workflow layer")),
    )
    monkeypatch.setattr(
        cli,
        "prepare_query",
        AsyncMock(side_effect=AssertionError("fetch should delegate to workflow layer")),
    )

    runner = CliRunner()
    result = runner.invoke(
        cli.app,
        [
            "fetch",
            "graph transformers",
            "--keyword-count",
            "7",
            "--output",
            str(tmp_path / "result.json"),
        ],
    )

    assert result.exit_code == 0
    workflow_mock.assert_awaited_once()
    assert workflow_mock.await_args.kwargs["keyword_count"] == 7


def test_fetch_forwards_no_keyword_expansion_to_workflow(tmp_path, monkeypatch):
    workflow_mock = AsyncMock(return_value=_workflow_result(tmp_path))
    monkeypatch.setattr(cli, "run_fetch_workflow", workflow_mock, raising=False)
    monkeypatch.setattr(
        cli,
        "parse_natural_language_query",
        AsyncMock(side_effect=AssertionError("fetch should delegate to workflow layer")),
    )
    monkeypatch.setattr(
        cli,
        "prepare_query",
        AsyncMock(side_effect=AssertionError("fetch should delegate to workflow layer")),
    )

    runner = CliRunner()
    result = runner.invoke(
        cli.app,
        [
            "fetch",
            "graph transformers",
            "--no-keyword-expansion",
            "--output",
            str(tmp_path / "result.json"),
        ],
    )

    assert result.exit_code == 0
    workflow_mock.assert_awaited_once()
    assert workflow_mock.await_args.kwargs["no_keyword_expansion"] is True


def test_shell_command_processes_queries_until_quit(tmp_path, monkeypatch):
    monkeypatch.setattr(
        cli,
        "parse_natural_language_query",
        AsyncMock(return_value=(SearchQuery(query="attention", top_n=3), None)),
    )
    monkeypatch.setattr(
        cli,
        "prepare_query",
        AsyncMock(return_value=SimpleNamespace()),
    )
    run_mock = AsyncMock(return_value=_make_result("attention"))
    monkeypatch.setattr(cli, "run", run_mock)

    runner = CliRunner()
    result = runner.invoke(
        cli.app,
        ["shell", "--output-dir", str(tmp_path)],
        input="attention\nbroader\nquit\n",
    )

    assert result.exit_code == 0
    assert run_mock.await_count == 1
    assert len(list(tmp_path.glob("*.json"))) == 1
    submitted = run_mock.await_args.args[0]
    assert submitted.keyword_count == 8


def test_fetch_forwards_interactive_broad_scope_choice_to_workflow(tmp_path, monkeypatch):
    workflow_mock = AsyncMock(return_value=_workflow_result(tmp_path))
    monkeypatch.setattr(cli, "run_fetch_workflow", workflow_mock, raising=False)
    monkeypatch.setattr(
        cli,
        "parse_natural_language_query",
        AsyncMock(side_effect=AssertionError("fetch should delegate to workflow layer")),
    )
    monkeypatch.setattr(
        cli,
        "prepare_query",
        AsyncMock(side_effect=AssertionError("fetch should delegate to workflow layer")),
    )

    runner = CliRunner()
    result = runner.invoke(
        cli.app,
        ["fetch", "vision transformers", "--output", str(tmp_path / "result.json")],
        input="broad\n",
    )

    assert result.exit_code == 0
    workflow_mock.assert_awaited_once()
    kwargs = workflow_mock.await_args.kwargs
    assert kwargs["keyword_count"] == 8
