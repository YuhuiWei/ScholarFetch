from __future__ import annotations
import math
from datetime import datetime
from typing import Optional

RECENCY_LAMBDA: dict[str, float] = {
    "cs_ml": 0.30,
    "biology": 0.15,
    "chemistry": 0.18,
    "general": 0.20,
}
DEFAULT_SCORE: float = 0.3


class RecencyScorer:
    @staticmethod
    def score(year: Optional[int], domain_category: str) -> float:
        if not year:
            return DEFAULT_SCORE
        age = max(0, datetime.utcnow().year - year)
        lam = RECENCY_LAMBDA.get(domain_category, 0.20)
        return round(math.exp(-lam * age), 4)
