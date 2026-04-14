from __future__ import annotations
import asyncio
import os
import sys
from pathlib import Path
from typing import Optional
import typer
from scholar_fetch.download.pipeline import run_download

_DEFAULT_OUTPUT_DIR = Path(
    os.environ.get("SCHOLAR_DOWNLOAD_DIR")
    or os.environ.get("SCHOLAR_PDF_DIR", "papers")
)


def download_command(
    results_file: Path = typer.Argument(..., help="Path to Phase 1 results JSON"),
    output_dir: Path = typer.Option(
        _DEFAULT_OUTPUT_DIR, "--output-dir", help="Directory to save downloaded files"
    ),
    top: Optional[int] = typer.Option(
        None,
        "--top",
        help="Target number of successfully downloadable papers to collect",
    ),
) -> None:
    if top is not None and top <= 0:
        raise typer.BadParameter("top must be a positive integer")

    if not results_file.exists():
        print(f"[nexus-dl] error: file not found: {results_file}", file=sys.stderr)
        raise typer.Exit(code=1)

    async def _run() -> None:
        await run_download(
            results_path=results_file,
            output_dir=output_dir,
            top_n=top,
        )

    asyncio.run(_run())
