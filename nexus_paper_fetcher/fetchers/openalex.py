from __future__ import annotations
import logging
from typing import Optional

import httpx

from nexus_paper_fetcher import config
from nexus_paper_fetcher.fetchers.base import BaseFetcher
from nexus_paper_fetcher.models import Paper, SearchQuery

logger = logging.getLogger(__name__)


def _reconstruct_abstract(inv_index: dict) -> str:
    slots: dict[int, str] = {}
    for word, positions in inv_index.items():
        for pos in positions:
            slots[pos] = word
    return " ".join(slots[i] for i in sorted(slots))


def _work_to_paper(work: dict) -> Optional[Paper]:
    title = work.get("title")
    if not title:
        return None

    doi = work.get("doi")
    if doi:
        doi = doi.removeprefix("https://doi.org/").removeprefix("http://doi.org/")

    inv = work.get("abstract_inverted_index")
    abstract = _reconstruct_abstract(inv) if inv else None

    authors = [
        a["author"]["display_name"]
        for a in (work.get("authorships") or [])
        if a.get("author", {}).get("display_name")
    ]

    primary = work.get("primary_location") or {}
    source_info = primary.get("source") or {}
    venue = source_info.get("display_name")

    raw_id = work.get("id", "")
    openalex_id = raw_id.removeprefix("https://openalex.org/") if raw_id else None

    return Paper.create(
        title=title,
        doi=doi,
        year=work.get("publication_year"),
        authors=authors,
        venue=venue,
        abstract=abstract,
        citation_count=work.get("cited_by_count"),
        openalex_id=openalex_id,
        sources=["openalex"],
    )


class OpenAlexFetcher(BaseFetcher):
    timeout = config.OPENALEX_TIMEOUT
    source_name = "openalex"
    BASE_URL = "https://api.openalex.org/works"

    async def _fetch(self, query: SearchQuery, client: httpx.AsyncClient) -> list[Paper]:
        target = query.resolved_fetch_per_source()
        papers: list[Paper] = []
        cursor = "*"

        while len(papers) < target:
            params: dict = {
                "search": query.query,
                "per-page": min(200, target - len(papers)),
                "cursor": cursor,
                "mailto": config.POLITE_POOL_EMAIL,
            }
            filters = []
            if query.year_from or query.year_to:
                y_from = query.year_from or 1900
                y_to = query.year_to or 2100
                filters.append(f"publication_year:{y_from}-{y_to}")
            if query.author:
                filters.append(
                    f"authorships.author.display_name.search:{query.author}"
                )
            if filters:
                params["filter"] = ",".join(filters)

            response = await client.get(self.BASE_URL, params=params)
            response.raise_for_status()
            data = response.json()

            results = data.get("results", [])
            if not results:
                break
            for work in results:
                p = _work_to_paper(work)
                if p:
                    papers.append(p)

            cursor = (data.get("meta") or {}).get("next_cursor")
            if not cursor:
                break

        return papers[:target]
