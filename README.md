# nexus-paper-fetcher

Ranked academic paper search and full-text download pipeline for the NEXUS multi-agent research platform. Fetches candidates from OpenAlex, Semantic Scholar, and OpenReview, deduplicates and scores them, then downloads full-text files for downstream extraction.

---

## Pipeline Overview

```
Phase 1: nexus fetch  →  ranked JSON  (OpenAlex + S2 + OpenReview)
Phase 2: nexus download  →  downloaded files + manifest.json
Phase 3: (coming) parse downloaded files, extract knowledge via OpenAI
Phase 4: (coming) generate NEXUS agent skills
```

---

## Setup

```bash
cd nexus-paper-fetcher
pip install -e ".[dev]"

# Optional — enables NLP query parsing, relevance scoring, methodology classification
export OPENAI_API_KEY=sk-...

# Optional — higher Semantic Scholar rate limits
export S2_API_KEY=...

# For OpenAlex polite pool
export NEXUS_EMAIL=you@institution.edu

# Preferred default output directory for downloaded files
export NEXUS_DOWNLOAD_DIR=/path/to/papers

# Legacy fallback (still supported)
export NEXUS_PDF_DIR=/path/to/papers
```

---

## Phase 1: Paper Screening

Fetch and rank papers from multiple academic sources.

```bash
# Basic search
nexus fetch "single-cell RNA sequencing" --top-n 20

# With filters
nexus fetch "attention mechanisms" --top-n 50 --domain-category cs_ml --year-from 2020

# Limit to a specific author
nexus fetch "graph neural networks" --author "Kipf, T." --top-n 10

# Disable keyword expansion
nexus fetch "CRISPR base editing" --no-keyword-expansion

# Control expansion keyword count
nexus fetch "diffusion models" --keyword-count 7

# Save to a specific path
nexus fetch "transformer architectures" --output results/transformers.json
```

**Output:** JSON file in `results/` containing ranked papers with scores, metadata, and source URLs.

### Interactive shell mode

```bash
nexus shell --output-dir results/
```

Runs a read-eval loop: enter a query, get ranked results, repeat until `quit`.

### Scoring

Papers are ranked by a composite score with domain-aware weights:

| Component | Description |
|-----------|-------------|
| Venue | Tier-based score from `venues.yaml` |
| Citation | Age-adjusted citation count |
| Recency | Exponential decay by publication year |
| Relevance | OpenAI embedding cosine similarity (requires `OPENAI_API_KEY`) |
| OpenReview bonus | Extra weight for accepted conference papers |

### Sources

| Source | Notes |
|--------|-------|
| OpenAlex | Open metadata, abstract reconstruction, cursor pagination |
| Semantic Scholar | Influential citation count, open access URL |
| OpenReview | CS/ML only (`domain_category=cs_ml`); venue+year enumeration |

---

## Phase 2: Full-Text Download

Download full-text files for ranked papers. Reads Phase 1 JSON output, resolves content from multiple sources, and writes a crash-safe manifest.

```bash
# Download all papers from a results file
nexus download results/2026-04-01_attention_top20.json

# Custom output directory
nexus download results/papers.json --output-dir /data/papers

# Download only top 10
nexus download results/papers.json --top 10
```

**Default output directory:** `$NEXUS_DOWNLOAD_DIR`, else legacy `$NEXUS_PDF_DIR`, else `./papers`.

### Resolution order

For each paper, sources are tried in sequence:

1. `open_access_pdf_url` from Phase 1 metadata (direct download)
2. OpenAlex OA recovery from `openalex_id`
3. arXiv lookup by DOI
4. Unpaywall lookup by DOI (`NEXUS_UNPAYWALL_EMAIL`, default `weiy@ohsu`)
5. Elsevier full-text XML lookup by DOI (`ELSEVIER_API_KEY`, Elsevier DOI prefix `10.1016/`)

Downloads are validated before saving. HTML error pages are rejected for PDF sources, and the Elsevier fallback requires a valid full-text XML response.
Successful Elsevier subscription downloads are saved as `.xml` with `source_used: "elsevier_api"`.
The output directory may contain a mix of `.pdf` and `.xml` files.

### Manifest

Every download result is recorded in `manifest.json` in the output directory:

```json
{
  "entries": [
    {
      "paper_id": "doi:10.1145/3292500.3330701",
      "title": "Attention Is All You Need",
      "rank": 1,
      "score": 0.912,
      "status": "success",
      "source_used": "arxiv",
      "file_path": "/data/papers/rank_01_attention_is_all_you_need.pdf",
      "file_size_kb": 412,
      "error": null
    }
  ]
}
```

The manifest is written atomically after each paper — safe under SLURM preemption. Re-running skips papers already marked `"success"`.

## Running Tests

```bash
pytest                          # all unit tests (113 tests)
pytest tests/test_download/ -v  # Phase 2 tests only
pytest tests/test_dedup.py -v   # single file
pytest -m integration           # real API tests (requires keys)
```

---

## Key Design Decisions

- `paper_id` = `sha256[:16]` of DOI > arxiv_id > `hash(title+year)` — stable cross-phase foreign key
- Dedup: exact DOI → fuzzy title (rapidfuzz `token_sort_ratio`, threshold 92)
- OpenReview only queried when `domain_category == cs_ml`
- `RelevanceScorer` defaults to 0.5 when `OPENAI_API_KEY` unset
- All fetchers return `[]` on failure — never raise
- Downloads capped at 3 concurrent (`asyncio.Semaphore(3)`)
- Manifest written atomically after each paper (`os.replace`) for SLURM crash-safety

---

## Environment Variables

| Variable | Phase | Description |
|----------|-------|-------------|
| `OPENAI_API_KEY` | 1 | NLP parsing, relevance scoring, methodology classification |
| `S2_API_KEY` | 1 | Semantic Scholar higher rate limits |
| `NEXUS_EMAIL` | 1 | OpenAlex polite pool email |
| `NEXUS_DOWNLOAD_DIR` | 2 | Preferred default output directory for downloaded files |
| `NEXUS_PDF_DIR` | 2 | Legacy fallback output directory when `NEXUS_DOWNLOAD_DIR` is unset |
| `NEXUS_UNPAYWALL_EMAIL` | 2 | Email used for Unpaywall API requests (defaults to `weiy@ohsu`) |
| `ELSEVIER_API_KEY` | 2 | Required to enable Elsevier subscription XML fallback for `10.1016/...` DOIs |

---

## Changelog

### v0.2.0 — Phase 2: Full-Text Download
- `nexus download` CLI command
- 5-step resolver: saved OA URL → OpenAlex recovery → DOI arXiv → DOI Unpaywall → DOI Elsevier XML
- Atomic crash-safe manifest (`manifest.json`) with idempotent re-runs
- `asyncio.Semaphore(3)` rate-limited concurrent downloads
- `SearchQuery` extended: `keyword_count`, `venue_preferences`, `weight_preferences`, `publication_categories`, `keyword_logic`, `paper_titles`
- `Paper` extended: `methodology_category`, `publication_type`, `keywords`
- `nexus shell` interactive query loop
- `nexus fetch` gains `--keyword-count` and `--no-keyword-expansion` flags

### v0.1.0 — Phase 1: Paper Screening
- Fetch from OpenAlex, Semantic Scholar, OpenReview
- Fuzzy deduplication (rapidfuzz)
- Composite scoring: venue + citation + recency + relevance + OpenReview bonus
- Domain classification (OpenAI + keyword fallback)
- NLP query parsing with OpenAI (fallback to regex)
- `nexus fetch` CLI with auto-dated output
