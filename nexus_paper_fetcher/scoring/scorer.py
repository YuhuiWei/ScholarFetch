from __future__ import annotations

from nexus_paper_fetcher.models import Paper, ScoreBreakdown
from nexus_paper_fetcher.scoring.citation import CitationScorer
from nexus_paper_fetcher.scoring.recency import RecencyScorer
from nexus_paper_fetcher.scoring.relevance import RelevanceScorer
from nexus_paper_fetcher.scoring.venue import VenueScorer

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


async def score_all(
    papers: list[Paper], query: str, domain_category: str
) -> list[Paper]:
    weights = DOMAIN_WEIGHTS.get(domain_category, DOMAIN_WEIGHTS["general"])
    max_citations = max((p.citation_count or 0 for p in papers), default=1)

    relevance_scores = await RelevanceScorer.score_batch(
        query, [p.abstract or "" for p in papers]
    )

    for paper, rel_score in zip(papers, relevance_scores):
        v = VenueScorer.score(paper.venue)
        c = CitationScorer.score(paper.citation_count, paper.year, max_citations)
        r = RecencyScorer.score(paper.year, domain_category)
        bonus = OPENREVIEW_BONUS.get(paper.openreview_tier or "", 0.0)

        composite = min(
            1.0,
            weights["venue"] * v
            + weights["citation"] * c
            + weights["recency"] * r
            + weights["relevance"] * rel_score
            + bonus,
        )

        paper.scores = ScoreBreakdown(
            venue=round(v, 4),
            citation=round(c, 4),
            recency=round(r, 4),
            relevance=rel_score,
            openreview_bonus=bonus,
            composite=round(composite, 4),
        )

    return papers
