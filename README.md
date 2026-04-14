# ScholarFetch

Ranked academic paper search and full-text download pipeline. Fetches candidates from OpenAlex, Semantic Scholar, and OpenReview, deduplicates and scores them, downloads full-text files, and organizes results for downstream ingestion.

---

## Pipeline Overview

```
Phase 1: scholar fetch     →  ranked JSON in results/<slug>/
Phase 2: scholar download  →  downloaded files + download_status in JSON + manual.md
```

---

## Setup

```bash
pip install -e ".[dev]"

# Optional — enables NLP query parsing, relevance scoring, methodology classification
export OPENAI_API_KEY=sk-...

# Optional — higher Semantic Scholar rate limits
export S2_API_KEY=...

# Optional — authenticated OpenReview V2 search
export OPENREVIEW_USERNAME=you@example.edu
export OPENREVIEW_PASSWORD=...

# For OpenAlex polite pool
export SCHOLAR_EMAIL=you@institution.edu

# Preferred default output directory for downloaded files
export SCHOLAR_DOWNLOAD_DIR=/path/to/papers

# Legacy fallback (still supported)
export SCHOLAR_PDF_DIR=/path/to/papers
```

---

## Phase 1: Paper Screening

Fetch and rank papers from multiple academic sources. Results are saved to `results/<query-slug>/YYYY-MM-DD_top<N>.json`.

```bash
# Basic search
scholar fetch "single-cell RNA sequencing" --top-n 20

# Paper lookup
scholar fetch 'find the paper "Attention Is All You Need"' --top-n 5

# With filters
scholar fetch "attention mechanisms" --top-n 50 --domain-category cs_ml --year-from 2020

# Limit to a specific author
scholar fetch "graph neural networks" --author "Kipf, T." --top-n 10

# Disable keyword expansion
scholar fetch "CRISPR base editing" --no-keyword-expansion

# Control expansion keyword count
scholar fetch "diffusion models" --keyword-count 7

# Save to a specific path
scholar fetch "transformer architectures" --output results/transformers.json

# Expand an existing result with new papers (deduplicates against prior run)
scholar fetch "graph transformers" --expand

# Integrated fetch + download in one step
scholar fetch "graph transformers for molecular property prediction" --download

# Integrated fetch + download with explicit download controls
scholar fetch "single-cell foundation models" --download --download-top 8 --output-dir /data/papers

# Non-interactive automation mode (required for scripts/cron/SLURM)
scholar fetch "retrieval augmented generation for biomedicine" \
  --download \
  --download-top 10 \
  --output-dir /data/papers \
  --yes
```

**Output:** JSON file in `results/<slug>/` containing ranked papers with scores, metadata, source URLs, and per-paper `download_status`.

### `scholar fetch` routing behavior

`scholar fetch "..."` supports three modes:

1. **Plain search query** — runs search, saves ranked JSON, then asks whether to download
2. **Natural-language download query** — `scholar fetch "download 10 papers about graph transformers"` runs search and downloads until 10 succeed or the ranked list is exhausted
3. **Existing results JSON path** — `scholar fetch results/graph_transformers.json` skips search and routes directly to download

### Expand-existing search (`--expand`)

Re-running a query with `--expand` deduplicates against the most recent prior result for that slug:

```bash
scholar fetch "graph transformers" --top-n 20 --expand
```

New papers are fetched excluding previously seen `paper_id`s, then merged with prior results and re-ranked by composite score. The merged result is saved as a new dated file.

### Non-interactive automation

Use `--yes` (alias `--non-interactive`) to disable all prompts. `--output-dir` is required when `--download` is set in non-interactive mode.

### Scoring

Papers are ranked by a composite score with domain-aware weights:

| Component | Description |
|-----------|-------------|
| Venue | Tier-based score from `venues.yaml` |
| Citation | Age-adjusted citation count |
| Recency | Exponential decay by publication year |
| Relevance | OpenAI embedding cosine similarity (requires `OPENAI_API_KEY`) |
| LLM relevance | `gpt-4o-mini` 1–5 relevance score blended for uncertain/top candidates |
| OpenReview bonus | Extra weight for accepted conference papers |

