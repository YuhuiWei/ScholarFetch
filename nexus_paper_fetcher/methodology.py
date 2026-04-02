from __future__ import annotations

import json
import logging
from typing import Iterable

from openai import AsyncOpenAI

from nexus_paper_fetcher import config
from nexus_paper_fetcher.models import Paper

logger = logging.getLogger(__name__)

VALID_METHODOLOGY_CATEGORIES = {"research", "review", "data", "method"}
_CATEGORY_CODES = {
    "R": "research",
    "V": "review",
    "D": "data",
    "M": "method",
}
_MAX_ABSTRACT_CHARS = 600
_BATCH_SIZE = 12


def heuristic_methodology_category(paper: Paper) -> str:
    publication_type = (paper.publication_type or "").lower()
    text = " ".join(
        [
            paper.title.lower(),
            (paper.abstract or "").lower(),
            " ".join(keyword.lower() for keyword in paper.keywords),
        ]
    )

    if "review" in publication_type or any(token in text for token in ["systematic review", "survey", "review of"]):
        return "review"
    if any(token in text for token in ["dataset", "database", "benchmark dataset", "corpus", "atlas", "resource"]):
        return "data"
    if any(token in text for token in ["protocol", "pipeline", "method", "methods", "algorithm", "toolkit", "framework"]):
        return "method"
    return "research"


def _chunk(items: list[Paper], size: int) -> Iterable[list[Paper]]:
    for index in range(0, len(items), size):
        yield items[index:index + size]


def _normalize_categories(payload: object, size: int) -> list[str]:
    if not isinstance(payload, list):
        return []
    categories: list[str] = []
    for item in payload[:size]:
        if not isinstance(item, str):
            categories.append("research")
            continue
        normalized = item.strip().lower()
        if len(normalized) == 1:
            categories.append(_CATEGORY_CODES.get(normalized.upper(), "research"))
        else:
            categories.append(normalized if normalized in VALID_METHODOLOGY_CATEGORIES else "research")
    while len(categories) < size:
        categories.append("research")
    return categories


async def classify_methodology(papers: list[Paper]) -> None:
    if not papers:
        return

    if not config.OPENAI_API_KEY:
        for paper in papers:
            paper.methodology_category = heuristic_methodology_category(paper)
        return

    client = AsyncOpenAI(api_key=config.OPENAI_API_KEY)
    for batch in _chunk(papers, _BATCH_SIZE):
        try:
            payload = [
                {
                    "index": index,
                    "title": paper.title[:220],
                    "abstract": (paper.abstract or "")[:_MAX_ABSTRACT_CHARS],
                }
                for index, paper in enumerate(batch)
            ]
            response = await client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "Classify each paper into exactly one category code using title and abstract only. "
                            "Codes: R=Research, V=Review, D=Data, M=Method. "
                            "Return compact JSON with one field 'categories' containing only the ordered code list. "
                            "Do not repeat titles, abstracts, indices, or explanations."
                        ),
                    },
                    {
                        "role": "user",
                        "content": json.dumps(payload),
                    },
                ],
                max_tokens=120,
                temperature=0,
                response_format={"type": "json_object"},
            )
            data = json.loads(response.choices[0].message.content.strip())
            categories = _normalize_categories(data.get("categories"), len(batch))
            for paper, category in zip(batch, categories):
                paper.methodology_category = category
        except Exception as exc:
            logger.warning("Methodology classification failed: %s; using heuristic fallback", exc)
            for paper in batch:
                paper.methodology_category = heuristic_methodology_category(paper)
