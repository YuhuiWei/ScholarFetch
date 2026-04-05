from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Protocol

import typer

from nexus_paper_fetcher.download.pipeline import run_download_for_result
from nexus_paper_fetcher.models import Paper, RunResult, SearchQuery
from nexus_paper_fetcher.nlp import parse_natural_language_query, prepare_query
from nexus_paper_fetcher.pipeline import run


class PromptIO(Protocol):
    def confirm(self, text: str, *, default: bool = False) -> bool: ...

    def prompt(self, text: str, *, default: Optional[str] = None) -> str: ...


class TyperPromptIO:
    def confirm(self, text: str, *, default: bool = False) -> bool:
        return typer.confirm(text, default=default)

    def prompt(self, text: str, *, default: Optional[str] = None) -> str:
        return typer.prompt(text, default=default)


@dataclass(slots=True)
class FetchWorkflowResult:
    result: RunResult
    preview_papers: list[Paper]
    saved_result_path: Path
    download_requested: bool
    download_executed: bool
    download_manifest: object | None
    download_top: int | None = None
    output_dir: Path | None = None


def _auto_output_path(query: str, top_n: int) -> Path:
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    slug = re.sub(r"[^\w]", "-", query.lower())[:40].strip("-")
    Path("results").mkdir(exist_ok=True)
    return Path("results") / f"{date_str}_{slug}_top{top_n}.json"


def _write_result(result: RunResult, out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    result.output_path = str(out_path)
    with open(out_path, "w", encoding="utf-8") as handle:
        json.dump(result.model_dump(mode="json"), handle, indent=2, default=str)


def _keyword_count_from_scope(scope: str) -> int:
    normalized = scope.strip().lower()
    if normalized in {"specific", "narrow", "less"}:
        return 3
    if normalized in {"broad", "broader", "more"}:
        return 8
    raise typer.BadParameter("Search scope must be 'specific' or 'broad'.")


def _apply_keyword_strategy(
    search_query: SearchQuery,
    *,
    cli_keyword_count: Optional[int],
    no_keyword_expansion: bool,
) -> None:
    if search_query.query_intent == "paper_lookup":
        search_query.search_scope = "specific"
        search_query.keyword_count = 0
        return

    if no_keyword_expansion:
        search_query.search_scope = "specific"
        search_query.keyword_count = 0
        return

    if cli_keyword_count is not None:
        search_query.keyword_count = cli_keyword_count
        if cli_keyword_count <= 3:
            search_query.search_scope = "specific"
        elif cli_keyword_count >= 8:
            search_query.search_scope = "broad"
        return

    if search_query.keyword_count is not None:
        if search_query.keyword_count == 0:
            search_query.search_scope = "specific"
        elif search_query.keyword_count <= 3:
            search_query.search_scope = "specific"
        elif search_query.keyword_count >= 8:
            search_query.search_scope = "broad"
        return

    # Workflow path is Python-first and non-chatty: default to a specific search
    # when neither NLP nor CLI gave explicit keyword expansion preferences.
    search_query.search_scope = "specific"
    search_query.keyword_count = _keyword_count_from_scope(search_query.search_scope)


def _validated_download_top(value: Optional[int]) -> Optional[int]:
    if value is None:
        return None
    if value <= 0:
        raise typer.BadParameter("download-top must be a positive integer")
    return value


async def run_fetch_workflow(
    *,
    query: str,
    top_n: int = 20,
    year_from: Optional[int] = None,
    year_to: Optional[int] = None,
    author: Optional[str] = None,
    journal: Optional[str] = None,
    fetch_per_source: int = 0,
    domain_category: Optional[str] = None,
    keyword_count: Optional[int] = None,
    no_keyword_expansion: bool = False,
    output: Optional[Path] = None,
    interactive: bool = True,
    download: bool = False,
    output_dir: Optional[Path] = None,
    download_top: Optional[int] = None,
    yes: bool = False,
    prompt_io: Optional[PromptIO] = None,
) -> FetchWorkflowResult:
    prompts = prompt_io or TyperPromptIO()
    chosen_download_top = _validated_download_top(download_top)
    normalized_output_dir = output_dir.expanduser() if output_dir is not None else None
    normalized_output = output.expanduser() if output is not None else None

    if not interactive and download and normalized_output_dir is None:
        raise typer.BadParameter("output-dir is required when download is enabled in non-interactive mode")

    search_query, parsed_domain = await parse_natural_language_query(query)

    search_query.top_n = top_n
    if year_from is not None:
        search_query.year_from = year_from
    if year_to is not None:
        search_query.year_to = year_to
    if author is not None:
        search_query.author = author
    if journal is not None:
        search_query.journal = journal
    search_query.fetch_per_source = fetch_per_source
    _apply_keyword_strategy(
        search_query,
        cli_keyword_count=keyword_count,
        no_keyword_expansion=no_keyword_expansion,
    )

    domain_override = domain_category or parsed_domain
    await prepare_query(search_query, domain_category_override=domain_override)
    result = await run(search_query, domain_category_override=domain_override)

    if not result.papers:
        raise ValueError("No papers found for query")

    out_path = normalized_output or _auto_output_path(query, search_query.top_n)
    _write_result(result, out_path)
    preview = result.papers[:10]

    download_requested = False
    download_executed = False
    chosen_output_dir = normalized_output_dir
    manifest = None

    if interactive:
        download_requested = bool(download)
        if not download_requested:
            download_requested = prompts.confirm("Download PDFs for these results?", default=False)
    else:
        download_requested = bool(download)

    if download_requested:
        if interactive and chosen_output_dir is None:
            chosen_output_dir = Path(prompts.prompt("Download output directory", default="papers")).expanduser()
        if chosen_output_dir is None:
            raise typer.BadParameter("output-dir is required when download is enabled in non-interactive mode")

        if chosen_download_top is None:
            if interactive:
                raw_top = prompts.prompt("How many top papers to download? (blank = all found)", default="")
                stripped = raw_top.strip()
                if stripped:
                    try:
                        parsed_top = int(stripped)
                    except ValueError as exc:
                        raise typer.BadParameter(
                            "download-top must be a positive integer"
                        ) from exc
                    chosen_download_top = _validated_download_top(parsed_top)
                else:
                    chosen_download_top = len(result.papers)
            else:
                chosen_download_top = len(result.papers)

        manifest = await run_download_for_result(
            result,
            chosen_output_dir,
            top_n=chosen_download_top,
        )
        download_executed = True

    return FetchWorkflowResult(
        result=result,
        preview_papers=preview,
        saved_result_path=out_path,
        download_requested=download_requested,
        download_executed=download_executed,
        download_manifest=manifest,
        download_top=chosen_download_top,
        output_dir=chosen_output_dir,
    )