### Query modes

| Mode | Behavior |
|------|----------|
| Paper lookup | Finds a single paper or named set; ranks exact title matches first; reports `not_found` when only approximate matches are available |
| Domain search | Defaults to a specific search with 3 expansion keywords; `--keyword-count`, `--no-keyword-expansion`, or an explicit scope choice can broaden or narrow retrieval |

By default the layered evaluation stage excludes review/survey articles unless the query explicitly asks for them.

### Sources

| Source | Notes |
|--------|-------|
| OpenAlex | Open metadata, abstract reconstruction, cursor pagination |
| Semantic Scholar | Influential citation count, open access URL, publication type metadata |
| OpenReview | CS/ML only (`domain_category=cs_ml`); authenticated V2 search when credentials are set, else venue/year fallback |

---

## Phase 2: Full-Text Download

Download full-text files for ranked papers. For each paper the result JSON is updated in-place with `download_status` (`success` / `failed` / `not_attempted`) and `download_file_path`. Papers that could not be auto-downloaded are appended to `manual.md` in the output directory.

```bash
# Download all papers from a results file
scholar download results/attention-mechanisms/2026-04-09_top20.json

# Custom output directory
scholar download results/papers.json --output-dir /data/papers

# Collect 10 successfully downloadable papers from the ranked list
scholar download results/papers.json --top 10
```

**Default output directory:** `$SCHOLAR_DOWNLOAD_DIR`, else legacy `$SCHOLAR_PDF_DIR`, else `./papers`.

### Resolution order

For each paper, sources are tried in sequence:

1. `open_access_pdf_url` from Phase 1 metadata (direct download)
2. OpenAlex OA recovery from `openalex_id`
3. arXiv lookup by DOI
4. Unpaywall lookup by DOI (`SCHOLAR_UNPAYWALL_EMAIL`)
5. Elsevier full-text XML lookup by DOI (`ELSEVIER_API_KEY`, Elsevier DOI prefix `10.1016/`)

Downloads are validated before saving. HTML error pages are rejected. Elsevier fallback requires a valid full-text XML response and saves `.xml` files.

### In-place result tracking

After each download attempt the source result JSON is updated atomically:

```json
{
  "paper_id": "abc123",
  "title": "Graph Transformers",
  "download_status": "success",
  "download_file_path": "/data/papers/rank_01_graph_transformers.pdf",
  ...
}
```

`download_status` values: `"success"` / `"failed"` / `"not_attempted"`

Re-running skips papers already marked `"success"`. Progress is tracked in `download_progress.json` alongside the files, written atomically after each paper (crash-safe under SLURM preemption).

### Manual download queue (`manual.md`)

Papers that fail all resolution attempts are appended to `<output-dir>/manual.md`.

---

## Search Across Saved Results

Search locally across all saved result JSONs — no API calls:

```bash
# Keyword search across titles, abstracts, authors, and domain tags
scholar search "flash attention"

# Filter to papers that failed or were not downloaded
scholar search --not-downloadable

# Filter to only successfully downloaded papers
scholar search --downloaded

# Restrict to a specific query-slug subdirectory
scholar search "graph" --domain attention-mechanisms
```

---

## Interactive Shell Mode

```bash
scholar shell --output-dir results/
```

Runs a read-eval loop: enter a query, review ranked results, optionally continue into download, and repeat until `quit`.

---

## Running Tests

```bash
pytest                          # all unit tests
pytest tests/test_download/ -v  # Phase 2 tests only
pytest tests/test_search.py -v  # search tests
pytest -m integration           # real API tests (requires keys)
```

---

## Python API

