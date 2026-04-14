from __future__ import annotations
import logging
from typing import Optional

import httpx

from scholar_fetch import config
from scholar_fetch.fetchers.base import BaseFetcher
from scholar_fetch.models import Paper, SearchQuery

logger = logging.getLogger(__name__)

_FIELDS = ",".join([
    "title", "abstract", "year", "authors", "venue",
    "citationCount", "influentialCitationCount",
    "openAccessPdf", "externalIds", "publicationTypes", "tldr",
])


def _s2_to_paper(item: dict) -> Optional[Paper]:
    title = item.get("title")
    if not title:
        return None

    ext = item.get("externalIds") or {}
    doi = ext.get("DOI")
    arxiv_id = ext.get("ArXiv")

    authors = [
        a["name"] for a in (item.get("authors") or []) if a.get("name")
    ]

    influential = item.get("influentialCitationCount") or 0
    citation_count = influential if influential > 0 else item.get("citationCount")

    oap = item.get("openAccessPdf") or {}
    open_access_url = oap.get("url")
    publication_types = [
        str(publication_type).lower()
        for publication_type in (item.get("publicationTypes") or [])
        if publication_type
    ]
    publication_type = publication_types[0] if publication_types else None

    return Paper.create(
        title=title,
        doi=doi,
        arxiv_id=arxiv_id,
        year=item.get("year"),
        authors=authors,
        venue=item.get("venue"),
        abstract=item.get("abstract"),
        citation_count=citation_count,
        publication_type=publication_type,
        source_publication_types=(
            {"semantic_scholar": publication_type} if publication_type else {}
        ),
        semantic_scholar_id=item.get("paperId"),
        open_access_pdf_url=open_access_url,
        sources=["semantic_scholar"],
    )


class SemanticScholarFetcher(BaseFetcher):
    timeout = config.S2_TIMEOUT
    source_name = "semantic_scholar"
    BASE_URL = "https://api.semanticscholar.org/graph/v1/paper/search"

    async def _fetch(self, query: SearchQuery, client: httpx.AsyncClient) -> list[Paper]:
        target = query.resolved_fetch_per_source()
        papers: list[Paper] = []
        offset = 0
        page_size = 100

        headers = {}
        if config.S2_API_KEY:
            headers["x-api-key"] = config.S2_API_KEY

        while len(papers) < target:
            params: dict = {
                "query": query.query,
                "fields": _FIELDS,
                "limit": min(page_size, target - len(papers)),
                "offset": offset,
            }
            if query.year_from or query.year_to:
                y_from = query.year_from or 1900
                y_to = query.year_to or 2100
                params["year"] = f"{y_from}-{y_to}"

            response = await client.get(self.BASE_URL, params=params, headers=headers)
            response.raise_for_status()
            data = response.json()

            items = data.get("data", [])
            if not items:
                break
            for item in items:
                p = _s2_to_paper(item)
                if p:
                    papers.append(p)

            offset += len(items)
            if offset >= data.get("total", 0):
                break

        return papers[:target]
