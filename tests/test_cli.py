from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

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
        raising=False,
    )
    monkeypatch.setattr(
        cli,
        "prepare_query",
        AsyncMock(side_effect=AssertionError("fetch should delegate to workflow layer")),
        raising=False,
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
        raising=False,
    )
    monkeypatch.setattr(
        cli,
        "prepare_query",
        AsyncMock(side_effect=AssertionError("fetch should delegate to workflow layer")),
        raising=False,
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
    assert kwargs["interactive"] is False


def test_fetch_forwards_natural_language_download_phrase_to_workflow(tmp_path, monkeypatch):
    workflow_mock = AsyncMock(return_value=_workflow_result(tmp_path))
    monkeypatch.setattr(cli, "run_fetch_workflow", workflow_mock, raising=False)
    monkeypatch.setattr(
        cli,
        "parse_natural_language_query",
        AsyncMock(side_effect=AssertionError("fetch should delegate to workflow layer")),
        raising=False,
    )
    monkeypatch.setattr(
        cli,
        "prepare_query",
        AsyncMock(side_effect=AssertionError("fetch should delegate to workflow layer")),
        raising=False,
    )

    runner = CliRunner()
    result = runner.invoke(
        cli.app,
        ["fetch", "download 10 papers about graph transformers", "--output", str(tmp_path / "result.json")],
    )

    assert result.exit_code == 0
    workflow_mock.assert_awaited_once()
    assert workflow_mock.await_args.kwargs["query"] == "download 10 papers about graph transformers"


def test_fetch_forwards_existing_results_json_to_workflow(tmp_path, monkeypatch):
    workflow_mock = AsyncMock(return_value=_workflow_result(tmp_path))
    monkeypatch.setattr(cli, "run_fetch_workflow", workflow_mock, raising=False)
    monkeypatch.setattr(
        cli,
        "parse_natural_language_query",
        AsyncMock(side_effect=AssertionError("fetch should delegate to workflow layer")),
        raising=False,
    )
    monkeypatch.setattr(
        cli,
        "prepare_query",
        AsyncMock(side_effect=AssertionError("fetch should delegate to workflow layer")),
        raising=False,
    )

    results_path = tmp_path / "saved-results.json"
    results_path.write_text("{}")

    runner = CliRunner()
    result = runner.invoke(
        cli.app,
        ["fetch", str(results_path), "--yes", "--output-dir", str(tmp_path / "papers")],
    )

    assert result.exit_code == 0
    workflow_mock.assert_awaited_once()
    assert workflow_mock.await_args.kwargs["query"] == str(results_path)


def test_fetch_forwards_existing_fetch_controls_to_workflow(tmp_path, monkeypatch):
    workflow_mock = AsyncMock(return_value=_workflow_result(tmp_path))
    monkeypatch.setattr(cli, "run_fetch_workflow", workflow_mock, raising=False)
    monkeypatch.setattr(
        cli,
        "parse_natural_language_query",
        AsyncMock(side_effect=AssertionError("fetch should delegate to workflow layer")),
        raising=False,
    )
    monkeypatch.setattr(
        cli,
        "prepare_query",
        AsyncMock(side_effect=AssertionError("fetch should delegate to workflow layer")),
        raising=False,
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
        raising=False,
    )
    monkeypatch.setattr(
        cli,
        "prepare_query",
        AsyncMock(side_effect=AssertionError("fetch should delegate to workflow layer")),
        raising=False,
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
        raising=False,
    )
    monkeypatch.setattr(
        cli,
        "prepare_query",
        AsyncMock(side_effect=AssertionError("fetch should delegate to workflow layer")),
        raising=False,
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
    prompt_mock = Mock(side_effect=["attention", "quit"])
    monkeypatch.setattr(cli.typer, "prompt", prompt_mock)
    workflow_mock = AsyncMock(return_value=_workflow_result(tmp_path))
    monkeypatch.setattr(cli, "run_fetch_workflow", workflow_mock, raising=False)
    monkeypatch.setattr(
        cli,
        "parse_natural_language_query",
        AsyncMock(side_effect=AssertionError("shell should delegate parsing to workflow layer")),
        raising=False,
    )
    monkeypatch.setattr(
        cli,
        "prepare_query",
        AsyncMock(side_effect=AssertionError("shell should delegate preparation to workflow layer")),
        raising=False,
    )
    monkeypatch.setattr(
        cli,
        "run",
        AsyncMock(side_effect=AssertionError("shell should delegate execution to workflow layer")),
        raising=False,
    )

    runner = CliRunner()
    result = runner.invoke(
        cli.app,
        ["shell", "--output-dir", str(tmp_path)],
    )

    assert result.exit_code == 0
    assert prompt_mock.call_count == 2
    workflow_mock.assert_awaited_once()
    kwargs = workflow_mock.await_args.kwargs
    assert kwargs["query"] == "attention"
    assert kwargs["interactive"] is True
    assert kwargs["results_output_dir"] == tmp_path


def test_download_command_missing_results_file_reports_error_contract(tmp_path):
    runner = CliRunner()
    missing_path = tmp_path / "does-not-exist.json"
    result = runner.invoke(cli.app, ["download", str(missing_path)])

    assert result.exit_code == 1
    assert f"[nexus-dl] error: file not found: {missing_path}" in result.output


def test_fetch_leaves_scope_keyword_strategy_to_workflow(tmp_path, monkeypatch):
    workflow_mock = AsyncMock(return_value=_workflow_result(tmp_path))
    monkeypatch.setattr(cli, "run_fetch_workflow", workflow_mock, raising=False)
    monkeypatch.setattr(
        cli,
        "parse_natural_language_query",
        AsyncMock(side_effect=AssertionError("fetch should delegate to workflow layer")),
        raising=False,
    )
    monkeypatch.setattr(
        cli,
        "prepare_query",
        AsyncMock(side_effect=AssertionError("fetch should delegate to workflow layer")),
        raising=False,
    )

    runner = CliRunner()
    result = runner.invoke(
        cli.app,
        ["fetch", "vision transformers", "--output", str(tmp_path / "result.json")],
    )

    assert result.exit_code == 0
    workflow_mock.assert_awaited_once()
    kwargs = workflow_mock.await_args.kwargs
    assert kwargs["keyword_count"] is None
    assert kwargs["no_keyword_expansion"] is False


def test_fetch_summary_reports_full_ranked_count_with_preview_rows(tmp_path, monkeypatch):
    workflow_result = _workflow_result(tmp_path)
    full_result = RunResult(
        query="attention",
        domain_category="cs_ml",
        params=SearchQuery(query="attention", top_n=20),
        sources_used=["openalex"],
        papers=[
            Paper.create(title="Attention Is All You Need", year=2017, sources=["openalex"]),
            Paper.create(title="Sparse Attention", year=2019, sources=["openalex"]),
        ],
    )
    workflow_result.result = full_result
    workflow_result.preview_papers = [full_result.papers[0]]
    workflow_result.saved_result_path = tmp_path / "custom.json"

    workflow_mock = AsyncMock(return_value=workflow_result)
    monkeypatch.setattr(cli, "run_fetch_workflow", workflow_mock, raising=False)

    runner = CliRunner()
    result = runner.invoke(
        cli.app,
        ["fetch", "attention", "--output", str(tmp_path / "custom.json")],
    )

    assert result.exit_code == 0
    assert "[nexus] ranked top 2  →" in result.output
    assert str(tmp_path / "custom.json") in result.output
    assert "[nexus] showing top 1 preview papers" in result.output


def test_fetch_download_flag_does_not_install_cli_only_confirmation_override(
    tmp_path, monkeypatch
):
    observed = {}

    class FakePromptAdapter:
        def confirm(self, _text, *, default=False):
            return default

        def prompt(self, _text, *, default=None):
            return default or ""

    async def fake_run_fetch_workflow(**kwargs):
        observed["interactive"] = kwargs["interactive"]
        observed["download"] = kwargs["download"]
        observed["confirm_result"] = kwargs["prompt_io"].confirm(
            "Some workflow confirmation",
            default=False,
        )
        return _workflow_result(tmp_path)

    monkeypatch.setattr(cli, "_TyperPromptAdapter", FakePromptAdapter)
    monkeypatch.setattr(cli, "run_fetch_workflow", fake_run_fetch_workflow, raising=False)

    runner = CliRunner()
    result = runner.invoke(
        cli.app,
        ["fetch", "attention", "--download", "--output", str(tmp_path / "result.json")],
    )

    assert result.exit_code == 0
    assert observed["interactive"] is True
    assert observed["download"] is True
    assert observed["confirm_result"] is False


def test_fetch_non_interactive_download_requires_output_dir():
    runner = CliRunner()
    result = runner.invoke(
        cli.app,
        ["fetch", "attention", "--yes", "--download"],
    )

    assert result.exit_code == 2
    assert "output-dir is required when download is enabled in" in result.output
    assert "non-interactive mode" in result.output


def test_fetch_download_top_must_be_positive():
    runner = CliRunner()
    result = runner.invoke(
        cli.app,
        ["fetch", "attention", "--download-top", "0"],
    )

    assert result.exit_code == 2
    assert "download-top must be a positive integer" in result.output


def test_download_top_must_be_positive(tmp_path):
    results_file = tmp_path / "results.json"
    results_file.write_text("{}")

    runner = CliRunner()
    result = runner.invoke(
        cli.app,
        ["download", str(results_file), "--top", "0"],
    )

    assert result.exit_code == 2
    assert "top must be a positive integer" in result.output
