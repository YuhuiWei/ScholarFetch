from __future__ import annotations
import json
import logging
import re
import sys
from typing import Optional

from nexus_paper_fetcher import config
from nexus_paper_fetcher.models import SearchQuery

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """\
You are a research paper search assistant. Parse the user's natural language request \
into structured search parameters.

Return a JSON object with these fields (all optional except query):
  query          string   — core search terms, concise keywords (required)
  top_n          integer  — number of papers to return (default: 20)
  year_from      integer  — earliest publication year, or null
  year_to        integer  — latest publication year, or null
  author         string   — specific author name, or null
  domain_category string  — one of: cs_ml, biology, chemistry, general, or null
  query_intent   string   — one of: paper_lookup, domain_search
  keyword_count  integer  — number of expansion keywords to add; use 0 for no expansion,
                            3 for "less", 8 for "more", null when unspecified
  paper_titles   array[string] — specific paper titles when the user is asking for named papers
  weight_preferences array[string] — any of: citation, relevance, venue, recency, high_impact
  venue_preferences array[string] — venue/journal requests or venue groups such as
                                    "top tier cs conference", "cv conference",
                                    "neuroscience journal", "CNS"
  publication_categories array[string] — paper categories such as primary_research, review,
                                         methods, data, perspective, comment
  keyword_logic string — AND or OR when the user explicitly describes boolean keyword relations

Examples:
  "papers on attention mechanisms after 2020"
  → {"query": "attention mechanisms", "year_from": 2020}

  "top 50 CRISPR gene editing papers"
  → {"query": "CRISPR gene editing", "top_n": 50, "domain_category": "biology"}

  "recent transformers survey, last 3 years"
  → {"query": "transformer survey", "year_from": 2022}

  "Yann LeCun convolutional networks"
  → {"query": "convolutional networks", "author": "LeCun, Y."}

  "transformer papers, less keyword expansion"
  → {"query": "transformer papers", "keyword_count": 3}

  "top 10 transformer papers, no keyword expansion"
  → {"query": "transformer papers", "top_n": 10, "keyword_count": 0}

  "diffusion models with 7 expansion keywords"
  → {"query": "diffusion models", "keyword_count": 7}

  "find the papers Attention Is All You Need and BERT"
  → {"query": "Attention Is All You Need BERT", "query_intent": "paper_lookup", "paper_titles": ["Attention Is All You Need", "BERT: Pre-training of Deep Bidirectional Transformers for Language Understanding"]}

  "show more cited transformer papers from top tier CS conferences"
  → {"query": "transformer papers", "weight_preferences": ["citation"], "venue_preferences": ["top tier cs conference"]}

  "find 10 best paper from NeurIPS"
  → {"query": "NeurIPS", "top_n": 10, "weight_preferences": ["citation", "high_impact"], "venue_preferences": ["NeurIPS"]}

  "find 10 best paper from Nature"
  → {"query": "Nature", "top_n": 10, "weight_preferences": ["citation", "high_impact"], "venue_preferences": ["Nature"]}

  "review papers OR methods papers on single-cell RNA"
  → {"query": "single-cell RNA", "keyword_logic": "OR", "publication_categories": ["review", "methods"]}

Return ONLY valid JSON, nothing else."""


def _fallback_keyword_count(text: str) -> Optional[int]:
    lowered = text.lower()
    if "no keyword expansion" in lowered or "no expansion" in lowered:
        return 0
    if "less keyword" in lowered or "fewer keyword" in lowered:
        return 3
    if "more keyword" in lowered:
        return 8

    match = re.search(r"\b(\d+)\s+(?:expanded?\s+)?keywords?\b", lowered)
    if match:
        return int(match.group(1))
    return None


def _fallback_top_n(text: str, default_top_n: int) -> int:
    lowered = text.lower()
    match = re.search(r"\b(?:top|find|show|list|return)\s+(\d+)\b", lowered)
    if match:
        return int(match.group(1))
    return default_top_n


def _fallback_paper_titles(text: str) -> list[str]:
    return [match.strip() for match in re.findall(r'"([^"]+)"', text) if match.strip()]


def _fallback_query_intent(text: str, paper_titles: list[str]) -> str:
    lowered = text.lower()
    if paper_titles:
        return "paper_lookup"
    singular_lookup_patterns = (
        "find the paper ",
        "find paper ",
        "look up the paper ",
        "paper titled ",
        "paper called ",
        "publication titled ",
    )
    if any(pattern in lowered for pattern in singular_lookup_patterns):
        return "paper_lookup"
    return "domain_search"


def _fallback_weight_preferences(text: str) -> list[str]:
    lowered = text.lower()
    preferences: list[str] = []
    if any(token in lowered for token in [" top ", " best ", "most influential", "landmark", "seminal"]):
        preferences.extend(["citation", "high_impact"])
    if "more cited" in lowered or "highly cited" in lowered:
        preferences.append("citation")
    if "more relevant" in lowered or "more relevent" in lowered:
        preferences.append("relevance")
    if "high impact" in lowered:
        preferences.append("high_impact")
    if "more recent" in lowered or "newer" in lowered:
        preferences.append("recency")
    return list(dict.fromkeys(preferences))


