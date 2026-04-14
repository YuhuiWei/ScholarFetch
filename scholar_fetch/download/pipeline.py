from __future__ import annotations
import asyncio
import json
import logging
import os
import sys
from pathlib import Path
from typing import Optional
import httpx
import typer
from scholar_fetch.models import RunResult
from scholar_fetch.download.manifest import DownloadSummary, Manifest, load_manifest, save_manifest
from scholar_fetch.download.downloader import resolve, ManifestEntry
from scholar_fetch.download.progress import DownloadProgress, load_progress, save_progress
from scholar_fetch.download.manual import update_manual_md

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


def _save_result_json(result: RunResult, path: Path) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(result.model_dump(mode="json"), indent=2, default=str))
    os.replace(tmp, path)


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
    result_json_path: Optional[Path] = None,
) -> Optional[Manifest]:
    """Download papers from run_result.

    When result_json_path is provided (ScholarWiki mode):
      - Updates download_status/download_file_path on each Paper in-place
      - Saves result JSON after each download (crash-safe via download_progress.json)
      - Generates manual.md for failed papers
      - Does NOT write manifest.json

    When result_json_path is None (legacy mode):
      - Writes manifest.json and returns a Manifest object
    """
    validated_top_n = _validated_top_n(top_n)
    if result_json_path is not None:
        await _run_download_inplace(
            run_result,
            output_dir,
            validated_top_n,
            source_label=source_label or "RunResult(in-memory)",
            result_json_path=result_json_path,
        )
        return None
    return await _run_download_for_papers(
        run_result.papers,
        output_dir,
        source_label=source_label or "RunResult(in-memory)",
        target_success_count=validated_top_n,
    )


async def _run_download_inplace(
    run_result: RunResult,
    output_dir: Path,
    top_n: Optional[int],
    *,
    source_label: str,
    result_json_path: Path,
) -> None:
    """ScholarWiki-mode download: in-place JSON updates, progress tracker, manual.md."""
    papers = run_result.papers  # full candidate list; download loop stops at top_n successes

    output_dir.mkdir(parents=True, exist_ok=True)
    progress_path = output_dir / "download_progress.json"
    progress = load_progress(progress_path)

    id_to_idx = {p.paper_id: i for i, p in enumerate(run_result.papers)}
    already_done = progress.successful_ids()
    ranked_papers = list(enumerate(papers, 1))
    pending = [(rank, p) for rank, p in ranked_papers if p.paper_id not in already_done]
    skipped = len(ranked_papers) - len(pending)

    target_msg = f", targeting {top_n} successes" if top_n is not None else ""
    _err(
        f"[nexus-dl] loading {source_label}  →  "
        f"{len(papers)} candidates{target_msg} ({skipped} already downloaded)"
    )

    # Restore status for already-downloaded papers
    for pid in already_done:
        entry = progress.get(pid)
        if entry and pid in id_to_idx:
            p = run_result.papers[id_to_idx[pid]]
            p.download_status = "success"
            p.download_file_path = entry.file_path

    failed_entries: list[tuple, int] = []  # (paper, rank) pairs

    async with httpx.AsyncClient(follow_redirects=True, timeout=30.0) as client:
        async def _download_one(rank: int, paper) -> ManifestEntry:
            entry = await resolve(paper=paper, rank=rank, output_dir=output_dir, session=client)
            status = "success" if entry.status == "success" else "failed"
            progress.upsert(paper.paper_id, status, entry.file_path)
            save_progress(progress, progress_path)

            if paper.paper_id in id_to_idx:
                rp = run_result.papers[id_to_idx[paper.paper_id]]
                rp.download_status = status
                rp.download_file_path = entry.file_path

            _save_result_json(run_result, result_json_path)

            icon = "ok" if entry.status == "success" else "fail"
            source = entry.source_used or "-"
            size = f"({entry.file_size_kb:>4} KB)" if entry.file_size_kb else " " * 9
            name = Path(entry.file_path).name if entry.file_path else (entry.error or "")
            _err(f"[nexus-dl]   rank_{rank:02d}  {icon}  {source:<20} {size}  {name}")
            return entry

        remaining = top_n
        pending_idx = 0
        while pending_idx < len(pending):
            if remaining is not None and remaining <= 0:
                break
            batch_size = _CONCURRENCY if remaining is None else min(_CONCURRENCY, remaining)
            batch = pending[pending_idx: pending_idx + batch_size]
            pending_idx += len(batch)
            batch_entries = await asyncio.gather(*[_download_one(r, p) for r, p in batch])
            if remaining is not None:
                remaining -= sum(1 for e in batch_entries if e.status == "success")
            for entry, (rank, paper) in zip(batch_entries, batch):
                if entry.status == "failed":
                    failed_entries.append((run_result.papers[id_to_idx[paper.paper_id]], rank))

    # Mark not-attempted papers
    attempted_ids = {p.paper_id for _, p in ranked_papers}
    for paper in run_result.papers:
        if paper.download_status is None:
            paper.download_status = "not_attempted" if paper.paper_id not in attempted_ids else "failed"

    _save_result_json(run_result, result_json_path)

    if failed_entries:
        update_manual_md(output_dir, failed_entries, source_json=str(result_json_path))

    downloaded = sum(1 for p in run_result.papers if p.download_status == "success")
    failed = sum(1 for p in run_result.papers if p.download_status == "failed")
    _err(
        f"[nexus-dl] done: {downloaded} downloaded, {failed} failed, "
        f"{skipped} skipped  →  {result_json_path}"
    )
