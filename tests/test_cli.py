from types import SimpleNamespace
from unittest.mock import AsyncMock

from typer.testing import CliRunner

from nexus_paper_fetcher import cli


def _workflow_result(tmp_path):
    return SimpleNamespace(
        result=SimpleNamespace(papers=[]),
        preview_papers=[],
        saved_result_path=tmp_path / "result.json",
        download_requested=False,
        download_executed=False,
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
    monkeypatch.setattr(
        cli,
        "run",
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
    monkeypatch.setattr(
        cli,
        "run",
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
