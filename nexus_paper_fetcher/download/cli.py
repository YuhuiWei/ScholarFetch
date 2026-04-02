from __future__ import annotations
import asyncio
import sys
from pathlib import Path
from typing import Optional
import typer
from nexus_paper_fetcher.download.pipeline import run_download

_DEFAULT_OUTPUT_DIR = Path(
    __import__("os").environ.get("NEXUS_PDF_DIR", "papers")
)


def download_command(
    results_file: Path = typer.Argument(..., help="Path to Phase 1 results JSON"),
    output_dir: Path = typer.Option(
        _DEFAULT_OUTPUT_DIR, "--output-dir", help="Directory to save PDFs"
    ),
    top: Optional[int] = typer.Option(None, "--top", help="Download only top N papers"),
    skip_ezproxy: bool = typer.Option(
        False, "--skip-ezproxy", help="Only use free sources (skip OHSU EZproxy)"
    ),
) -> None:
    if not results_file.exists():
        print(f"[nexus-dl] error: file not found: {results_file}", file=sys.stderr)
        raise typer.Exit(code=1)

    async def _run() -> None:
        await run_download(
            results_path=results_file,
            output_dir=output_dir,
            top_n=top,
            skip_ezproxy=skip_ezproxy,
        )

    asyncio.run(_run())
