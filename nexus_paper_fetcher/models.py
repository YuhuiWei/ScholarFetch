from __future__ import annotations
import hashlib
from datetime import datetime, timezone
from typing import Optional
from pydantic import BaseModel, Field


def _derive_paper_id(
    doi: Optional[str],
    arxiv_id: Optional[str],
    title: Optional[str],
    year: Optional[int],
) -> str:
    if doi:
        stable = doi.lower().strip()
    elif arxiv_id:
        stable = arxiv_id.lower().strip()
    else:
        stable = f"{(title or '').lower().strip()}_{year or 0}"
    return hashlib.sha256(stable.encode()).hexdigest()[:16]


class SearchQuery(BaseModel):
    query: str
    top_n: int = 20
    year_from: Optional[int] = None
    year_to: Optional[int] = None
    author: Optional[str] = None
    journal: Optional[str] = None
    fetch_per_source: int = 0  # 0 = auto: max(3*top_n, 100)
    keyword_count: Optional[int] = None
    paper_titles: list[str] = Field(default_factory=list)
    weight_preferences: list[str] = Field(default_factory=list)
    venue_preferences: list[str] = Field(default_factory=list)
    publication_categories: list[str] = Field(default_factory=list)
    keyword_logic: str = "AUTO"
    query_intent: str = "domain_search"
    search_scope: Optional[str] = None

    def resolved_fetch_per_source(self) -> int:
        return self.fetch_per_source or max(3 * self.top_n, 100)


class ScoreBreakdown(BaseModel):
    venue: float = 0.0
    citation: float = 0.0
    recency: float = 0.0
    relevance: float = 0.5
    llm_relevance: Optional[float] = None
    openreview_bonus: float = 0.0
    composite: float = 0.0


class Paper(BaseModel):
    paper_id: str
    title: str
    abstract: Optional[str] = None
    year: Optional[int] = None
    authors: list[str] = Field(default_factory=list)
    venue: Optional[str] = None
    doi: Optional[str] = None
    arxiv_id: Optional[str] = None
    semantic_scholar_id: Optional[str] = None
    openalex_id: Optional[str] = None
    open_access_pdf_url: Optional[str] = None
    openreview_tier: Optional[str] = None
    sources: list[str] = Field(default_factory=list)
    citation_count: Optional[int] = None
    publication_type: Optional[str] = None
    source_publication_types: dict[str, str] = Field(default_factory=dict)
    keywords: list[str] = Field(default_factory=list)
    methodology_category: Optional[str] = None
    heuristic_category: Optional[str] = None
    llm_category: Optional[str] = None
    llm_relevance_score: Optional[int] = None
    evaluation_reasoning: Optional[str] = None
    title_match_score: float = 0.0
    exact_match: bool = False
    scores: ScoreBreakdown = Field(default_factory=ScoreBreakdown)

    @classmethod
    def create(
        cls,
        *,
        title: str,
        doi: Optional[str] = None,
        arxiv_id: Optional[str] = None,
        year: Optional[int] = None,
        **kwargs,
    ) -> "Paper":
        paper_id = _derive_paper_id(doi, arxiv_id, title, year)
        return cls(paper_id=paper_id, title=title, doi=doi, arxiv_id=arxiv_id, year=year, **kwargs)


class RunResult(BaseModel):
    query: str
    domain_category: str
    params: SearchQuery
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    sources_used: list[str]
    sources_failed: list[str] = Field(default_factory=list)
    papers: list[Paper]
    not_found: bool = False
    match_strategy: Optional[str] = None
    output_path: Optional[str] = None
