# nexus-paper-fetcher

Ranked academic paper search and full-text download pipeline for the NEXUS multi-agent research platform. Fetches candidates from OpenAlex, Semantic Scholar, and OpenReview, deduplicates and scores them, downloads full-text files, and organizes results for downstream ScholarWiki ingestion.

---

## Pipeline Overview

```
Phase 1: nexus fetch     →  ranked JSON in results/<slug>/
Phase 2: nexus download  →  downloaded files + download_status in JSON + manual.md
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

# Optional — authenticated OpenReview V2 search
export OPENREVIEW_USERNAME=you@example.edu
export OPENREVIEW_PASSWORD=...

# For OpenAlex polite pool
export NEXUS_EMAIL=you@institution.edu

# Preferred default output directory for downloaded files
export NEXUS_DOWNLOAD_DIR=/path/to/papers

# Legacy fallback (still supported)
export NEXUS_PDF_DIR=/path/to/papers
```

---

## Phase 1: Paper Screening

Fetch and rank papers from multiple academic sources. Results are saved to `results/<query-slug>/YYYY-MM-DD_top<N>.json`.

```bash
# Basic search
nexus fetch "single-cell RNA sequencing" --top-n 20

# Paper lookup
nexus fetch 'find the paper "Attention Is All You Need"' --top-n 5

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

# Expand an existing result with new papers (deduplicates against prior run)
nexus fetch "graph transformers" --expand

# Integrated fetch + download in one step
nexus fetch "graph transformers for molecular property prediction" --download

# Integrated fetch + download with explicit download controls
nexus fetch "single-cell foundation models" --download --download-top 8 --output-dir /data/papers

# Non-interactive automation mode (required for scripts/cron/SLURM)
nexus fetch "retrieval augmented generation for biomedicine" \
  --download \
  --download-top 10 \
  --output-dir /data/papers \
  --yes
```

**Output:** JSON file in `results/<slug>/` containing ranked papers with scores, metadata, source URLs, and per-paper `download_status`.

### `nexus fetch` routing behavior

`nexus fetch "..."` supports three modes:

1. **Plain search query** — runs search, saves ranked JSON, then asks whether to download
2. **Natural-language download query** — `nexus fetch "download 10 papers about graph transformers"` runs search and downloads until 10 succeed or the ranked list is exhausted
3. **Existing results JSON path** — `nexus fetch results/graph_transformers.json` skips search and routes directly to download

### Expand-existing search (`--expand`)

Re-running a query with `--expand` deduplicates against the most recent prior result for that slug:

```bash
nexus fetch "graph transformers" --top-n 20 --expand
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
nexus download results/attention-mechanisms/2026-04-09_top20.json

# Custom output directory
nexus download results/papers.json --output-dir /data/papers

# Collect 10 successfully downloadable papers from the ranked list
nexus download results/papers.json --top 10
```

**Default output directory:** `$NEXUS_DOWNLOAD_DIR`, else legacy `$NEXUS_PDF_DIR`, else `./papers`.

### Resolution order

For each paper, sources are tried in sequence:

1. `open_access_pdf_url` from Phase 1 metadata (direct download)
2. OpenAlex OA recovery from `openalex_id`
3. arXiv lookup by DOI
4. Unpaywall lookup by DOI (`NEXUS_UNPAYWALL_EMAIL`)
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

Papers that fail all resolution attempts are appended to `<output-dir>/manual.md`:

```markdown
# Manual Download Queue

### [Rank 3] Some Paywalled Paper
- **DOI:** [10.1016/j.cell.2024.01.001](https://doi.org/10.1016/j.cell.2024.01.001)
- **paper_id:** a1b2c3d4e5f6g7h8
- **Authors:** Smith, J.; Doe, A.
- **Year:** 2024 | **Venue:** Cell
- **Score:** 0.87
- **Status:** awaiting manual download
```

The file is append-only and deduplicates by `paper_id` across runs. Drop the PDF into `manual_inbox/` and run `scholarwiki ingest` to register it.

### Legacy manifest

When called via `nexus download` (standalone), `manifest.json` is still written to the output directory for backward compatibility. Integrated fetch+download and direct JSON routing use the in-place result tracking instead.

---

## Search Across Saved Results

Search locally across all saved result JSONs — no API calls:

