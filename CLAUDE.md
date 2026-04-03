# Nexus Paper Fetcher — Claude Code Context

## What This Is
Phases 1-2 of a 4-phase pipeline. Phase 1 fetches and ranks papers from OpenAlex, Semantic Scholar,
and OpenReview. Phase 2 downloads full-text files (PDFs and Elsevier XML fallback) and writes `manifest.json`.
Output feeds MAC research assistant (Phase 4).

## Setup
```bash
cd nexus-paper-fetcher
pip install -e ".[dev]"
export OPENAI_API_KEY=...     # optional — enables relevance scoring + domain classification
export S2_API_KEY=...          # optional — higher S2 rate limits
export NEXUS_EMAIL=you@x.com  # for OpenAlex polite pool
export NEXUS_DOWNLOAD_DIR=/path/to/papers  # preferred output dir for downloaded files
export NEXUS_PDF_DIR=/path/to/papers       # legacy fallback output dir
export NEXUS_UNPAYWALL_EMAIL=you@x.com     # optional Unpaywall email override
export ELSEVIER_API_KEY=...                # required for Elsevier subscription XML fallback
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
- Phase 2 download order: saved `open_access_pdf_url` -> OpenAlex `openalex_id` recovery -> DOI arXiv -> DOI Unpaywall -> DOI Elsevier XML
- Elsevier XML fallback runs only for `10.1016/...` DOIs and requires `ELSEVIER_API_KEY`
- Successful Elsevier fallback saves `.xml` files with `source_used: "elsevier_api"`
- Output directory may contain mixed `.pdf` and `.xml` files
