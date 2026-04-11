from __future__ import annotations
import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

import httpx

from nexus_paper_fetcher import config
from nexus_paper_fetcher.fetchers.base import BaseFetcher
from nexus_paper_fetcher.models import Paper, SearchQuery

logger = logging.getLogger(__name__)

BASE_URL = "https://api2.openreview.net/notes"
SEARCH_URL = "https://api2.openreview.net/notes/search"

VENUE_INVITATIONS = {
    "ICLR": "ICLR.cc/{year}/Conference/-/Blind_Submission",
    "NeurIPS": "NeurIPS.cc/{year}/Conference/-/Blind_Submission",
    "ICML": "ICML.cc/{year}/Conference/-/Blind_Submission",
}
DECISION_INVITATIONS = {
    "ICLR": "ICLR.cc/{year}/Conference/-/Decision",
    "NeurIPS": "NeurIPS.cc/{year}/Conference/-/Decision",
    "ICML": "ICML.cc/{year}/Conference/-/Decision",
}
TIER_MAP = {
    "accept (oral)": "oral",
    "accept (spotlight)": "spotlight",
    "accept (poster)": "poster",
}


def _parse_tier(decision_str: str) -> Optional[str]:
    return TIER_MAP.get(decision_str.lower().strip())


def _infer_tier_from_venue(venue_label: Optional[str]) -> Optional[str]:
    label = (venue_label or "").lower()
    if "oral" in label:
        return "oral"
    if "spotlight" in label:
        return "spotlight"
    if "poster" in label:
        return "poster"
    return None


def _get_field(content: dict, key: str) -> Optional[str]:
    val = content.get(key)
    if isinstance(val, dict):
        return val.get("value")
    return val


def _note_to_json(note) -> dict:
    if isinstance(note, dict):
        return note
    if hasattr(note, "to_json"):
        return note.to_json()
    payload = {}
    for attr in ("id", "forum", "content", "cdate", "pdate", "tmdate", "tcdate", "mdate"):
        if hasattr(note, attr):
            payload[attr] = getattr(note, attr)
    return payload


def _note_year(note: dict, fallback_year: Optional[int] = None) -> Optional[int]:
    for key in ("pdate", "cdate", "tcdate", "tmdate", "mdate"):
        value = note.get(key)
        if value:
            try:
                timestamp = float(value) / 1000.0
                return datetime.fromtimestamp(timestamp, tz=timezone.utc).year
            except (OverflowError, OSError, ValueError):
                continue
    return fallback_year


def _openreview_pdf_url(note: dict, content: dict) -> Optional[str]:
    """Derive a direct PDF URL from a note, preferring the content 'pdf' field."""
    pdf_field = _get_field(content, "pdf")
    if pdf_field:
        if pdf_field.startswith("http"):
            return pdf_field
        # Relative path like "/pdf/abc123.pdf"
        return f"https://openreview.net{pdf_field}" if pdf_field.startswith("/") else f"https://openreview.net/{pdf_field}"
    forum_id = note.get("forum") or note.get("id")
    if forum_id:
        return f"https://openreview.net/pdf?id={forum_id}"
    return None


def _note_to_paper(
    note: dict,
    tier: Optional[str],
    venue: Optional[str],
    year: Optional[int],
) -> Optional[Paper]:
    content = note.get("content") or {}
    title = _get_field(content, "title")
    if not title:
        return None
    abstract = _get_field(content, "abstract")
    authors_raw = content.get("authors")
    if isinstance(authors_raw, dict):
        authors = authors_raw.get("value") or []
    else:
        authors = authors_raw or []
    venue_label = venue or _get_field(content, "venue") or _get_field(content, "venueid") or "OpenReview"
    return Paper.create(
        title=title,
        year=year,
        venue=venue_label,
        authors=authors if isinstance(authors, list) else [],
        abstract=abstract,
        open_access_pdf_url=_openreview_pdf_url(note, content),
        openreview_tier=tier or _infer_tier_from_venue(venue_label),
        publication_type="conference_paper",
        source_publication_types={"openreview": "conference_paper"},
        sources=["openreview"],
    )


