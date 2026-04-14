from __future__ import annotations

import json
import logging
from typing import Iterable

from scholar_fetch import config
from scholar_fetch.models import Paper, SearchQuery

logger = logging.getLogger(__name__)

REVIEW_VENUE_PATTERNS = (
    "annual review of",
    "nature reviews",
    "trends in",
    "reviews",
)
REVIEW_TITLE_PATTERNS = (
    "review",
    "survey",
)
REVIEW_TYPE_TOKENS = (
    "review",
    "survey",
    "meta-analysis",
)


def target_publication_category(search_query: SearchQuery) -> str:
    categories = {category.lower() for category in search_query.publication_categories}
    if categories & {"review", "survey"}:
        return "review"
    return "primary"


def apply_metadata_heuristics(
    papers: list[Paper],
    target_category: str,
) -> tuple[list[Paper], list[Paper], int]:
    candidates: list[Paper] = []
    uncertain: list[Paper] = []
    filtered = 0

    for paper in papers:
        category = heuristic_category_for_paper(paper)
        paper.heuristic_category = category
        if category is None:
            candidates.append(paper)
            uncertain.append(paper)
            continue
        if category != target_category:
            filtered += 1
            continue
        candidates.append(paper)

    return candidates, uncertain, filtered


def heuristic_category_for_paper(paper: Paper) -> str | None:
    venue = (paper.venue or "").lower()
    if any(pattern in venue for pattern in REVIEW_VENUE_PATTERNS):
        return "review"

    title = (paper.title or "").lower()
    if any(token in title for token in REVIEW_TITLE_PATTERNS):
        return "review"

    votes = [publication_type_to_category(value) for value in paper.source_publication_types.values()]
    votes = [vote for vote in votes if vote is not None]
    if not votes and paper.publication_type:
        fallback_vote = publication_type_to_category(paper.publication_type)
        if fallback_vote:
            votes.append(fallback_vote)

    review_votes = sum(vote == "review" for vote in votes)
    primary_votes = sum(vote == "primary" for vote in votes)
    if review_votes >= 1 and primary_votes == 0:
        return "review"
    if primary_votes >= 1 and review_votes == 0:
        return "primary"
    return None


def publication_type_to_category(publication_type: str | None) -> str | None:
    normalized = str(publication_type or "").lower()
    if not normalized:
        return None
    if any(token in normalized for token in REVIEW_TYPE_TOKENS):
        return "review"
    return "primary"


def select_llm_candidates(
    papers: list[Paper],
    uncertain_papers: Iterable[Paper],
    top_n: int,
) -> list[Paper]:
    selected: dict[str, Paper] = {
        paper.paper_id: paper for paper in uncertain_papers
    }
    top_k = max(top_n * 2, 10)
    ranked = sorted(papers, key=lambda paper: paper.scores.composite, reverse=True)[:top_k]
    for paper in ranked:
        selected.setdefault(paper.paper_id, paper)
    return list(selected.values())


def filter_by_target_category(
    papers: list[Paper],
    target_category: str,
) -> tuple[list[Paper], int]:
    kept: list[Paper] = []
    filtered = 0
    for paper in papers:
        category = paper.llm_category or paper.heuristic_category
        if category is not None and category != target_category:
            filtered += 1
            continue
        kept.append(paper)
    return kept, filtered


class LlmCategoricalJudge:
    _client = None

    @classmethod
    def _get_client(cls):
        if cls._client is None:
            from openai import AsyncOpenAI

            cls._client = AsyncOpenAI(api_key=config.OPENAI_API_KEY)
        return cls._client

    @classmethod
    async def evaluate_batch(cls, papers: list[Paper], research_query: str) -> None:
        if not papers or not config.OPENAI_API_KEY:
            return

        client = cls._get_client()
        for paper in papers:
            abstract = paper.abstract or ""
            prompt = (
                "Role: You are a senior research librarian.\n"
                "Task: Evaluate the following paper for two criteria.\n"
                "Category: Is this 'Primary Research' (presents new data/methods) "
                "or a 'Review/Survey' (summarizes existing work)?\n"
                f"Relevance: On a scale of 1-5, how closely does this abstract relate to {research_query!r}?\n"
                'Output Format: JSON {"category": "primary/review", "relevance_score": 1-5, "reasoning": "..."}\n\n'
                f"Title: {paper.title}\n"
                f"Abstract: {abstract}\n"
            )
            try:
                response = await client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0,
                    max_tokens=180,
                    response_format={"type": "json_object"},
                )
                data = json.loads(response.choices[0].message.content.strip())
                category = str(data.get("category") or "").strip().lower()
                paper.llm_category = "review" if category == "review" else "primary"
                raw_relevance = int(data.get("relevance_score") or 3)
                paper.llm_relevance_score = max(1, min(5, raw_relevance))
                paper.evaluation_reasoning = data.get("reasoning")
            except Exception as exc:
                logger.warning("LLM categorical evaluation failed for %s: %s", paper.title, exc)
