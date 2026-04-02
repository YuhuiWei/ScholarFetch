from __future__ import annotations
import asyncio
import json
import logging
import sys
from pathlib import Path
from typing import Optional
import httpx
from nexus_paper_fetcher.models import RunResult
from nexus_paper_fetcher.download.manifest import Manifest, load_manifest, save_manifest
from nexus_paper_fetcher.download.ezproxy import EZProxySession
from nexus_paper_fetcher.download.downloader import resolve, ManifestEntry

logger = logging.getLogger(__name__)
_CONCURRENCY = 3


def _err(msg: str) -> None:
    print(msg, file=sys.stderr)


async def run_download(
    results_path: Path,
    output_dir: Path,
    top_n: Optional[int] = None,
    skip_ezproxy: bool = False,
) -> Manifest:
    with open(results_path) as f:
        run_result = RunResult.model_validate(json.load(f))

    papers = run_result.papers[:top_n] if top_n is not None else run_result.papers
    manifest_path = output_dir / "manifest.json"
    manifest = load_manifest(manifest_path)
    already_done = manifest.successful_ids()

    to_download = [
        (rank, paper)
        for rank, paper in enumerate(papers, 1)
        if paper.paper_id not in already_done
    ]
    skipped = len(papers) - len(to_download)
    _err(
        f"[nexus-dl] loading {results_path}  ->  "
        f"{len(papers)} papers ({skipped} already downloaded)"
    )

    output_dir.mkdir(parents=True, exist_ok=True)

    async with httpx.AsyncClient(follow_redirects=True, timeout=30.0) as client:
        ezproxy: Optional[EZProxySession] = None
        if not skip_ezproxy:
            ez = EZProxySession(client)
            if await ez.authenticate():
                _err("[nexus-dl] EZproxy auth ok")
                ezproxy = ez
            else:
                _err("[nexus-dl] EZproxy auth failed  (free sources only)")
                skip_ezproxy = True

        _err(
            f"[nexus-dl] downloading {len(to_download)} papers "
            f"(max {_CONCURRENCY} concurrent)..."
        )
        semaphore = asyncio.Semaphore(_CONCURRENCY)

        async def _download_one(rank: int, paper) -> ManifestEntry:
            async with semaphore:
                entry = await resolve(
                    paper=paper,
                    rank=rank,
                    output_dir=output_dir,
                    session=client,
                    ezproxy=ezproxy,
                    skip_ezproxy=skip_ezproxy,
                )
                # upsert + save are both synchronous (no await between them), so
                # they cannot be interleaved by the asyncio event loop even with
                # Semaphore(3). Safe without an explicit lock.
                manifest.upsert(entry)
                save_manifest(manifest, manifest_path)
                icon = "ok" if entry.status == "success" else "fail"
                source = entry.source_used or "-"
                size = f"({entry.file_size_kb:>4} KB)" if entry.file_size_kb else " " * 9
                name = (
                    Path(entry.file_path).name
                    if entry.file_path
                    else (entry.error or "")
                )
                _err(f"[nexus-dl]   rank_{rank:02d}  {icon}  {source:<20} {size}  {name}")
                return entry

        await asyncio.gather(*[_download_one(r, p) for r, p in to_download])

    success = sum(1 for e in manifest.entries if e.status == "success")
    failed = sum(1 for e in manifest.entries if e.status == "failed")
    _err(
        f"[nexus-dl] done: {success} success, {failed} failed, "
        f"{skipped} skipped  ->  {manifest_path}"
    )
    return manifest
