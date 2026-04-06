# CODEX Changes

This file summarizes the changes made in this Codex session for `nexus-paper-fetcher`.

## Scope

The work in this session focused on:

- fixing OpenReview paper retrieval
- replacing the numeric keyword-expansion prompt with a scope-based prompt
- splitting queries into paper-lookup vs domain-search behavior
- adding layered paper-category evaluation and reranking
- batching large relevance-scoring requests
- updating tests and docs to cover the new behavior

## Functional Changes

### 1. OpenReview retrieval

Updated OpenReview fetching to support authenticated API V2 search using credentials from the environment:

- `OPENREVIEW_USERNAME`
- `OPENREVIEW_PASSWORD`
- optional `OPENREVIEW_BASEURL`
- optional `OPENREVIEW_SEARCH_PAGE_SIZE`

Behavior:

- use authenticated OpenReview V2 search first when credentials are present
- page search requests with `limit`/`offset`
- fall back to public venue/year enumeration when authenticated search is unavailable or fails
- use the current year as the default upper bound instead of the old hard-coded `2024`

Files:

- `nexus_paper_fetcher/config.py`
- `nexus_paper_fetcher/fetchers/openreview.py`
- `pyproject.toml`

### 2. Query intent routing

Added explicit query intent handling:

- `paper_lookup`
- `domain_search`

Behavior:

- paper lookup skips keyword expansion
- paper lookup ranks exact title matches first
- if no exact match exists, results are returned with `not_found: true` and the closest matches
- domain search keeps broad retrieval and ranking flow

Files:

- `nexus_paper_fetcher/models.py`
- `nexus_paper_fetcher/nlp.py`
- `nexus_paper_fetcher/pipeline.py`

### 3. Search scope prompt

Replaced the old numeric interactive prompt:

- old: `Keyword expansion count [5]:`

with a scope prompt:

- new: `Search scope [specific/broad]`

Behavior:

- default is `specific`
- `specific` maps to fewer expansion terms
- `broad` maps to more expansion terms
- paper lookup mode bypasses scope prompting and disables expansion

Files:

- `nexus_paper_fetcher/cli.py`

### 4. Layered evaluation

Added a layered evaluation module to filter review/survey papers by default and improve reranking.

Layer 1: metadata heuristics

- review-journal/title blacklist checks
- cross-source publication-type voting

Layer 2: LLM judge

- use `gpt-4o-mini` for uncertain/top candidates
- classify `primary` vs `review`
- assign 1-5 relevance score
- store evaluation reasoning

Behavior:

- review/survey papers are excluded by default unless the query explicitly requests them
- LLM relevance is blended into final ranking when available

Files:

- `nexus_paper_fetcher/evaluation.py`
- `nexus_paper_fetcher/models.py`
- `nexus_paper_fetcher/pipeline.py`
- `nexus_paper_fetcher/scoring/scorer.py`

### 5. Large-batch relevance scoring

Updated embedding-based relevance scoring to batch large requests.

Behavior:

- break large abstract lists into multiple embedding requests
- cap batch size by input count
- also cap by estimated token load to avoid oversized requests

Files:

- `nexus_paper_fetcher/scoring/relevance.py`

### 6. Source metadata propagation and dedup

Extended source parsing and dedup merging so publication-type metadata survives cross-source merges.

Files:

- `nexus_paper_fetcher/fetchers/openalex.py`
- `nexus_paper_fetcher/fetchers/semantic_scholar.py`
- `nexus_paper_fetcher/dedup.py`

## Logging and Output Changes

Added or updated logs for:

- query intent
- search scope
- heuristic filtering counts
- LLM evaluation counts
- exact-match lookup fallback

Added summary messaging for:

- exact paper match not found, showing closest matches

Files:

- `nexus_paper_fetcher/cli.py`
- `nexus_paper_fetcher/pipeline.py`

## Documentation Changes

Updated the README to document:

- paper lookup vs domain search
- `specific` vs `broad` search scope
- OpenReview authenticated V2 usage
- layered evaluation behavior
- new environment variables
- `nexus fetch` routing for plain search, natural-language download intent, and existing results JSON input

Files:

- `README.md`

Also added the implementation plan used during the session:

- `docs/superpowers/plans/2026-04-03-query-intent-openreview-evaluation.md`

## Tests Added/Updated

Expanded tests for:

- OpenReview authenticated paged search
- OpenReview query-search fallback behavior
- lookup intent parsing
- fallback `top_n` parsing
- fallback natural-language download intent parsing
- scope prompt handling
- review filtering in pipeline
- lookup `not_found` behavior
- workflow auto-download intent without confirmation
- workflow routing of existing results JSON through `fetch`
- LLM relevance contribution
- batched relevance scoring

Files:

- `tests/test_fetchers.py`
- `tests/test_cli.py`
- `tests/test_nlp.py`
- `tests/test_pipeline.py`
- `tests/test_scoring.py`

## Files Changed in This Session

- `README.md`
- `pyproject.toml`
- `nexus_paper_fetcher/cli.py`
- `nexus_paper_fetcher/config.py`
- `nexus_paper_fetcher/dedup.py`
- `nexus_paper_fetcher/evaluation.py`
- `nexus_paper_fetcher/fetchers/openalex.py`
- `nexus_paper_fetcher/fetchers/openreview.py`
- `nexus_paper_fetcher/fetchers/semantic_scholar.py`
- `nexus_paper_fetcher/models.py`
- `nexus_paper_fetcher/nlp.py`
- `nexus_paper_fetcher/pipeline.py`
- `nexus_paper_fetcher/scoring/relevance.py`
- `nexus_paper_fetcher/scoring/scorer.py`
- `tests/test_cli.py`
- `tests/test_fetchers.py`
- `tests/test_nlp.py`
- `tests/test_pipeline.py`
- `tests/test_scoring.py`
- `docs/superpowers/plans/2026-04-03-query-intent-openreview-evaluation.md`
- `CODEX_CHANGES.md`

