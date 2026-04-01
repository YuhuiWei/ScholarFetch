from __future__ import annotations
import asyncio
import logging
import sys
from datetime import datetime
from typing import Optional

from nexus_paper_fetcher.models import Paper, RunResult, SearchQuery
from nexus_paper_fetcher.fetchers.openalex import OpenAlexFetcher
from nexus_paper_fetcher.fetchers.semantic_scholar import SemanticScholarFetcher
from nexus_paper_fetcher.fetchers.openreview import OpenReviewFetcher
from nexus_paper_fetcher.dedup import deduplicate
from nexus_paper_fetcher.domain import classify_domain
from nexus_paper_fetcher.scoring.scorer import score_all

logger = logging.getLogger(__name__)


def _err(msg: str) -> None:
    print(msg, file=sys.stderr)


async def run(
    query: SearchQuery,
    domain_category_override: Optional[str] = None,
) -> RunResult:
    # Step 1: classify domain
    domain_category = await classify_domain(query.query, domain_category_override)
    _err(f"[nexus] classifying domain... {domain_category}")

    # Step 2: parallel fetch
    active_fetchers = [OpenAlexFetcher(), SemanticScholarFetcher()]
    if domain_category == "cs_ml":
        active_fetchers.append(OpenReviewFetcher())
    else:
        _err(f"[nexus]   {'openreview':<20} –  skipped (domain: {domain_category})")

    _err(
        f"[nexus] fetching from {len(active_fetchers)} sources "
        f"(fetch_per_source={query.resolved_fetch_per_source()})"
    )
    results = await asyncio.gather(
        *[f.fetch(query) for f in active_fetchers],
        return_exceptions=True,
    )

    all_papers: list[Paper] = []
    sources_used: list[str] = []
    sources_failed: list[str] = []

    for fetcher, result in zip(active_fetchers, results):
        if isinstance(result, Exception):
            sources_failed.append(fetcher.source_name)
            _err(f"[nexus]   {fetcher.source_name:<20} ✗  failed ({result})")
        elif isinstance(result, list):
            count = len(result)
            if count:
                sources_used.append(fetcher.source_name)
            _err(f"[nexus]   {fetcher.source_name:<20} {'✓' if count else '–'}  {count} papers")
            all_papers.extend(result)

    # Step 3: dedup
    _err(f"[nexus] deduplicating {len(all_papers)} papers...")
    unique = deduplicate(all_papers)
    _err(f"[nexus] deduplicating → {len(unique)} unique")

    # Step 4: score
    import nexus_paper_fetcher.config as cfg
    suffix = " (relevance via OpenAI)" if cfg.OPENAI_API_KEY else " (relevance defaulting to 0.5)"
    _err(f"[nexus] scoring {len(unique)} papers{suffix}...")
    scored = await score_all(unique, query.query, domain_category)

    # Step 5: rank and truncate
    top_n = sorted(scored, key=lambda p: p.scores.composite, reverse=True)[: query.top_n]

    return RunResult(
        query=query.query,
        domain_category=domain_category,
        params=query,
        timestamp=datetime.utcnow(),
        sources_used=sources_used,
        sources_failed=sources_failed,
        papers=top_n,
    )
