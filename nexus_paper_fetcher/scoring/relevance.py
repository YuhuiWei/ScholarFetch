from __future__ import annotations
import logging
from typing import Optional

import numpy as np

from nexus_paper_fetcher import config

logger = logging.getLogger(__name__)

DEFAULT_SCORE: float = 0.5
MODEL: str = "text-embedding-3-small"


def _cosine(a: list[float], b: list[float]) -> float:
    va, vb = np.array(a), np.array(b)
    denom = float(np.linalg.norm(va) * np.linalg.norm(vb))
    if denom == 0.0:
        return 0.0
    return float(np.dot(va, vb) / denom)


class RelevanceScorer:
    _client = None  # AsyncOpenAI instance — set lazily or replaced in tests

    @classmethod
    def _get_client(cls):
        if cls._client is None:
            from openai import AsyncOpenAI
            cls._client = AsyncOpenAI(api_key=config.OPENAI_API_KEY)
        return cls._client

    @classmethod
    async def score_batch(cls, query: str, abstracts: list[str]) -> list[float]:
        if not config.OPENAI_API_KEY:
            return [DEFAULT_SCORE] * len(abstracts)

        # Replace empty abstracts with the query itself so we don't embed empty strings
        texts = [query] + [a if a.strip() else query for a in abstracts]
        client = cls._get_client()
        response = await client.embeddings.create(model=MODEL, input=texts)
        embeddings = [e.embedding for e in response.data]

        query_emb = embeddings[0]
        scores: list[float] = []
        for i, abstract in enumerate(abstracts):
            if not abstract.strip():
                scores.append(DEFAULT_SCORE)
            else:
                raw = _cosine(query_emb, embeddings[i + 1])
                scores.append(round(max(0.0, raw), 4))
        return scores
