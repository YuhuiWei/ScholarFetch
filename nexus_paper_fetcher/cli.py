from __future__ import annotations
import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import typer

from nexus_paper_fetcher.models import SearchQuery
from nexus_paper_fetcher.pipeline import run
from nexus_paper_fetcher.nlp import parse_natural_language_query, prepare_query
from nexus_paper_fetcher.download.cli import download_command
from nexus_paper_fetcher.workflow import run_fetch_workflow

app = typer.Typer(help="Nexus Paper Fetcher — ranked academic paper search")
app.command("download")(download_command)


@app.callback()
def main() -> None:
    """Nexus Paper Fetcher — ranked academic paper search"""


def _auto_output_path(query: str, top_n: int) -> Path:
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    import re
    slug = re.sub(r"[^\w]", "-", query.lower())[:40].strip("-")
    Path("results").mkdir(exist_ok=True)
    return Path("results") / f"{date_str}_{slug}_top{top_n}.json"


def _write_result(result, out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    result.output_path = str(out_path)
    with open(out_path, "w") as f:
        json.dump(result.model_dump(mode="json"), f, indent=2, default=str)


class _TyperPromptAdapter:
    def __init__(self, *, force_download_confirm: bool = False) -> None:
        self.force_download_confirm = force_download_confirm

    def confirm(self, text: str, *, default: bool = False) -> bool:
        if self.force_download_confirm:
            return True
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
    top_n: int = typer.Option(20, "--top-n", help="Number of papers to return"),
    year_from: Optional[int] = typer.Option(None, "--year-from"),
    year_to: Optional[int] = typer.Option(None, "--year-to"),
    author: Optional[str] = typer.Option(None, "--author"),
    journal: Optional[str] = typer.Option(None, "--journal"),
    fetch_per_source: int = typer.Option(0, "--fetch-per-source"),
    domain_category: Optional[str] = typer.Option(None, "--domain-category"),
    keyword_count: Optional[int] = typer.Option(None, "--keyword-count", help="Number of expansion keywords"),
    no_keyword_expansion: bool = typer.Option(False, "--no-keyword-expansion", help="Disable keyword expansion"),
    download: bool = typer.Option(False, "--download", help="Download full-text files after ranking"),
    download_top: Optional[int] = typer.Option(None, "--download-top", help="Top N papers to download"),
    output_dir: Optional[Path] = typer.Option(None, "--output-dir", help="Directory for downloaded files"),
    yes: bool = typer.Option(
        False,
        "--yes",
        "--non-interactive",
        help="Non-interactive mode (skip prompts and use provided flags)",
    ),
    output: Optional[Path] = typer.Option(None, "--output"),
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
            prompt_io=_TyperPromptAdapter(force_download_confirm=download),
        )
        _print_summary(
            workflow_result.result,
            papers=workflow_result.preview_papers,
            ranked_count=len(workflow_result.result.papers),
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
            sq, domain = await parse_natural_language_query(query)
            _apply_keyword_strategy(
                sq,
                cli_keyword_count=None,
                no_keyword_expansion=False,
            )
            await prepare_query(sq, domain_category_override=domain)
            result = await run(sq, domain_category_override=domain)
            if not result.papers:
                print("[nexus] no papers returned", file=sys.stderr)
                return
            out_path = _auto_output_path(query, sq.top_n)
            out_path = output_dir / out_path.name
            _write_result(result, out_path)
            _print_summary(result)

        asyncio.run(_run(q))
