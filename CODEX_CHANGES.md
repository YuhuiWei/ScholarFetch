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
- scope prompt handling
- review filtering in pipeline
- lookup `not_found` behavior
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

## Verification Run

The latest verification run completed successfully:

- `pytest -q`
- result: `134 passed, 6 skipped`

## Known Remaining Notes

- There are still pre-existing `datetime.utcnow()` deprecation warnings in scoring code outside the main feature changes completed here.
- This summary intentionally does not include unrelated untracked repo files that were already present before this write-up.
