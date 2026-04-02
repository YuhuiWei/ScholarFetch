from unittest.mock import AsyncMock

from typer.testing import CliRunner

from nexus_paper_fetcher import cli
from nexus_paper_fetcher.models import Paper, RunResult, SearchQuery


def _make_result(query: str) -> RunResult:
    params = SearchQuery(query=query, top_n=3)
    return RunResult(
        query=query,
        domain_category="cs_ml",
        params=params,
        sources_used=["openalex"],
        papers=[Paper.create(title="Graph Transformers", year=2024, sources=["openalex"])],
    )


def test_fetch_command_writes_output(tmp_path, monkeypatch):
    monkeypatch.setattr(
        cli,
        "parse_natural_language_query",
        AsyncMock(return_value=(SearchQuery(query="graph transformers", top_n=3), None)),
    )
    monkeypatch.setattr(
        cli,
        "prepare_query",
        AsyncMock(return_value=("cs_ml", ["transformer", "attention"], "graph transformers transformer attention", "fallback", ["cs_ml"], "graph transformers", ["transformer"], ["attention"])),
    )
    run_mock = AsyncMock(return_value=_make_result("graph transformers"))
    monkeypatch.setattr(cli, "run", run_mock)

    out_path = tmp_path / "result.json"
    runner = CliRunner()
    result = runner.invoke(cli.app, ["fetch", "graph transformers", "--output", str(out_path)], input="4\n")

    assert result.exit_code == 0
    assert out_path.exists()
    run_mock.assert_awaited_once()


def test_fetch_command_can_override_keyword_count(tmp_path, monkeypatch):
    parsed = SearchQuery(query="graph transformers", top_n=3)
    monkeypatch.setattr(
        cli,
        "parse_natural_language_query",
        AsyncMock(return_value=(parsed, None)),
    )
    monkeypatch.setattr(
        cli,
        "prepare_query",
        AsyncMock(return_value=("cs_ml", ["transformer"], "graph transformers transformer", "fallback", ["cs_ml"], "graph transformers", ["transformer"], [])),
    )
    run_mock = AsyncMock(return_value=_make_result("graph transformers"))
    monkeypatch.setattr(cli, "run", run_mock)

    runner = CliRunner()
    result = runner.invoke(
        cli.app,
        ["fetch", "graph transformers", "--keyword-count", "7", "--output", str(tmp_path / "result.json")],
        input="4\n",
    )

    assert result.exit_code == 0
    submitted = run_mock.await_args.args[0]
    assert submitted.keyword_count == 7


def test_fetch_command_can_disable_keyword_expansion(tmp_path, monkeypatch):
    parsed = SearchQuery(query="graph transformers", top_n=3, keyword_count=5)
    monkeypatch.setattr(
        cli,
        "parse_natural_language_query",
        AsyncMock(return_value=(parsed, None)),
    )
    monkeypatch.setattr(
        cli,
        "prepare_query",
        AsyncMock(return_value=("cs_ml", [], "graph transformers", "disabled", ["cs_ml"], "graph transformers", [], [])),
    )
    run_mock = AsyncMock(return_value=_make_result("graph transformers"))
    monkeypatch.setattr(cli, "run", run_mock)

    runner = CliRunner()
    result = runner.invoke(
        cli.app,
        ["fetch", "graph transformers", "--no-keyword-expansion", "--output", str(tmp_path / "result.json")],
    )

    assert result.exit_code == 0
    submitted = run_mock.await_args.args[0]
    assert submitted.keyword_count == 0


def test_shell_command_processes_queries_until_quit(tmp_path, monkeypatch):
    monkeypatch.setattr(
        cli,
        "parse_natural_language_query",
        AsyncMock(return_value=(SearchQuery(query="attention", top_n=3), None)),
    )
    monkeypatch.setattr(
        cli,
        "prepare_query",
        AsyncMock(return_value=("cs_ml", ["attention"], "attention attention", "fallback", ["cs_ml"], "attention", ["attention"], [])),
    )
    run_mock = AsyncMock(return_value=_make_result("attention"))
    monkeypatch.setattr(cli, "run", run_mock)

    runner = CliRunner()
    result = runner.invoke(
        cli.app,
        ["shell", "--output-dir", str(tmp_path)],
        input="attention\n4\nquit\n",
    )

    assert result.exit_code == 0
    assert run_mock.await_count == 1
    assert len(list(tmp_path.glob("*.json"))) == 1
