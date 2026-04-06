from __future__ import annotations
import asyncio
import json
import logging
import sys
from pathlib import Path
from typing import Optional
import httpx
import typer
from nexus_paper_fetcher.models import RunResult
from nexus_paper_fetcher.download.manifest import DownloadSummary, Manifest, load_manifest, save_manifest
from nexus_paper_fetcher.download.downloader import resolve, ManifestEntry

logger = logging.getLogger(__name__)
_CONCURRENCY = 3


def _err(msg: str) -> None:
    print(msg, file=sys.stderr)


def _validated_top_n(top_n: Optional[int]) -> Optional[int]:
    if top_n is None:
        return None
    if top_n <= 0:
        raise typer.BadParameter("top must be a positive integer")
    return top_n


async def run_download(
    results_path: Path,
    output_dir: Path,
    top_n: Optional[int] = None,
) -> Manifest:
    validated_top_n = _validated_top_n(top_n)
    with open(results_path) as f:
        run_result = RunResult.model_validate(json.load(f))

    return await run_download_for_result(
        run_result,
        output_dir,
        validated_top_n,
        source_label=str(results_path),
    )


async def _run_download_for_papers(
    papers,
    output_dir: Path,
    *,
    source_label: str,
    target_success_count: Optional[int] = None,
) -> Manifest:
    manifest_path = output_dir / "manifest.json"
    manifest = load_manifest(manifest_path)
    already_done = manifest.successful_ids()

    ranked_papers = list(enumerate(papers, 1))
    already_downloaded = [
        (rank, paper)
        for rank, paper in ranked_papers
        if paper.paper_id in already_done
    ]
    pending = [
        (rank, paper)
        for rank, paper in ranked_papers
        if paper.paper_id not in already_done
    ]
    skipped = len(already_downloaded)
    _err(
        f"[nexus-dl] loading {source_label}  ->  "
        f"{len(papers)} papers ({skipped} already downloaded)"
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    attempted_entries: list[ManifestEntry] = []
    remaining_needed = None
    if target_success_count is not None:
        remaining_needed = max(target_success_count - skipped, 0)

    if target_success_count is None:
        _err(
            f"[nexus-dl] downloading up to {len(pending)} ranked papers "
            f"(all downloadable content, max {_CONCURRENCY} concurrent)..."
        )
    else:
        _err(
            f"[nexus-dl] downloading until {target_success_count} papers are available "
            f"(max {_CONCURRENCY} concurrent)..."
        )

    async with httpx.AsyncClient(follow_redirects=True, timeout=30.0) as client:
        async def _download_one(rank: int, paper) -> ManifestEntry:
            entry = await resolve(
                paper=paper,
                rank=rank,
                output_dir=output_dir,
                session=client,
            )
            # upsert + save are both synchronous (no await between them), so
            # they cannot be interleaved by the asyncio event loop.
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

        pending_index = 0
        while pending_index < len(pending):
            if remaining_needed is not None and remaining_needed <= 0:
                break

            batch_limit = _CONCURRENCY
            if remaining_needed is not None:
                batch_limit = min(batch_limit, remaining_needed)
            batch = pending[pending_index: pending_index + batch_limit]
            pending_index += len(batch)
            batch_entries = await asyncio.gather(*[_download_one(r, p) for r, p in batch])
            attempted_entries.extend(batch_entries)

            if remaining_needed is not None:
                remaining_needed -= sum(1 for entry in batch_entries if entry.status == "success")

    downloaded_count = sum(1 for entry in attempted_entries if entry.status == "success")
    failed_entries = [entry for entry in attempted_entries if entry.status == "failed"]
    available_count = skipped + downloaded_count
    shortfall_count = 0
    if target_success_count is not None:
        shortfall_count = max(target_success_count - available_count, 0)

    manifest.download_summary = DownloadSummary(
        requested_success_count=target_success_count,
        candidate_count=len(papers),
        attempted_count=len(attempted_entries),
        already_downloaded_count=skipped,
        downloaded_count=downloaded_count,
        available_count=available_count,
        failed_count=len(failed_entries),
        shortfall_count=shortfall_count,
        backup_candidates=failed_entries[:5],
    )
    save_manifest(manifest, manifest_path)

    if target_success_count is None:
        _err(
            f"[nexus-dl] done: {available_count} available, {downloaded_count} downloaded now, "
            f"{len(failed_entries)} failed, {skipped} skipped  ->  {manifest_path}"
        )
    else:
        _err(
            f"[nexus-dl] done: target {target_success_count}, available {available_count}, "
            f"{downloaded_count} downloaded now, {len(failed_entries)} failed, "
            f"{skipped} skipped, shortfall {shortfall_count}  ->  {manifest_path}"
        )

    if failed_entries:
        _err("[nexus-dl] top manual-backup candidates:")
        for entry in failed_entries[:5]:
            _err(f"[nexus-dl]   rank_{entry.rank:02d}  {entry.title}")
    return manifest


async def run_download_for_result(
    run_result: RunResult,
    output_dir: Path,
    top_n: Optional[int] = None,
    *,
    source_label: Optional[str] = None,
) -> Manifest:
    validated_top_n = _validated_top_n(top_n)
    return await _run_download_for_papers(
        run_result.papers,
        output_dir,
        source_label=source_label or "RunResult(in-memory)",
        target_success_count=validated_top_n,
    )
