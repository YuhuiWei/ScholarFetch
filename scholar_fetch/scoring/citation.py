from __future__ import annotations
import math
from datetime import datetime
from typing import Optional


class CitationScorer:
    @staticmethod
    def score(
        citation_count: Optional[int], year: Optional[int], max_citations: int
    ) -> float:
        if not citation_count or max_citations == 0:
            return 0.0
        log_score = math.log1p(citation_count) / math.log1p(max_citations)
        current_year = datetime.utcnow().year
        age_years = current_year - (year or current_year)
        age_factor = min(1.0, (age_years + 1) / 3)
        return round(log_score * age_factor, 4)