## 2026-04-05 Fetch CLI Download Intent Follow-Up

This follow-up extended the integrated workflow branch so `nexus fetch "..."`
handles plain search prompting, natural-language search-plus-download requests,
and existing search-results JSON input.

### Functional Changes

- Added workflow-level download fields to `SearchQuery`:
  - `download_requested`
  - `download_top_n`
- Extended NLP parsing so queries like:
  - `download 10 papers about graph transformers`
  - `download the paper "Attention Is All You Need"`
  populate cleaned search text plus download intent
- Added workflow routing for existing `.json` results-file input:
  - `nexus fetch results/run.json`
  - skips search and routes directly into the downloader
- Updated integrated workflow download behavior so parser-driven download intent:
  - skips the interactive "Download PDFs for these results?" confirmation
  - still prompts for output directory when needed
  - uses parsed download count when available
- Routed `nexus shell` through the same integrated workflow layer as `nexus fetch`
  so shell queries now support:
  - post-search download prompting
  - natural-language search-plus-download requests
  - the same paper-lookup `not_found=True` no-download safety rule
- Preserved the lookup safety rule:
  - if a paper lookup returns `not_found=True`, closest matches are saved and
    returned but not auto-downloaded

### Files Changed In This Follow-Up

- `nexus_paper_fetcher/models.py`
- `nexus_paper_fetcher/nlp.py`
- `nexus_paper_fetcher/workflow.py`
- `nexus_paper_fetcher/cli.py`
- `tests/test_cli.py`
- `tests/test_nlp.py`
- `tests/test_workflow.py`
- `README.md`
- `CODEX_CHANGES.md`
- `docs/superpowers/specs/2026-04-05-fetch-cli-download-intent-design.md`
- `docs/superpowers/plans/2026-04-05-fetch-cli-download-intent.md`

### Verification Added In This Follow-Up

Targeted new coverage now includes:

- fallback detection of domain-search download intent
- fallback detection of paper-lookup download intent
- workflow auto-download from parsed query intent
- workflow direct download routing from an existing results JSON path
- CLI passthrough for natural-language download phrases
- CLI passthrough for existing results JSON paths
- shell delegation to the integrated workflow layer

### Verification Run For This Follow-Up

Fresh verification completed during implementation:

- `pytest -q tests/test_nlp.py -k 'domain_download_intent or lookup_download_intent'`
  - result: `2 passed`
- `pytest -q tests/test_workflow.py -k 'query_requested_download_skips_confirmation or results_json_query_routes_to_download_without_search'`
  - result: `2 passed`
- `pytest -q tests/test_cli.py -k 'natural_language_download_phrase or existing_results_json'`
  - result: `2 passed`
- `pytest -q tests/test_cli.py -k shell_command_processes_queries_until_quit`
  - result: `1 passed`
- `pytest -q tests/test_cli.py tests/test_workflow.py`
  - result: `36 passed`
- `pytest -q tests/test_nlp.py tests/test_workflow.py tests/test_cli.py`
  - result: `45 passed`
- `pytest -q tests/test_download/test_pipeline.py tests/test_pipeline.py`
  - result: `22 passed`
- `pytest -q`
  - result: `170 passed, 6 skipped`

## 2026-04-05 Download Target-Semantics Fix

This follow-up corrected the integrated branch download semantics across both
CLI and API surfaces.

### Problem Fixed

Before this change, requests like:

- `nexus fetch "download 10 papers about ..."`
- `nexus fetch results.json --yes --output-dir papers --download-top 10`
- `nexus download results.json --top 10`
- `run_fetch_workflow(..., download_top=10)`

treated `10` as "attempt the first 10 ranked candidates once". If several of
those papers had no downloadable source, the final success count could be much
lower than 10.

### New Behavior

- `top` / `download_top` now means target successful downloads, not candidate count
- the downloader walks the ranked list until:
  - the requested number of successful downloads is available, or
  - the ranked list is exhausted
- when no top count is provided for direct JSON downloads, the downloader tries
  the full ranked list and collects all downloadable content
- the download manifest now records a structured `download_summary` including:
  - requested target
  - attempted count
  - already-downloaded count
  - newly-downloaded count
  - available count
  - failed count
  - shortfall count
  - top 5 failed backup candidates for manual follow-up
- `run_fetch_workflow(...)` now exposes that same summary via
  `workflow_result.download_summary`

### Files Changed In This Follow-Up

- `nexus_paper_fetcher/download/manifest.py`
- `nexus_paper_fetcher/download/pipeline.py`
- `nexus_paper_fetcher/download/cli.py`
- `nexus_paper_fetcher/workflow.py`
- `nexus_paper_fetcher/cli.py`
- `tests/test_download/test_pipeline.py`
- `tests/test_workflow.py`
- `README.md`
- `CODEX_CHANGES.md`

### Verification Added In This Follow-Up

- target-success semantics across failed early-ranked papers
- shortfall reporting when ranked results cannot fill the requested count
- workflow/API exposure of structured download summary metadata
- "blank means all downloadable" behavior for workflow-driven downloads

### Verification Run For This Follow-Up

- `pytest -q tests/test_download/test_pipeline.py tests/test_workflow.py`
  - result: `39 passed`

## Verification Run

The latest verification run completed successfully:

- `pytest -q`
- result: `134 passed, 6 skipped`

## Known Remaining Notes

- There are still pre-existing `datetime.utcnow()` deprecation warnings in scoring code outside the main feature changes completed here.
- This summary intentionally does not include unrelated untracked repo files that were already present before this write-up.
