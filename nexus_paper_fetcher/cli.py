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

app = typer.Typer(help="Nexus Paper Fetcher — ranked academic paper search")


@app.callback()
def main() -> None:
    """Nexus Paper Fetcher — ranked academic paper search"""


def _auto_output_path(query: str, top_n: int) -> Path:
    date_str = datetime.utcnow().strftime("%Y-%m-%d")
    import re
    slug = re.sub(r"[^\w]", "-", query.lower())[:40].strip("-")
    Path("results").mkdir(exist_ok=True)
    return Path("results") / f"{date_str}_{slug}_top{top_n}.json"


@app.command()
def fetch(
    query: str = typer.Argument(..., help="Research domain description"),
    top_n: int = typer.Option(20, "--top-n", help="Number of papers to return"),
    year_from: Optional[int] = typer.Option(None, "--year-from"),
    year_to: Optional[int] = typer.Option(None, "--year-to"),
    author: Optional[str] = typer.Option(None, "--author"),
    journal: Optional[str] = typer.Option(None, "--journal"),
    fetch_per_source: int = typer.Option(0, "--fetch-per-source"),
    domain_category: Optional[str] = typer.Option(None, "--domain-category"),
    output: Optional[Path] = typer.Option(None, "--output"),
) -> None:
    search_query = SearchQuery(
        query=query,
        top_n=top_n,
        year_from=year_from,
        year_to=year_to,
        author=author,
        journal=journal,
        fetch_per_source=fetch_per_source,
    )

    result = asyncio.run(run(search_query, domain_category_override=domain_category))

    if not result.papers:
        print("[nexus] error: all sources failed — no papers returned", file=sys.stderr)
        raise typer.Exit(code=1)

    out_path = output or _auto_output_path(query, top_n)
    result.output_path = str(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(result.model_dump(mode="json"), f, indent=2, default=str)

    print(f"[nexus] ranked top {len(result.papers)}  →  {out_path}", file=sys.stderr)

    # Summary table to stderr
    header = f"\n{'Rank':>4}  {'Score':>5}  {'Year':>4}  {'Venue':<22}  Title"
    print(header, file=sys.stderr)
    for i, paper in enumerate(result.papers, 1):
        venue = (paper.venue or "—")[:22]
        title = (paper.title or "")[:55]
        year = str(paper.year or "—")
        score = f"{paper.scores.composite:.3f}"
        print(f"{i:>4}  {score:>5}  {year:>4}  {venue:<22}  {title}", file=sys.stderr)
