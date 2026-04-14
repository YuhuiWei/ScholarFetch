from __future__ import annotations
import logging
import re
from typing import Optional

from openai import AsyncOpenAI

from scholar_fetch import config

logger = logging.getLogger(__name__)

VALID_CATEGORIES = {"cs_ml", "biology", "chemistry", "general"}

_DOMAIN_PATTERNS: dict[str, str] = {
    # Match on full words AND common stem prefixes that appear as standalone tokens.
    # Note: trailing \b means the pattern only fires when the matched text is at a
    # word boundary — so stems like "pharmacol" won't fire on "pharmacology".
    # We therefore list full words (biology, pharmacology, …) alongside stems.
    "biology": (
        r"\b(bio(?:logy|medical|informatics)?|cell|gene|protein|sequencing|"
        r"genome|rna|dna|organism|molecular|bacterial|viral|tissue|neuronal|"
        r"stem|immune|cancer|single.cell|omics|transcriptom(?:e|ics)?|"
        r"proteom(?:e|ics)?|metabolom(?:e|ics)?|crispr|genomic|epigenetic|"
        r"phenotyp(?:e|ic)?|medical|clinical|pharmacolog(?:y|ical)?|"
        r"drug|patient|disease|therapeutic|biomedical|"
        r"neuroscien(?:ce)?|health)\b"
    ),
    "chemistry": (
        r"\b(chemi(?:stry|cal)?|synthesis|reaction|polymer|molecule|compound|"
        r"catalyst|organic|inorganic|spectroscop(?:y|ic)?|crystallograph(?:y|ic)?|"
        r"ligand|solvent|reagent)\b"
    ),
    "cs_ml": (
        r"\b(machine.learning|deep.learning|neural.networks?|transformers?|"
        r"language.models?|large.language|llm|bert|gpt|computer.vision|"
        r"vision.language|multimodal|multi.modal|representation.learning|"
        r"self.supervised|contrastive.learning|encoders?|embeddings?|"
        r"reinforcement.learning|natural.language.process|diffusion.model|"
        r"cs.domain|computer.science|artificial.intelligence|foundation.model|"
        r"graph.neural|attention.mechanism|convolutional|object.detection|"
        r"image.classification|semantic.segmentation|generative.model)\b"
    ),
}


def _keyword_classify(query: str) -> list[str]:
    """Return all domains with keyword matches. Returns [] when nothing matches (no default)."""
    q = query.lower()
    return [domain for domain, pattern in _DOMAIN_PATTERNS.items()
            if re.search(pattern, q)]


def _parse_domain_response(raw: str) -> list[str]:
    """Parse a comma-separated domain response into a validated list."""
    parts = [p.strip().lower() for p in re.split(r"[,\s]+", raw) if p.strip()]
    valid = [p for p in parts if p in VALID_CATEGORIES]
    return valid or []


async def classify_domain(
    query: str,
    override: Optional[str] = None,
) -> list[str]:
    """Return one or more domain categories for the query.

    ``override`` may be a single category (``"cs_ml"``) or a comma-separated
    list (``"cs_ml,biology"``).  When set, it is validated and returned directly
    without calling the LLM.
    """
    if override:
        parts = _parse_domain_response(override)
        if not parts:
            raise ValueError(
                f"Invalid domain category: {override!r}. Choose from {VALID_CATEGORIES}"
            )
        invalid = [p for p in re.split(r"[,\s]+", override.lower()) if p.strip() and p not in VALID_CATEGORIES]
        if invalid:
            raise ValueError(
                f"Invalid domain categories: {invalid!r}. Choose from {VALID_CATEGORIES}"
            )
        return parts

    # Step 1: keyword-matched domains (genuine matches only, no default fallback)
    keyword_cats = _keyword_classify(query)

    if config.OPENAI_API_KEY:
        try:
            client = AsyncOpenAI(api_key=config.OPENAI_API_KEY)
            response = await client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{
                    "role": "user",
                    "content": (
                        f"Classify this research query by domain. List ALL applicable domains.\n"
                        f"Categories:\n"
                        f"  cs_ml    — involves ML/AI/CS methods (neural networks, transformers, "
                        f"representation learning, computer vision, NLP, etc.), regardless of application area\n"
                        f"  biology  — targets biological/biomedical/clinical/neuroscience questions\n"
                        f"  chemistry — targets chemistry questions\n"
                        f"  general  — clearly interdisciplinary without a dominant domain\n"
                        f"Rules:\n"
                        f"  - If the query uses any ML/AI/CS method, include cs_ml\n"
                        f"  - If the query targets biological/medical applications, include biology\n"
                        f"  - List multiple domains when both apply (e.g., cs_ml,biology)\n"
                        f"Query: {query}\n"
                        f"Respond with ONLY the category name(s), comma-separated, e.g.: cs_ml,biology"
                    ),
                }],
                max_tokens=20,
                temperature=0,
            )
            raw = response.choices[0].message.content.strip().lower()
            llm_cats = _parse_domain_response(raw)
            if llm_cats:
                # Merge: union of LLM result and keyword-genuine-matches, preserving LLM order
                merged = list(dict.fromkeys(llm_cats + keyword_cats))
                return merged
            logger.warning("OpenAI returned unexpected domain %r, falling back", raw)
        except Exception as e:
            logger.warning("OpenAI domain classification failed: %s, using keyword fallback", e)

    # Final fallback: keyword matches, defaulting to cs_ml when nothing matches
    return keyword_cats or ["cs_ml"]