```python
import asyncio
from pathlib import Path
from scholar_fetch.workflow import run_fetch_workflow

async def main() -> None:
    result = await run_fetch_workflow(
        query="multimodal foundation models for pathology",
        top_n=20,
        download=True,
        download_top=5,
        output_dir=Path("/data/papers"),
        interactive=False,
    )
    print("Saved ranked results:", result.saved_result_path)
    if result.download_summary is not None:
        print("Shortfall:", result.download_summary.shortfall_count)

asyncio.run(main())
```

Search across saved results:

```python
from scholar_fetch.search import search_results

hits = search_results("flash attention", results_dir=Path("results"))
for hit in hits[:10]:
    print(hit.rank, hit.paper.title, hit.paper.download_status)
```

---

## Key Design Decisions

- `paper_id` = `sha256[:16]` of DOI > arxiv_id > `hash(title+year)` — stable cross-phase foreign key
- Dedup: exact DOI → fuzzy title (rapidfuzz `token_sort_ratio`, threshold 92)
- Results organized as `results/<query-slug>/YYYY-MM-DD_top<N>.json`
- `--expand` excludes prior `paper_id`s from new fetch, then merges and re-ranks
- Download status written in-place to the source result JSON (atomic via `.tmp` + `os.replace`)
- `download_progress.json` tracks per-paper status independently of the manifest, for crash-safe resume
- `manual.md` is append-only, deduplicated by `paper_id`
- OpenReview only queried when `domain_category == cs_ml`
- `RelevanceScorer` defaults to 0.5 when `OPENAI_API_KEY` unset
- All fetchers return `[]` on failure — never raise
- Downloads capped at 3 concurrent (asyncio semaphore)

---

## Environment Variables

| Variable | Phase | Description |
|----------|-------|-------------|
| `OPENAI_API_KEY` | 1 | NLP parsing, relevance scoring, methodology classification |
| `S2_API_KEY` | 1 | Semantic Scholar higher rate limits |
| `OPENREVIEW_USERNAME` | 1 | Optional OpenReview V2 username |
| `OPENREVIEW_PASSWORD` | 1 | Optional OpenReview V2 password |
| `SCHOLAR_EMAIL` | 1 | OpenAlex polite pool email |
| `SCHOLAR_DOWNLOAD_DIR` | 2 | Preferred default output directory for downloaded files |
| `SCHOLAR_PDF_DIR` | 2 | Legacy fallback output directory |
| `SCHOLAR_UNPAYWALL_EMAIL` | 2 | Email for Unpaywall API requests |
| `ELSEVIER_API_KEY` | 2 | Required to enable Elsevier subscription XML fallback for `10.1016/...` DOIs |

---

## Changelog

### v0.3.0

- Results saved to `results/<query-slug>/YYYY-MM-DD_top<N>.json` (organized by query)
- Per-paper `download_status` and `download_file_path` written in-place to result JSON
- Crash-safe `download_progress.json` tracker (atomic writes, idempotent re-runs)
- `manual.md` append-only queue for papers that could not be auto-downloaded
- `--expand` flag: deduplicates against prior results, merges and re-ranks
- `scholar search` subcommand: fuzzy search across all saved result JSONs
- Layered paper evaluation (heuristic + LLM judge) with review/survey filtering
- Paper lookup vs domain search routing
- Authenticated OpenReview V2 search

### v0.2.0

- `scholar download` CLI command
- 5-step resolver: saved OA URL → OpenAlex recovery → DOI arXiv → DOI Unpaywall → DOI Elsevier XML
- Atomic crash-safe manifest with idempotent re-runs
- `asyncio.Semaphore(3)` rate-limited concurrent downloads
- `scholar shell` interactive query loop

### v0.1.0

- Fetch from OpenAlex, Semantic Scholar, OpenReview
- Fuzzy deduplication (rapidfuzz)
- Composite scoring: venue + citation + recency + relevance + OpenReview bonus
- Domain classification (OpenAI + keyword fallback)
- NLP query parsing with OpenAI (fallback to regex)
- `scholar fetch` CLI with auto-dated output
