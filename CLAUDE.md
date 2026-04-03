# Nexus Paper Fetcher — Claude Code Context

## What This Is
Phase 1 of a 4-phase pipeline. Fetches and ranks papers from OpenAlex, Semantic Scholar,
OpenReview. Output feeds MAC research assistant (Phase 4).

## Setup
```bash
cd nexus-paper-fetcher
pip install -e ".[dev]"
export OPENAI_API_KEY=...     # optional — enables relevance scoring + domain classification
export S2_API_KEY=...          # optional — higher S2 rate limits
export NEXUS_EMAIL=you@x.com  # for OpenAlex polite pool
```

## Run Tests
```bash
pytest                          # all unit tests
pytest tests/test_dedup.py -v  # single file
pytest -m integration           # real API tests (opt-in, requires keys)
```

## CLI
```bash
nexus fetch "single-cell RNA sequencing" --top-n 20
nexus fetch "attention mechanisms" --top-n 50 --domain-category cs_ml --year-from 2020
```

## Key Design Decisions (see full spec in docs/superpowers/specs/)
- paper_id = sha256[:16] of DOI > arxiv_id > hash(title+year) — stable cross-phase FK
- Dedup: exact DOI → fuzzy title (rapidfuzz token_sort_ratio, threshold 92)
- OpenReview only queried when domain_category == cs_ml
- RelevanceScorer defaults to 0.5 when OPENAI_API_KEY unset
- All fetchers return [] on failure, never raise
- Output: envelope JSON {run: {...}, papers: [...]} in results/
- Phase 2 PDF order: saved `open_access_pdf_url` -> OpenAlex `openalex_id` recovery -> DOI arXiv -> DOI Unpaywall