class OpenReviewFetcher(BaseFetcher):
    timeout = config.OPENREVIEW_TIMEOUT
    source_name = "openreview"

    def _get_api_v2_client(self):
        from openreview.api import OpenReviewClient

        return OpenReviewClient(
            baseurl=config.OPENREVIEW_BASEURL,
            username=config.OPENREVIEW_USERNAME,
            password=config.OPENREVIEW_PASSWORD,
        )

    async def _fetch(self, query: SearchQuery, client: httpx.AsyncClient) -> list[Paper]:
        year_from = query.year_from or 2020
        year_to = query.year_to or datetime.now(timezone.utc).year
        target = query.resolved_fetch_per_source()
        papers: list[Paper] = []
        seen_titles: set[str] = set()

        for paper in await self._search_query(client, query.query, year_from, year_to, target):
            normalized_title = paper.title.strip().lower()
            if normalized_title in seen_titles:
                continue
            seen_titles.add(normalized_title)
            papers.append(paper)
            if len(papers) >= target:
                return papers[:target]

        tasks = [
            self._fetch_venue_year(client, venue, year)
            for venue in VENUE_INVITATIONS
            for year in range(year_from, year_to + 1)
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for result in results:
            if isinstance(result, list):
                for paper in result:
                    normalized_title = paper.title.strip().lower()
                    if normalized_title in seen_titles:
                        continue
                    seen_titles.add(normalized_title)
                    papers.append(paper)
                    if len(papers) >= target:
                        return papers[:target]

        return papers[:target]

    async def _search_query(
        self,
        client: httpx.AsyncClient,
        query_text: str,
        year_from: int,
        year_to: int,
        limit: int,
    ) -> list[Paper]:
        if config.OPENREVIEW_USERNAME and config.OPENREVIEW_PASSWORD:
            try:
                return await self._search_query_authenticated(
                    query_text=query_text,
                    year_from=year_from,
                    year_to=year_to,
                    limit=limit,
                )
            except Exception as exc:
                logger.warning("OpenReview authenticated search failed for %r: %s", query_text, exc)

        try:
            response = await client.get(
                SEARCH_URL,
                params={
                    "query": query_text,
                    "content": "all",
                    "source": "all",
                    "sort": "tmdate:desc",
                    "limit": min(limit, 100),
                },
            )
            if response.status_code == 403:
                logger.info(
                    "OpenReview anonymous search forbidden for %r; falling back to public venue enumeration",
                    query_text,
                )
                return []
        except Exception as exc:
            logger.debug("OpenReview query search unavailable for %r: %s", query_text, exc)
            return []
        if response.status_code == 404:
            return []
        response.raise_for_status()

        papers: list[Paper] = []
        for note in response.json().get("notes", []):
            note_year = _note_year(note)
            if note_year is not None and not (year_from <= note_year <= year_to):
                continue
            content = note.get("content") or {}
            venue = _get_field(content, "venue") or _get_field(content, "venueid") or "OpenReview"
            paper = _note_to_paper(
                note,
                _infer_tier_from_venue(venue),
                venue,
                note_year,
            )
            if paper:
                papers.append(paper)
        return papers[:limit]

    async def _search_query_authenticated(
        self,
        *,
        query_text: str,
        year_from: int,
        year_to: int,
        limit: int,
    ) -> list[Paper]:
        # OpenReviewClient and search_notes are synchronous; run them in a thread
        # to avoid blocking the asyncio event loop (which would stall parallel fetchers).
        api_client = await asyncio.to_thread(self._get_api_v2_client)
        page_size = max(1, min(config.OPENREVIEW_SEARCH_PAGE_SIZE, limit))
        offset = 0
        papers: list[Paper] = []

        while len(papers) < limit:
            batch_limit = page_size
            notes = await asyncio.to_thread(
                api_client.search_notes,
                term=query_text,
                content="all",
                group="all",
                source="all",
                limit=batch_limit,
                offset=offset,
            )
            if not notes:
                break

            for raw_note in notes:
                note = _note_to_json(raw_note)
                note_year = _note_year(note)
                if note_year is not None and not (year_from <= note_year <= year_to):
                    continue
                content = note.get("content") or {}
                venue = _get_field(content, "venue") or _get_field(content, "venueid") or "OpenReview"
                paper = _note_to_paper(
                    note,
                    _infer_tier_from_venue(venue),
                    venue,
                    note_year,
                )
                if paper:
                    papers.append(paper)
                    if len(papers) >= limit:
                        break

            if len(notes) < batch_limit:
                break
            offset += len(notes)

        return papers[:limit]

    async def _fetch_venue_year(
        self, client: httpx.AsyncClient, venue: str, year: int
    ) -> list[Paper]:
        sub_inv = VENUE_INVITATIONS[venue].format(year=year)
        dec_inv = DECISION_INVITATIONS[venue].format(year=year)

        sub_resp = await client.get(BASE_URL, params={
            "invitation": sub_inv, "limit": 100,
        })
        if sub_resp.status_code == 404:
            return []
        sub_resp.raise_for_status()
        submissions = sub_resp.json().get("notes", [])
        if not submissions:
            return []

        # Fetch all decisions for this venue — build forum_id → tier map
        decisions: dict[str, Optional[str]] = {}
        dec_resp = await client.get(BASE_URL, params={"invitation": dec_inv, "limit": 1000})
        if dec_resp.status_code == 200:
            for note in dec_resp.json().get("notes", []):
                forum_id = note.get("forum")
                content = note.get("content") or {}
                decision_str = _get_field(content, "decision") or ""
                decisions[forum_id] = _parse_tier(decision_str)

        papers: list[Paper] = []
        for sub in submissions:
            forum_id = sub.get("forum") or sub.get("id")
            if forum_id in decisions and decisions[forum_id] is None:
                continue  # explicitly rejected
            tier = decisions.get(forum_id)
            p = _note_to_paper(sub, tier, venue, year)
            if p:
                papers.append(p)

        return papers
