from __future__ import annotations
import asyncio
import logging
import re
import sys
from datetime import datetime, timezone
from typing import Optional

from rapidfuzz import fuzz

import scholar_fetch.config as cfg
from scholar_fetch.evaluation import (
    LlmCategoricalJudge,
    apply_metadata_heuristics,
    filter_by_target_category,
    select_llm_candidates,
    target_publication_category,
)
from scholar_fetch.models import Paper, RunResult, SearchQuery
from scholar_fetch.fetchers.openalex import OpenAlexFetcher
from scholar_fetch.fetchers.semantic_scholar import SemanticScholarFetcher
from scholar_fetch.fetchers.openreview import OpenReviewFetcher
from scholar_fetch.dedup import deduplicate
from scholar_fetch.domain import classify_domain
from scholar_fetch.scoring.scorer import score_all

logger = logging.getLogger(__name__)


def _err(msg: str) -> None:
    print(msg, file=sys.stderr)


def _normalize_title(text: str) -> str:
    normalized = re.sub(r"[^\w\s]", " ", text.lower())
    return re.sub(r"\s+", " ", normalized).strip()


def _rank_lookup_results(
    papers: list[Paper],
    search_query: SearchQuery,
) -> tuple[list[Paper], bool, str]:
    targets = search_query.paper_titles or [search_query.query]
    normalized_targets = [_normalize_title(title) for title in targets if title.strip()]

    for paper in papers:
        normalized_title = _normalize_title(paper.title)
        similarities = [
            fuzz.token_sort_ratio(normalized_title, normalized_target)
            for normalized_target in normalized_targets
        ]
        best_similarity = max(similarities, default=0.0)
        paper.title_match_score = round(best_similarity / 100.0, 4)
        paper.exact_match = normalized_title in normalized_targets

    ranked = sorted(
        papers,
        key=lambda paper: (
            paper.exact_match,
            paper.title_match_score,
            paper.scores.composite,
        ),
        reverse=True,
    )
    not_found = not any(paper.exact_match for paper in ranked)
    return ranked[: search_query.top_n], not_found, "closest_match" if not_found else "exact_match"


async def run(
    query: SearchQuery,
    domain_category_override: Optional[str] = None,
) -> RunResult:
    # Step 1: classify domain
    domain_categories = await classify_domain(query.query, domain_category_override)
    domain_label = ", ".join(domain_categories)
    _err(f"[scholar] classifying domain... {domain_label}")
    _err(f"[scholar] query intent... {query.query_intent}")
    if query.query_intent == "domain_search" and query.search_scope:
        _err(f"[scholar] search scope... {query.search_scope}")

    # Step 2: parallel fetch — include OpenReview whenever cs_ml is one of the domains
    active_fetchers = [OpenAlexFetcher(), SemanticScholarFetcher()]
    if "cs_ml" in domain_categories:
        active_fetchers.append(OpenReviewFetcher())
    else:
        _err(f"[scholar]   {'openreview':<20} –  skipped (domain: {domain_label})")

    _err(
        f"[scholar] fetching from {len(active_fetchers)} sources "
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
            _err(f"[scholar]   {fetcher.source_name:<20} ✗  failed ({result})")
        elif isinstance(result, list):
            count = len(result)
            if count:
                sources_used.append(fetcher.source_name)
            _err(f"[scholar]   {fetcher.source_name:<20} {'✓' if count else '–'}  {count} papers")
            all_papers.extend(result)

    # Step 3: dedup
    _err(f"[scholar] deduplicating {len(all_papers)} papers...")
    unique = deduplicate(all_papers, exclude_ids=query.exclude_ids or None)
    _err(f"[scholar] deduplicating → {len(unique)} unique")

    # Step 4: layered evaluation and score
    target_category = target_publication_category(query)
    candidates, uncertain, heuristic_filtered = apply_metadata_heuristics(
        unique,
        target_category,
    )
    if heuristic_filtered:
        _err(
            f"[scholar] metadata heuristics filtered {heuristic_filtered} "
            f"{'review/survey' if target_category == 'primary' else 'primary'} papers"
        )
    if not candidates:
        candidates = []

    suffix = " (relevance via OpenAI)" if cfg.OPENAI_API_KEY else " (relevance defaulting to 0.5)"
    _err(f"[scholar] scoring {len(candidates)} papers{suffix}...")
    scored = await score_all(candidates, query.query, domain_categories)

    llm_targets = select_llm_candidates(scored, uncertain, query.top_n) if cfg.OPENAI_API_KEY else []
    if llm_targets:
        await LlmCategoricalJudge.evaluate_batch(llm_targets, query.query)
        llm_filtered_candidates, llm_filtered = filter_by_target_category(
            scored,
            target_category,
        )
        if llm_filtered:
            _err(
                f"[scholar] llm evaluation filtered {llm_filtered} "
                f"{'review/survey' if target_category == 'primary' else 'primary'} papers"
            )
        if llm_targets:
            _err(f"[scholar] llm evaluated {len(llm_targets)} papers")
        scored = await score_all(llm_filtered_candidates, query.query, domain_categories)

    # Step 5: rank and truncate
    not_found = False
    match_strategy = "ranked"
    if query.query_intent == "paper_lookup" or query.paper_titles:
        top_n, not_found, match_strategy = _rank_lookup_results(scored, query)
        if not_found and top_n:
            _err("[scholar] exact paper match not found; returning closest matches")
        all_papers_ranked = top_n
    else:
        # Store all scored candidates; top_n_count marks the display cutoff.
        # Download logic uses the full list so it can keep trying past rank top_n.
        all_papers_ranked = sorted(scored, key=lambda p: p.scores.composite, reverse=True)

    return RunResult(
        query=query.query,
        domain_category=domain_categories,
        params=query,
        timestamp=datetime.now(timezone.utc),
        sources_used=sources_used,
        sources_failed=sources_failed,
        papers=all_papers_ranked,
        top_n_count=query.top_n,
        not_found=not_found,
        match_strategy=match_strategy,
    )
