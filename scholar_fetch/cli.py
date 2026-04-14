from __future__ import annotations
import asyncio
import sys
from pathlib import Path
from typing import Optional

import typer

from scholar_fetch.download.cli import download_command
from scholar_fetch.search import search_results
from scholar_fetch.workflow import run_fetch_workflow

app = typer.Typer(help="Nexus Paper Fetcher — ranked academic paper search")
app.command("download")(download_command)


@app.callback()
def main() -> None:
    """Nexus Paper Fetcher — ranked academic paper search"""


class _TyperPromptAdapter:
    def confirm(self, text: str, *, default: bool = False) -> bool:
        return typer.confirm(text, default=default)

    def prompt(self, text: str, *, default: Optional[str] = None) -> str:
        return typer.prompt(text, default=default)


def _print_summary(
    result,
    *,
    papers: Optional[list] = None,
    ranked_count: Optional[int] = None,
    output_path: Optional[Path] = None,
) -> None:
    displayed_papers = papers if papers is not None else result.papers
    full_count = ranked_count if ranked_count is not None else len(result.papers)
    summary_path = output_path if output_path is not None else result.output_path

    print(f"[nexus] ranked top {full_count}  →  {summary_path}", file=sys.stderr)
    if len(displayed_papers) != full_count:
        print(
            f"[nexus] showing top {len(displayed_papers)} preview papers",
            file=sys.stderr,
        )
    if getattr(result, "not_found", False):
        print("[nexus] exact paper match not found — showing closest matches", file=sys.stderr)
    header = f"\n{'Rank':>4}  {'Score':>5}  {'Year':>4}  {'Venue':<22}  Title"
    print(header, file=sys.stderr)
    for i, paper in enumerate(displayed_papers, 1):
        venue = (paper.venue or "—")[:22]
        title = (paper.title or "")[:55]
        year = str(paper.year or "—")
        score = f"{paper.scores.composite:.3f}"
        print(f"{i:>4}  {score:>5}  {year:>4}  {venue:<22}  {title}", file=sys.stderr)


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
        return

    if search_query.keyword_count is not None:
        if search_query.keyword_count == 0:
            search_query.search_scope = "specific"
        elif search_query.keyword_count <= 3:
            search_query.search_scope = "specific"
        elif search_query.keyword_count >= 8:
            search_query.search_scope = "broad"
        return

    scope = typer.prompt("Search scope [specific/broad]", default="specific")
    search_query.search_scope = scope.strip().lower()
    search_query.keyword_count = _keyword_count_from_scope(search_query.search_scope)


@app.command()
def fetch(
    query: str = typer.Argument(..., help="Research query or natural language description"),
    top_n: Optional[int] = typer.Option(None, "--top-n", help="Number of papers to return (overrides NLP-parsed count)"),
    year_from: Optional[int] = typer.Option(None, "--year-from"),
    year_to: Optional[int] = typer.Option(None, "--year-to"),
    author: Optional[str] = typer.Option(None, "--author"),
    journal: Optional[str] = typer.Option(None, "--journal"),
    fetch_per_source: int = typer.Option(0, "--fetch-per-source"),
    domain_category: Optional[str] = typer.Option(None, "--domain-category"),
    keyword_count: Optional[int] = typer.Option(None, "--keyword-count", help="Number of expansion keywords"),
    no_keyword_expansion: bool = typer.Option(False, "--no-keyword-expansion", help="Disable keyword expansion"),
    download: bool = typer.Option(False, "--download", help="Download full-text files after ranking"),
    download_top: Optional[int] = typer.Option(
        None,
        "--download-top",
        help="Target number of successfully downloadable papers to collect",
    ),
    output_dir: Optional[Path] = typer.Option(None, "--output-dir", help="Directory for downloaded files"),
    yes: bool = typer.Option(
        False,
        "--yes",
        "--non-interactive",
        help="Non-interactive mode (skip prompts and use provided flags)",
    ),
    output: Optional[Path] = typer.Option(None, "--output"),
    expand: bool = typer.Option(False, "--expand", help="Expand existing search results with new papers"),
) -> None:
    async def _run() -> None:
        workflow_result = await run_fetch_workflow(
            query=query,
            top_n=top_n,
            year_from=year_from,
            year_to=year_to,
            author=author,
            journal=journal,
            fetch_per_source=fetch_per_source,
            domain_category=domain_category,
            keyword_count=keyword_count,
            no_keyword_expansion=no_keyword_expansion,
            output=output,
            interactive=not yes,
            download=download,
            output_dir=output_dir,
            download_top=download_top,
            yes=yes,
            prompt_io=_TyperPromptAdapter(),
            expand_existing=expand,
        )
        result = workflow_result.result
        _print_summary(
            result,
            papers=workflow_result.preview_papers,
            ranked_count=result.top_n_count or len(result.papers),
            output_path=workflow_result.saved_result_path,
        )

    try:
        asyncio.run(_run())
    except ValueError as exc:
        print(f"[nexus] error: {exc}", file=sys.stderr)
        raise typer.Exit(code=1) from exc


@app.command()
def shell(
    output_dir: Path = typer.Option(Path("."), "--output-dir", help="Directory to save results"),
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)

    while True:
        q = typer.prompt("\nQuery (or 'quit' to exit)")
        if q.strip().lower() in ("quit", "exit", "q"):
            break

        async def _run(query: str) -> None:
            workflow_result = await run_fetch_workflow(
                query=query,
                interactive=True,
                prompt_io=_TyperPromptAdapter(),
                results_output_dir=output_dir,
            )
            if not workflow_result.result.papers:
                print("[nexus] no papers returned", file=sys.stderr)
                return
            _r = workflow_result.result
            _print_summary(
                _r,
                papers=workflow_result.preview_papers,
                ranked_count=_r.top_n_count or len(_r.papers),
                output_path=workflow_result.saved_result_path,
            )

        asyncio.run(_run(q))


@app.command()
def search(
    query: str = typer.Argument("", help="Keywords to search (empty = list all)"),
    not_downloadable: bool = typer.Option(
        False, "--not-downloadable", help="Only show papers with failed or no download"
    ),
    downloaded: bool = typer.Option(
        False, "--downloaded", help="Only show successfully downloaded papers"
    ),
    domain: Optional[str] = typer.Option(
        None, "--domain", help="Restrict to a specific query-slug subdirectory"
    ),
) -> None:
    """Search across saved result JSONs (no API calls)."""
    hits = search_results(
        query,
        results_dir=Path("results"),
        not_downloadable=not_downloadable,
        downloaded_only=downloaded,
        domain_slug=domain,
    )
    if not hits:
        print("[nexus] no results found", file=sys.stderr)
        return
    header = f"\n{'Rank':>4}  {'Score':>5}  {'DL':>4}  {'Year':>4}  {'Venue':<18}  Title"
    print(header)
    for hit in hits[:50]:
        dl = {
            "success": " ok",
            "failed": "fail",
            "not_attempted": "skip",
            None: "   —",
        }.get(hit.paper.download_status, "   —")
        venue = (hit.paper.venue or "—")[:18]
        title = (hit.paper.title or "")[:55]
        year = str(hit.paper.year or "—")
        score = f"{hit.paper.scores.composite:.3f}"
        print(f"{hit.rank:>4}  {score:>5}  {dl:>4}  {year:>4}  {venue:<18}  {title}")
    print(f"\n[nexus] {len(hits)} results", file=sys.stderr)
