from __future__ import annotations
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from rapidfuzz import fuzz

from scholar_fetch.models import Paper, RunResult


@dataclass
class SearchHit:
    paper: Paper
    score: float          # match score 0–100
    source_file: Path     # JSON file this paper came from
    rank: int             # original rank in that result


def _match_score(paper: Paper, query: str) -> float:
    if not query:
        return 100.0
    q = query.lower()
    candidates = [
        paper.title or "",
        paper.abstract or "",
        " ".join(paper.authors),
        " ".join(paper.domain_tags),
    ]
    return max(fuzz.partial_ratio(q, c.lower()) for c in candidates if c)


def search_results(
    query: str,
    *,
    results_dir: Path = Path("results"),
    not_downloadable: bool = False,
    downloaded_only: bool = False,
    domain_slug: Optional[str] = None,
    min_score: float = 40.0,
) -> list[SearchHit]:
    """Search across saved result JSONs. Returns hits sorted by match score desc."""
    if domain_slug:
        search_dirs = [results_dir / domain_slug]
    else:
        search_dirs = [d for d in results_dir.iterdir() if d.is_dir()] if results_dir.exists() else []

    hits: list[SearchHit] = []
    for slug_dir in search_dirs:
        for json_file in sorted(slug_dir.glob("*.json"), reverse=True):
            try:
                run_result = RunResult.model_validate(json.loads(json_file.read_text()))
            except Exception:
                continue
            for rank, paper in enumerate(run_result.papers, 1):
                if not_downloadable and paper.download_status == "success":
                    continue
                if downloaded_only and paper.download_status != "success":
                    continue
                score = _match_score(paper, query)
                if score >= min_score or not query:
                    hits.append(SearchHit(paper=paper, score=score, source_file=json_file, rank=rank))

    hits.sort(key=lambda h: h.score, reverse=True)
    return hits