def _fallback_venue_preferences(text: str) -> list[str]:
    lowered = text.lower()
    preferences: list[str] = []
    for phrase in [
        "top tier cs conference",
        "cv conference",
        "cns",
        "neuroscience journal",
    ]:
        if phrase in lowered:
            preferences.append(phrase)

    exact_patterns = {
        "NeurIPS": r"\b(?:neurips|nips)\b",
        "ICML": r"\bicml\b",
        "ICLR": r"\biclr\b",
        "CVPR": r"\bcvpr\b",
        "ICCV": r"\biccv\b",
        "ECCV": r"\beccv\b",
        "Nature": r"\bnature\b",
        "Science": r"\bscience\b",
        "Cell": r"\bcell\b",
    }
    for venue, pattern in exact_patterns.items():
        if re.search(pattern, lowered):
            preferences.append(venue)
    return preferences


def _fallback_publication_categories(text: str) -> list[str]:
    lowered = text.lower()
    categories: list[str] = []
    mapping = {
        "review": ["review paper", "review papers", "survey", "surveys"],
        "methods": ["method paper", "methods paper", "methods papers", "method presenting"],
        "data": ["data paper", "data papers", "dataset paper", "data presenting"],
        "perspective": ["perspective", "perspective paper"],
        "comment": ["comment paper", "commentary", "editorial", "letter"],
        "primary_research": ["research paper", "research papers", "primary research"],
    }
    for category, phrases in mapping.items():
        if any(phrase in lowered for phrase in phrases):
            categories.append(category)
    return categories or ["primary_research"]


def _fallback_keyword_logic(text: str) -> str:
    lowered = text.lower()
    if " or " in lowered:
        return "OR"
    if " and " in lowered:
        return "AND"
    return "AUTO"


async def prepare_query(
    search_query: SearchQuery,
    domain_category_override: Optional[str] = None,
) -> tuple:
    """Placeholder for future keyword expansion and domain detection logic."""
    return (
        domain_category_override,
        [],
        search_query.query,
        "passthrough",
        [domain_category_override] if domain_category_override else [],
        search_query.query,
        [],
        [],
    )


async def parse_natural_language_query(
    text: str,
    default_top_n: int = 20,
) -> tuple[SearchQuery, Optional[str]]:
    """Parse natural language into (SearchQuery, domain_category_override).

    Returns a plain SearchQuery(query=text) if OPENAI_API_KEY is not set,
    printing a one-time hint to stderr.
    """
    if not config.OPENAI_API_KEY:
        print(
            "[nexus] OPENAI_API_KEY not set — treating input as raw query string.\n"
            "[nexus]   NLP parsing disabled. To enable natural language input:\n"
            "[nexus]   add 'export OPENAI_API_KEY=sk-...' to ~/.bashrc, then run: source ~/.bashrc",
            file=sys.stderr,
        )
        return (
            SearchQuery(
                query=text,
                top_n=_fallback_top_n(text, default_top_n),
                keyword_count=_fallback_keyword_count(text),
                paper_titles=(paper_titles := _fallback_paper_titles(text)),
                weight_preferences=_fallback_weight_preferences(text),
                venue_preferences=_fallback_venue_preferences(text),
                publication_categories=_fallback_publication_categories(text),
                keyword_logic=_fallback_keyword_logic(text),
                query_intent=_fallback_query_intent(text, paper_titles),
            ),
            None,
        )

    try:
        from openai import AsyncOpenAI
        client = AsyncOpenAI(api_key=config.OPENAI_API_KEY)
        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": text},
            ],
            max_tokens=200,
            temperature=0,
            response_format={"type": "json_object"},
        )
        data = json.loads(response.choices[0].message.content.strip())

        sq = SearchQuery(
            query=data.get("query") or text,
            top_n=int(data["top_n"]) if data.get("top_n") else default_top_n,
            year_from=data.get("year_from"),
            year_to=data.get("year_to"),
            author=data.get("author"),
            keyword_count=(
                int(data["keyword_count"])
                if data.get("keyword_count") is not None
                else None
            ),
            paper_titles=(paper_titles := (data.get("paper_titles") or [])),
            weight_preferences=data.get("weight_preferences") or [],
            venue_preferences=data.get("venue_preferences") or [],
            publication_categories=data.get("publication_categories") or ["primary_research"],
            keyword_logic=(data.get("keyword_logic") or "AUTO").upper(),
            query_intent=(
                data.get("query_intent")
                or _fallback_query_intent(text, paper_titles)
            ),
        )
        domain = data.get("domain_category") or None
        return sq, domain

    except Exception as e:
        logger.warning("NLP parsing failed (%s) — falling back to raw query", e)
        return (
            SearchQuery(
                query=text,
                top_n=_fallback_top_n(text, default_top_n),
                keyword_count=_fallback_keyword_count(text),
                paper_titles=(paper_titles := _fallback_paper_titles(text)),
                weight_preferences=_fallback_weight_preferences(text),
                venue_preferences=_fallback_venue_preferences(text),
                publication_categories=_fallback_publication_categories(text),
                keyword_logic=_fallback_keyword_logic(text),
                query_intent=_fallback_query_intent(text, paper_titles),
            ),
            None,
        )
