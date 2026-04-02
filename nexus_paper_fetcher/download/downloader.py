from __future__ import annotations
import logging
import re
from pathlib import Path
from typing import Optional
import httpx
from nexus_paper_fetcher.models import Paper
from nexus_paper_fetcher.download.manifest import ManifestEntry
from nexus_paper_fetcher.download.ezproxy import EZProxySession

logger = logging.getLogger(__name__)


def _sanitize_title(title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", title.lower()).strip("_")
    words = [w for w in slug.split("_") if w][:6]
    return "_".join(words)


def _is_pdf(content: bytes) -> bool:
    return content[:4] == b"%PDF"


async def _fetch_url(session: httpx.AsyncClient, url: str) -> bytes | None:
    try:
        response = await session.get(url, follow_redirects=True)
        content = response.content
        return content if _is_pdf(content) else None
    except Exception as e:
        logger.debug(f"fetch failed for {url}: {e}")
        return None


def _success_entry(
    paper: Paper, rank: int, file_path: Path, content: bytes, source: str
) -> ManifestEntry:
    return ManifestEntry(
        paper_id=paper.paper_id,
        title=paper.title,
        rank=rank,
        score=paper.scores.composite,
        status="success",
        source_used=source,
        file_path=str(file_path),
        file_size_kb=len(content) // 1024,
    )


async def resolve(
    paper: Paper,
    rank: int,
    output_dir: Path,
    session: httpx.AsyncClient,
    ezproxy: Optional[EZProxySession] = None,
    skip_ezproxy: bool = False,
) -> ManifestEntry:
    sanitized = _sanitize_title(paper.title) or paper.paper_id
    filename = f"rank_{rank:02d}_{sanitized}.pdf"
    file_path = output_dir / filename

    # Source 1: open_access_pdf_url (covers OA, arXiv URLs from S2, OpenReview)
    if paper.open_access_pdf_url:
        content = await _fetch_url(session, paper.open_access_pdf_url)
        if content:
            file_path.write_bytes(content)
            return _success_entry(paper, rank, file_path, content, "open_access_url")

    # Source 2: arxiv_id
    if paper.arxiv_id:
        url = f"https://arxiv.org/pdf/{paper.arxiv_id}.pdf"
        content = await _fetch_url(session, url)
        if content:
            file_path.write_bytes(content)
            return _success_entry(paper, rank, file_path, content, "arxiv")

    # Source 3: EZproxy (DOI)
    if not skip_ezproxy and ezproxy is not None and paper.doi:
        content = await ezproxy.get_pdf(paper.doi)
        if content:
            file_path.write_bytes(content)
            return _success_entry(paper, rank, file_path, content, "ezproxy")

    return ManifestEntry(
        paper_id=paper.paper_id,
        title=paper.title,
        rank=rank,
        score=paper.scores.composite,
        status="failed",
        error="no downloadable source found",
    )
