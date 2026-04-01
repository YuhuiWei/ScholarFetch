from __future__ import annotations
import asyncio
import logging
from typing import Optional

import httpx

from nexus_paper_fetcher import config
from nexus_paper_fetcher.fetchers.base import BaseFetcher
from nexus_paper_fetcher.models import Paper, SearchQuery

logger = logging.getLogger(__name__)

BASE_URL = "https://api2.openreview.net/notes"

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


def _get_field(content: dict, key: str) -> Optional[str]:
    val = content.get(key)
    if isinstance(val, dict):
        return val.get("value")
    return val


def _note_to_paper(note: dict, tier: Optional[str], venue: str, year: int) -> Optional[Paper]:
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
    return Paper.create(
        title=title,
        year=year,
        venue=f"{venue} {year}",
        authors=authors if isinstance(authors, list) else [],
        abstract=abstract,
        openreview_tier=tier,
        sources=["openreview"],
    )


class OpenReviewFetcher(BaseFetcher):
    timeout = config.OPENREVIEW_TIMEOUT
    source_name = "openreview"

    async def _fetch(self, query: SearchQuery, client: httpx.AsyncClient) -> list[Paper]:
        year_from = query.year_from or 2020
        year_to = query.year_to or 2024
        target = query.resolved_fetch_per_source()

        tasks = [
            self._fetch_venue_year(client, venue, year, query.query)
            for venue in VENUE_INVITATIONS
            for year in range(year_from, year_to + 1)
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        papers: list[Paper] = []
        for result in results:
            if isinstance(result, list):
                papers.extend(result)

        return papers[:target]

    async def _fetch_venue_year(
        self, client: httpx.AsyncClient, venue: str, year: int, query_term: str
    ) -> list[Paper]:
        sub_inv = VENUE_INVITATIONS[venue].format(year=year)
        dec_inv = DECISION_INVITATIONS[venue].format(year=year)

        sub_resp = await client.get(BASE_URL, params={
            "invitation": sub_inv, "term": query_term, "limit": 100,
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
