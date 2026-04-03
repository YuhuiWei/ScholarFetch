from __future__ import annotations
import logging
import os
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Optional
import httpx
from nexus_paper_fetcher.models import Paper
from nexus_paper_fetcher.download.manifest import ManifestEntry
from nexus_paper_fetcher.fetchers.openalex import extract_open_access_pdf_url

logger = logging.getLogger(__name__)
OPENALEX_WORKS_URL = "https://api.openalex.org/works"
ARXIV_API_URL = "https://export.arxiv.org/api/query"
UNPAYWALL_API_URL = "https://api.unpaywall.org/v2"
DEFAULT_UNPAYWALL_EMAIL = "weiy@ohsu"
UNPAYWALL_EMAIL_ENV_VAR = "NEXUS_UNPAYWALL_EMAIL"
ELSEVIER_API_KEY_ENV_VAR = "ELSEVIER_API_KEY"
ELSEVIER_ARTICLE_DOI_URL = "https://api.elsevier.com/content/article/doi"
DOWNLOAD_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
    ),
    "Accept": "application/pdf,application/octet-stream;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


def _sanitize_title(title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", title.lower()).strip("_")
    words = [w for w in slug.split("_") if w][:6]
    return "_".join(words)


def _is_pdf(content: bytes) -> bool:
    return content[:4] == b"%PDF"


def _is_xml(content: bytes) -> bool:
    stripped = content.lstrip()
    if not stripped:
        return False
    if not stripped.startswith((b"<?xml", b"<")):
        return False
    try:
        ET.fromstring(content)
    except ET.ParseError:
        return False
    return True


def _normalize_doi(doi: Optional[str]) -> str | None:
    if not doi:
        return None
    normalized = doi.strip().lower()
    for prefix in (
        "https://doi.org/",
        "http://doi.org/",
        "https://dx.doi.org/",
        "http://dx.doi.org/",
        "doi:",
    ):
        if normalized.startswith(prefix):
            normalized = normalized[len(prefix):]
            break
    normalized = normalized.strip()
    return normalized or None


def _extract_arxiv_pdf_from_feed(feed_xml: str, expected_doi: str) -> str | None:
    root = ET.fromstring(feed_xml)
    namespaces = {
        "atom": "http://www.w3.org/2005/Atom",
        "arxiv": "http://arxiv.org/schemas/atom",
    }
    for entry in root.findall("atom:entry", namespaces):
        doi_node = entry.find("arxiv:doi", namespaces)
        id_node = entry.find("atom:id", namespaces)
        if doi_node is None or id_node is None or not doi_node.text or not id_node.text:
            continue
        if _normalize_doi(doi_node.text) != expected_doi:
            continue
        arxiv_id = id_node.text.rsplit("/", 1)[-1].strip()
        if not arxiv_id:
            continue
        return f"https://arxiv.org/pdf/{arxiv_id}.pdf"
    return None


async def _find_arxiv_pdf_by_doi(
    session: httpx.AsyncClient,
    doi: Optional[str],
) -> str | None:
    normalized = _normalize_doi(doi)
    if not normalized:
        return None
    try:
        response = await session.get(
            ARXIV_API_URL,
            params={
                "search_query": f'doi:"{normalized}"',
                "start": 0,
                "max_results": 5,
            },
        )
        if response.status_code == 404:
            return None
        response.raise_for_status()
        return _extract_arxiv_pdf_from_feed(response.text, normalized)
    except Exception as exc:
        logger.debug("arXiv DOI lookup failed for %s: %s", normalized, exc)
        return None


def _extract_unpaywall_pdf_url(payload: object) -> str | None:
    if not isinstance(payload, dict):
        return None

    best = payload.get("best_oa_location")
    if isinstance(best, dict):
        best_pdf = best.get("url_for_pdf")
        if isinstance(best_pdf, str) and best_pdf:
            return best_pdf
        best_url = best.get("url")
        if isinstance(best_url, str) and best_url:
            return best_url

    locations = payload.get("oa_locations")
    if not isinstance(locations, list):
        return None

    for location in locations:
        if not isinstance(location, dict):
            continue
        location_pdf = location.get("url_for_pdf")
        if isinstance(location_pdf, str) and location_pdf:
            return location_pdf
        location_url = location.get("url")
        if isinstance(location_url, str) and location_url:
            return location_url
    return None


def _resolve_unpaywall_email(email: Optional[str]) -> str:
    if email:
        return email
    return os.environ.get(UNPAYWALL_EMAIL_ENV_VAR, DEFAULT_UNPAYWALL_EMAIL)


async def _find_unpaywall_pdf_by_doi(
    session: httpx.AsyncClient,
    doi: Optional[str],
    email: Optional[str] = None,
) -> str | None:
    normalized = _normalize_doi(doi)
    if not normalized:
        return None
    resolved_email = _resolve_unpaywall_email(email)
    try:
        response = await session.get(
            f"{UNPAYWALL_API_URL}/{normalized}",
            params={"email": resolved_email},
        )
        if response.status_code == 404:
            return None
        response.raise_for_status()
        payload = response.json()
        return _extract_unpaywall_pdf_url(payload)
    except Exception as exc:
        logger.debug(
            "Unpaywall DOI lookup failed for %s with email %s: %s",
            normalized,
            resolved_email,
            exc,
        )
        return None


async def _fetch_url(session: httpx.AsyncClient, url: str) -> bytes | None:
    try:
        response = await session.get(url, follow_redirects=True, headers=DOWNLOAD_HEADERS)
        content = response.content
        return content if _is_pdf(content) else None
    except Exception as e:
        logger.debug(f"fetch failed for {url}: {e}")
        return None


async def _fetch_elsevier_xml_by_doi(
    session: httpx.AsyncClient,
    doi: Optional[str],
) -> bytes | None:
    normalized = _normalize_doi(doi)
    if not normalized or not normalized.startswith("10.1016/"):
        return None

    api_key = os.environ.get(ELSEVIER_API_KEY_ENV_VAR)
    if not api_key:
        return None

    try:
        response = await session.get(
            f"{ELSEVIER_ARTICLE_DOI_URL}/{normalized}",
            params={"view": "FULL"},
            headers={
                "X-ELS-APIKey": api_key,
                "Accept": "application/xml",
            },
        )
        if response.status_code in {401, 403, 404}:
            return None
        response.raise_for_status()
        content = response.content
        return content if _is_xml(content) else None
    except Exception as exc:
        logger.debug("Elsevier DOI lookup failed for %s: %s", normalized, exc)
        return None


async def _recover_openalex_pdf_url(
    session: httpx.AsyncClient,
    openalex_id: Optional[str],
) -> str | None:
    if not openalex_id:
        return None

    try:
        response = await session.get(f"{OPENALEX_WORKS_URL}/{openalex_id}")
        response.raise_for_status()
        return extract_open_access_pdf_url(response.json())
    except Exception as exc:
        logger.debug("OpenAlex recovery failed for %s: %s", openalex_id, exc)
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


def _build_output_path(
    output_dir: Path, rank: int, title: str, paper_id: str, suffix: str
) -> Path:
    sanitized = _sanitize_title(title) or paper_id
    filename = f"rank_{rank:02d}_{sanitized}{suffix}"
    return output_dir / filename


async def resolve(
    paper: Paper,
    rank: int,
    output_dir: Path,
    session: httpx.AsyncClient,
) -> ManifestEntry:
    pdf_path = _build_output_path(
        output_dir=output_dir,
        rank=rank,
        title=paper.title,
        paper_id=paper.paper_id,
        suffix=".pdf",
    )

    # Source 1: open_access_pdf_url (covers OA, arXiv URLs from S2, OpenReview)
    if paper.open_access_pdf_url:
        content = await _fetch_url(session, paper.open_access_pdf_url)
        if content:
            pdf_path.write_bytes(content)
            return _success_entry(paper, rank, pdf_path, content, "open_access_url")

    # Source 1b: OpenAlex recovery from openalex_id
    if paper.openalex_id:
        recovered_open_access_pdf_url = await _recover_openalex_pdf_url(
            session, paper.openalex_id
        )
        if recovered_open_access_pdf_url:
            content = await _fetch_url(session, recovered_open_access_pdf_url)
            if content:
                pdf_path.write_bytes(content)
                return _success_entry(paper, rank, pdf_path, content, "open_access_url")

    # Source 2: DOI -> arXiv
    arxiv_pdf_url = await _find_arxiv_pdf_by_doi(session, paper.doi)
    if arxiv_pdf_url:
        content = await _fetch_url(session, arxiv_pdf_url)
        if content:
            pdf_path.write_bytes(content)
            return _success_entry(paper, rank, pdf_path, content, "arxiv")

    # Source 3: DOI -> Unpaywall
    unpaywall_pdf_url = await _find_unpaywall_pdf_by_doi(session, paper.doi)
    if unpaywall_pdf_url:
        content = await _fetch_url(session, unpaywall_pdf_url)
        if content:
            pdf_path.write_bytes(content)
            return _success_entry(paper, rank, pdf_path, content, "open_access_url")

    # Source 4: DOI -> Elsevier full-text XML (subscription API)
    elsevier_xml = await _fetch_elsevier_xml_by_doi(session, paper.doi)
    if elsevier_xml:
        xml_path = _build_output_path(
            output_dir=output_dir,
            rank=rank,
            title=paper.title,
            paper_id=paper.paper_id,
            suffix=".xml",
        )
        xml_path.write_bytes(elsevier_xml)
        return _success_entry(paper, rank, xml_path, elsevier_xml, "elsevier_api")

    return ManifestEntry(
        paper_id=paper.paper_id,
        title=paper.title,
        rank=rank,
        score=paper.scores.composite,
        status="failed",
        error="no downloadable source found",
    )
