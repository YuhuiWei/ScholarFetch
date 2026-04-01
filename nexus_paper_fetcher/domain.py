from __future__ import annotations
import logging
import re
from typing import Optional

from openai import AsyncOpenAI

from nexus_paper_fetcher import config

logger = logging.getLogger(__name__)

VALID_CATEGORIES = {"cs_ml", "biology", "chemistry", "general"}

_DOMAIN_PATTERNS: dict[str, str] = {
    "biology": (
        r"\b(bio|cell|gene|protein|sequencing|genome|rna|dna|organism|"
        r"molecular|bacterial|viral|tissue|neuronal|stem|immune|cancer|"
        r"single.cell|omics|transcriptom|proteom|metabolom|crispr|"
        r"genomic|epigenet|phenotyp)\b"
    ),
    "chemistry": (
        r"\b(chemi|synthesis|reaction|polymer|molecule|compound|"
        r"catalyst|organic|inorganic|spectroscop|crystallograph|"
        r"ligand|solvent|reagent)\b"
    ),
}


def _keyword_classify(query: str) -> str:
    q = query.lower()
    for domain, pattern in _DOMAIN_PATTERNS.items():
        if re.search(pattern, q):
            return domain
    return "cs_ml"


async def classify_domain(query: str, override: Optional[str] = None) -> str:
    if override:
        if override not in VALID_CATEGORIES:
            raise ValueError(
                f"Invalid domain category: {override!r}. Choose from {VALID_CATEGORIES}"
            )
        return override

    if config.OPENAI_API_KEY:
        try:
            client = AsyncOpenAI(api_key=config.OPENAI_API_KEY)
            response = await client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{
                    "role": "user",
                    "content": (
                        f"Classify this research query into exactly one of these categories: "
                        f"cs_ml, biology, chemistry, general.\n"
                        f"Query: {query}\n"
                        f"Respond with ONLY the category name, nothing else."
                    ),
                }],
                max_tokens=10,
                temperature=0,
            )
            result = response.choices[0].message.content.strip().lower()
            if result in VALID_CATEGORIES:
                return result
            logger.warning("OpenAI returned unexpected domain %r, falling back", result)
        except Exception as e:
            logger.warning("OpenAI domain classification failed: %s, using keyword fallback", e)

    return _keyword_classify(query)
