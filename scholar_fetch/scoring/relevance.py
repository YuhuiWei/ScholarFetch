from __future__ import annotations
import logging
from typing import Optional

import numpy as np

from scholar_fetch import config

logger = logging.getLogger(__name__)

DEFAULT_SCORE: float = 0.5
MODEL: str = "text-embedding-3-small"
MAX_INPUTS_PER_REQUEST: int = 300
MAX_ESTIMATED_TOKENS_PER_REQUEST: int = 300_000


def _estimate_tokens(text: str) -> int:
    if not text:
        return 0
    return max(1, len(text) // 4)


def _chunk_abstracts(query: str, abstracts: list[str]) -> list[list[str]]:
    query_tokens = _estimate_tokens(query)
    chunks: list[list[str]] = []
    current_chunk: list[str] = []
    current_tokens = query_tokens

    for abstract in abstracts:
        text = abstract if abstract.strip() else query
        estimated_tokens = _estimate_tokens(text)
        would_exceed_count = len(current_chunk) >= MAX_INPUTS_PER_REQUEST
        would_exceed_tokens = current_chunk and (
            current_tokens + estimated_tokens > MAX_ESTIMATED_TOKENS_PER_REQUEST
        )
        if would_exceed_count or would_exceed_tokens:
            chunks.append(current_chunk)
            current_chunk = []
            current_tokens = query_tokens

        current_chunk.append(abstract)
        current_tokens += estimated_tokens

    if current_chunk:
        chunks.append(current_chunk)

    return chunks


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

        client = cls._get_client()
        scores: list[float] = []
        for abstract_chunk in _chunk_abstracts(query, abstracts):
            texts = [query] + [a if a.strip() else query for a in abstract_chunk]
            response = await client.embeddings.create(model=MODEL, input=texts)
            embeddings = [e.embedding for e in response.data]

            query_emb = embeddings[0]
            for i, abstract in enumerate(abstract_chunk):
                if not abstract.strip():
                    scores.append(DEFAULT_SCORE)
                else:
                    raw = _cosine(query_emb, embeddings[i + 1])
                    scores.append(round(max(0.0, raw), 4))
        return scores
