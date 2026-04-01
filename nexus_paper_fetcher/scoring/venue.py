from __future__ import annotations
import re
from pathlib import Path
from typing import Optional
import yaml
from rapidfuzz import fuzz, process


def _normalize_venue_name(name: str) -> str:
    name = name.lower()
    name = re.sub(r"[^\w\s]", "", name)
    return name.strip()


class VenueScorer:
    TIER_SCORES: dict[int, float] = {1: 1.0, 2: 0.75, 3: 0.5}
    DEFAULT_SCORE: float = 0.3
    FUZZY_THRESHOLD: int = 85

    _registry: list[dict] = []
    _normalized_names: list[str] = []
    _loaded: bool = False

    @classmethod
    def _load(cls) -> None:
        if cls._loaded:
            return
        user_override = Path.home() / ".config" / "nexus" / "venues.yaml"
        if user_override.exists():
            with open(user_override) as f:
                data = yaml.safe_load(f)
        else:
            data_path = Path(__file__).parent.parent / "data" / "venues.yaml"
            with open(data_path) as f:
                data = yaml.safe_load(f)
        cls._registry = [
            {
                "normalized_name": _normalize_venue_name(v["name"]),
                "tier": v["tier"],
                "domain": v.get("domain", "general"),
            }
            for v in data.get("venues", [])
        ]
        cls._normalized_names = [r["normalized_name"] for r in cls._registry]
        cls._loaded = True

    @classmethod
    def score(cls, venue: Optional[str]) -> float:
        if not venue:
            return cls.DEFAULT_SCORE
        cls._load()
        normalized = _normalize_venue_name(venue)
        result = process.extractOne(normalized, cls._normalized_names, scorer=fuzz.token_sort_ratio)
        if result is None:
            return cls.DEFAULT_SCORE
        _match, score, idx = result
        if score >= cls.FUZZY_THRESHOLD:
            return cls.TIER_SCORES.get(cls._registry[idx]["tier"], cls.DEFAULT_SCORE)
        return cls.DEFAULT_SCORE
