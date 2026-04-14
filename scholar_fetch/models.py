from __future__ import annotations
import hashlib
from datetime import datetime, timezone
from typing import Literal, Optional, Union
from pydantic import BaseModel, Field, field_validator


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
    download_requested: bool = False
    download_top_n: Optional[int] = None
    query_slug: str = ""          # computed from query; drives results/<slug>/ directory
    expand_existing: bool = False  # when True, exclude already-found paper_ids
    exclude_ids: set[str] = Field(default_factory=set)

    def resolved_fetch_per_source(self) -> int:
        return self.fetch_per_source or max(self.top_n, 10)


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
    # Download tracking (populated by Phase 2)
    download_status: Optional[Literal["success", "failed", "not_attempted"]] = None
    download_file_path: Optional[str] = None  # absolute path to downloaded file
    # Keyword expansion tags (populated from NLP step)
    domain_tags: list[str] = Field(default_factory=list)

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
    domain_category: list[str]
    params: SearchQuery

    @field_validator("domain_category", mode="before")
    @classmethod
    def _coerce_domain_category(cls, v: Union[str, list]) -> list[str]:
        """Accept a bare string for backward compatibility with saved JSON files."""
        if isinstance(v, str):
            return [v]
        return v
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    sources_used: list[str]
    sources_failed: list[str] = Field(default_factory=list)
    papers: list[Paper]
    not_found: bool = False
    match_strategy: Optional[str] = None
    output_path: Optional[str] = None
    expanded_from: Optional[str] = None  # path to the result file this search expanded
    top_n_count: Optional[int] = None    # display/rank cutoff; papers list may contain more candidates
