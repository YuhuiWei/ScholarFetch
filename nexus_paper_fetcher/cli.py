from __future__ import annotations
import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

import typer

from nexus_paper_fetcher.models import SearchQuery
from nexus_paper_fetcher.pipeline import run
from nexus_paper_fetcher.nlp import parse_natural_language_query, prepare_query
from nexus_paper_fetcher.download.cli import download_command

app = typer.Typer(help="Nexus Paper Fetcher — ranked academic paper search")
app.command("download")(download_command)


@app.callback()
def main() -> None:
    """Nexus Paper Fetcher — ranked academic paper search"""


def _auto_output_path(query: str, top_n: int) -> Path:
    date_str = datetime.utcnow().strftime("%Y-%m-%d")
    import re
    slug = re.sub(r"[^\w]", "-", query.lower())[:40].strip("-")
    Path("results").mkdir(exist_ok=True)
    return Path("results") / f"{date_str}_{slug}_top{top_n}.json"


def _write_result(result, out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    result.output_path = str(out_path)
    with open(out_path, "w") as f:
        json.dump(result.model_dump(mode="json"), f, indent=2, default=str)


def _print_summary(result) -> None:
    print(f"[nexus] ranked top {len(result.papers)}  →  {result.output_path}", file=sys.stderr)
    header = f"\n{'Rank':>4}  {'Score':>5}  {'Year':>4}  {'Venue':<22}  Title"
    print(header, file=sys.stderr)
    for i, paper in enumerate(result.papers, 1):
        venue = (paper.venue or "—")[:22]
        title = (paper.title or "")[:55]
        year = str(paper.year or "—")
        score = f"{paper.scores.composite:.3f}"
        print(f"{i:>4}  {score:>5}  {year:>4}  {venue:<22}  {title}", file=sys.stderr)


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
    output: Optional[Path] = typer.Option(None, "--output"),
) -> None:
    async def _run() -> None:
        sq, domain = await parse_natural_language_query(query)
        sq.top_n = top_n
        if year_from is not None:
            sq.year_from = year_from
        if year_to is not None:
            sq.year_to = year_to
        if author is not None:
            sq.author = author
        if journal is not None:
            sq.journal = journal
        sq.fetch_per_source = fetch_per_source

        if no_keyword_expansion:
            sq.keyword_count = 0
        elif keyword_count is not None:
            sq.keyword_count = keyword_count
        else:
            kc = typer.prompt("Keyword expansion count", default=5)
            sq.keyword_count = int(kc)

        await prepare_query(sq, domain_category_override=domain_category or domain)
        result = await run(sq, domain_category_override=domain_category or domain)

        if not result.papers:
            print("[nexus] error: all sources failed — no papers returned", file=sys.stderr)
            raise typer.Exit(code=1)

        out_path = output or _auto_output_path(query, top_n)
        _write_result(result, out_path)
        _print_summary(result)

    asyncio.run(_run())


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
            kc = typer.prompt("Keyword expansion count", default=5)
            sq.keyword_count = int(kc)
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