```bash
# Keyword search across titles, abstracts, authors, and domain tags
nexus search "flash attention"

# Filter to papers that failed or were not downloaded
nexus search --not-downloadable

# Filter to only successfully downloaded papers
nexus search --downloaded

# Restrict to a specific query-slug subdirectory
nexus search "graph" --domain attention-mechanisms

# Combine filters
nexus search "transformer" --not-downloadable --domain cs-ml-papers
```

Output shows rank, composite score, download status, year, venue, and title. Results are sorted by fuzzy match score using rapidfuzz partial ratio.

---

## Interactive Shell Mode

```bash
nexus shell --output-dir results/
```

Runs a read-eval loop using the same integrated workflow as `nexus fetch`: enter a query, review ranked results, optionally continue into download, and repeat until `quit`.

Paper lookups return exact-title matches first. If an exact match is not found the result is marked `not_found: true` and closest matches are returned — these are saved but not auto-downloaded.

---

## Running Tests

```bash
pytest                          # all unit tests
pytest tests/test_download/ -v  # Phase 2 tests only
pytest tests/test_search.py -v  # search tests
pytest tests/test_dedup.py -v   # single file
pytest -m integration           # real API tests (requires keys)
```

---

## Python API

Use the integrated workflow API directly when embedding in scripts or orchestrators:

```python
import asyncio
from pathlib import Path
from nexus_paper_fetcher.workflow import run_fetch_workflow

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

Natural-language download requests and existing JSON paths are also accepted as `query`:

```python
# Natural-language download
result = await run_fetch_workflow(
    query="download 10 papers about graph transformers",
    interactive=False,
    output_dir=Path("papers"),
)

# Route an existing result JSON directly to download
result = await run_fetch_workflow(
    query="results/attention-mechanisms/2026-04-09_top20.json",
    interactive=False,
    output_dir=Path("papers"),
)

# Expand an existing result
result = await run_fetch_workflow(
    query="graph transformers",
    expand_existing=True,
    interactive=False,
)
```

Search across saved results:

```python
from nexus_paper_fetcher.search import search_results

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
- `manual.md` is append-only, deduplicated by `paper_id`, designed for ScholarWiki ingestion
- OpenReview only queried when `domain_category == cs_ml`
- `RelevanceScorer` defaults to 0.5 when `OPENAI_API_KEY` unset
- All fetchers return `[]` on failure — never raise
- Downloads capped at 3 concurrent (asyncio semaphore)
- Manifest written atomically after each paper (`os.replace`) for SLURM crash-safety

---

## Environment Variables

| Variable | Phase | Description |
|----------|-------|-------------|
| `OPENAI_API_KEY` | 1 | NLP parsing, relevance scoring, methodology classification |
| `S2_API_KEY` | 1 | Semantic Scholar higher rate limits |
| `OPENREVIEW_USERNAME` | 1 | Optional OpenReview V2 username |
| `OPENREVIEW_PASSWORD` | 1 | Optional OpenReview V2 password |
| `NEXUS_EMAIL` | 1 | OpenAlex polite pool email |
| `NEXUS_DOWNLOAD_DIR` | 2 | Preferred default output directory for downloaded files |
| `NEXUS_PDF_DIR` | 2 | Legacy fallback output directory |
| `NEXUS_UNPAYWALL_EMAIL` | 2 | Email for Unpaywall API requests (defaults to `weiy@ohsu`) |
| `ELSEVIER_API_KEY` | 2 | Required to enable Elsevier subscription XML fallback for `10.1016/...` DOIs |

---

## Changelog

### v0.3.0 — ScholarWiki Compatibility

- Results saved to `results/<query-slug>/YYYY-MM-DD_top<N>.json` (organized by query)
- Per-paper `download_status` and `download_file_path` written in-place to result JSON
- Crash-safe `download_progress.json` tracker (atomic writes, idempotent re-runs)
- `manual.md` append-only queue for papers that could not be auto-downloaded
- `--expand` flag: deduplicates against prior results, merges and re-ranks
- `nexus search` subcommand: fuzzy search across all saved result JSONs
- `Paper` model gains `download_status`, `download_file_path`, `domain_tags`
- `SearchQuery` gains `expand_existing`, `exclude_ids`, `query_slug`
- `RunResult` gains `expanded_from`

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
