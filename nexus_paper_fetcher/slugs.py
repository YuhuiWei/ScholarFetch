from __future__ import annotations
import re

_MAX_SLUG_LEN = 60


def make_query_slug(query: str) -> str:
    """Derive a filesystem-safe slug from a search query.

    Example: "single-cell RNA sequencing" -> "single-cell-rna-sequencing"
    """
    slug = query.lower().strip()
    slug = re.sub(r"[^a-z0-9\s-]", "", slug)   # strip non-alphanumeric (keep hyphens)
    slug = re.sub(r"[\s-]+", "-", slug)           # collapse whitespace/hyphens
    slug = slug.strip("-")
    return slug[:_MAX_SLUG_LEN].rstrip("-")
