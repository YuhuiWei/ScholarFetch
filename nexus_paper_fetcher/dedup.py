from __future__ import annotations
import re
from collections import defaultdict
from rapidfuzz import fuzz
from nexus_paper_fetcher.models import Paper, _derive_paper_id

FUZZY_THRESHOLD = 92


def _normalize_doi(doi: str) -> str:
    return (doi.lower()
               .removeprefix("https://doi.org/")
               .removeprefix("http://doi.org/")
               .strip())


def _normalize_title(title: str) -> str:
    t = title.lower().strip()
    t = re.sub(r"[^\w\s]", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    t = re.sub(r"^(a|an|the)\s+", "", t)
    return t


def _merge(papers: list[Paper]) -> Paper:
    if len(papers) == 1:
        return papers[0]
    base = papers[0].model_copy(deep=True)
    for other in papers[1:]:
        base.sources = list(set(base.sources + other.sources))
        base.doi = base.doi or other.doi
        base.arxiv_id = base.arxiv_id or other.arxiv_id
        base.semantic_scholar_id = base.semantic_scholar_id or other.semantic_scholar_id
        base.openalex_id = base.openalex_id or other.openalex_id
        base.open_access_pdf_url = base.open_access_pdf_url or other.open_access_pdf_url
        base.openreview_tier = base.openreview_tier or other.openreview_tier
        if other.source_publication_types:
            base.source_publication_types.update(other.source_publication_types)
        if not base.publication_type:
            base.publication_type = other.publication_type
        elif (
            other.publication_type
            and "review" in other.publication_type.lower()
            and "review" not in base.publication_type.lower()
        ):
            base.publication_type = other.publication_type
        base.citation_count = max(
            base.citation_count or 0, other.citation_count or 0
        ) or None
        if other.abstract and len(other.abstract) > len(base.abstract or ""):
            base.abstract = other.abstract
        other_score = sum([bool(other.authors), bool(other.venue), bool(other.year)])
        base_score = sum([bool(base.authors), bool(base.venue), bool(base.year)])
        if other_score > base_score:
            base.authors = other.authors or base.authors
            base.venue = other.venue or base.venue
            base.year = other.year or base.year
    base.paper_id = _derive_paper_id(base.doi, base.arxiv_id, base.title, base.year)
    return base


def deduplicate(papers: list[Paper], exclude_ids: set[str] | None = None) -> list[Paper]:
    if exclude_ids:
        papers = [p for p in papers if p.paper_id not in exclude_ids]
    # Pass 1: DOI exact match
    doi_buckets: dict[str, list[Paper]] = defaultdict(list)
    no_doi: list[Paper] = []
    for paper in papers:
        if paper.doi:
            doi_buckets[_normalize_doi(paper.doi)].append(paper)
        else:
            no_doi.append(paper)
    deduplicated = [_merge(group) for group in doi_buckets.values()]

    # Pass 2: Fuzzy title match on DOI-less papers
    clusters: list[list[Paper]] = []
    for paper in no_doi:
        placed = False
        for cluster in clusters:
            rep = _normalize_title(cluster[0].title)
            cand = _normalize_title(paper.title)
            if fuzz.token_sort_ratio(rep, cand) >= FUZZY_THRESHOLD:
                cluster.append(paper)
                placed = True
                break
        if not placed:
            clusters.append([paper])
    deduplicated += [_merge(cluster) for cluster in clusters]
    return deduplicated
