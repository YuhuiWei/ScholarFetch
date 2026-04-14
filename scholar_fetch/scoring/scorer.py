from __future__ import annotations

from scholar_fetch.models import Paper, ScoreBreakdown
from scholar_fetch.scoring.citation import CitationScorer
from scholar_fetch.scoring.recency import RecencyScorer
from scholar_fetch.scoring.relevance import RelevanceScorer
from scholar_fetch.scoring.venue import VenueScorer

DOMAIN_WEIGHTS: dict[str, dict[str, float]] = {
    "cs_ml":     {"venue": 0.20, "citation": 0.15, "recency": 0.30, "relevance": 0.35},
    "biology":   {"venue": 0.30, "citation": 0.35, "recency": 0.15, "relevance": 0.20},
    "chemistry": {"venue": 0.25, "citation": 0.35, "recency": 0.15, "relevance": 0.25},
    "general":   {"venue": 0.20, "citation": 0.25, "recency": 0.25, "relevance": 0.30},
}

OPENREVIEW_BONUS: dict[str, float] = {
    "oral": 0.15,
    "spotlight": 0.08,
    "poster": 0.0,
}


def _blend_weights(domain_categories: list[str]) -> dict[str, float]:
    """Average scoring weights across all applicable domains."""
    if len(domain_categories) == 1:
        return DOMAIN_WEIGHTS.get(domain_categories[0], DOMAIN_WEIGHTS["general"])
    weight_dicts = [DOMAIN_WEIGHTS.get(d, DOMAIN_WEIGHTS["general"]) for d in domain_categories]
    keys = DOMAIN_WEIGHTS["general"].keys()
    return {k: round(sum(w[k] for w in weight_dicts) / len(weight_dicts), 4) for k in keys}


def _recency_score(year, domain_categories: list[str]) -> float:
    """Average recency score across all applicable domains."""
    if len(domain_categories) == 1:
        return RecencyScorer.score(year, domain_categories[0])
    scores = [RecencyScorer.score(year, d) for d in domain_categories]
    return round(sum(scores) / len(scores), 4)


async def score_all(
    papers: list[Paper], query: str, domain_categories: list[str]
) -> list[Paper]:
    weights = _blend_weights(domain_categories)
    max_citations = max((p.citation_count or 0 for p in papers), default=1)

    relevance_scores = await RelevanceScorer.score_batch(
        query, [p.abstract or "" for p in papers]
    )

    for paper, rel_score in zip(papers, relevance_scores):
        v = VenueScorer.score(paper.venue)
        c = CitationScorer.score(paper.citation_count, paper.year, max_citations)
        r = _recency_score(paper.year, domain_categories)
        bonus = OPENREVIEW_BONUS.get(paper.openreview_tier or "", 0.0)
        llm_relevance = None
        effective_relevance = rel_score
        if paper.llm_relevance_score is not None:
            llm_relevance = round(
                max(0.0, min(1.0, (paper.llm_relevance_score - 1) / 4)),
                4,
            )
            effective_relevance = round((rel_score + llm_relevance) / 2, 4)

        composite = min(
            1.0,
            weights["venue"] * v
            + weights["citation"] * c
            + weights["recency"] * r
            + weights["relevance"] * effective_relevance
            + bonus,
        )

        paper.scores = ScoreBreakdown(
            venue=round(v, 4),
            citation=round(c, 4),
            recency=round(r, 4),
            relevance=rel_score,
            llm_relevance=llm_relevance,
            openreview_bonus=bonus,
            composite=round(composite, 4),
        )

    return papers
