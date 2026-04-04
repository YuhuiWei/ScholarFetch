# Query Intent, OpenReview Retrieval, and Layered Evaluation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add intent-aware paper search behavior, fix OpenReview returning no papers for relevant CS/ML queries, replace numeric keyword-expansion prompting with specific/broader scope selection, and add layered publication-category evaluation with LLM-assisted reranking.

**Architecture:** Keep the existing CLI -> NLP -> pipeline -> fetchers/scoring flow, but introduce explicit query intent and search-scope state on `SearchQuery`, a small evaluation layer between dedup and ranking, and a query-driven OpenReview fetch path. Paper lookup requests use exact/near-exact matching and fallback reporting, while domain search requests keep expansion and broad retrieval. Layered evaluation first removes obvious review/survey mismatches with metadata heuristics, then uses `gpt-4o-mini` for uncertain cases and final reranking.

**Tech Stack:** Python 3.11+, Typer, Pydantic, httpx, pytest/pytest-asyncio/respx, OpenAI API (`gpt-4o-mini`, embeddings)

---

### Task 1: Lock behavior with regression tests

**Files:**
- Modify: `tests/test_fetchers.py`
- Modify: `tests/test_cli.py`
- Modify: `tests/test_pipeline.py`
- Modify: `tests/test_nlp.py`
- Modify: `tests/test_scoring.py`

- [ ] **Step 1: Write failing OpenReview and query-intent tests**

```python
async def test_openreview_fetcher_uses_search_query_path_for_cs_requests():
    ...

async def test_openreview_fetcher_defaults_year_to_current_year():
    ...

def test_fetch_command_prompts_for_scope_not_keyword_count():
    ...

async def test_parse_natural_language_query_classifies_lookup_intent():
    ...

async def test_pipeline_returns_not_found_for_lookup_without_exact_match():
    ...
```

- [ ] **Step 2: Run focused tests to verify failures**

Run: `pytest tests/test_fetchers.py tests/test_cli.py tests/test_nlp.py tests/test_pipeline.py tests/test_scoring.py -v`

Expected: failures for missing `query_intent`, missing scope prompt behavior, missing lookup routing, and missing layered evaluation fields.

- [ ] **Step 3: Add failing layered-evaluation tests**

```python
async def test_layered_evaluation_filters_review_journal_articles():
    ...

async def test_layered_evaluation_keeps_explicit_review_queries():
    ...

async def test_score_all_uses_llm_relevance_score_when_present():
    ...
```

- [ ] **Step 4: Run scoring/pipeline tests again**

Run: `pytest tests/test_pipeline.py tests/test_scoring.py -v`

Expected: failures showing missing heuristic filtering and missing LLM-rerank support.

- [ ] **Step 5: Commit regression tests**

```bash
git add tests/test_fetchers.py tests/test_cli.py tests/test_nlp.py tests/test_pipeline.py tests/test_scoring.py
git commit -m "test: cover query intent and layered evaluation"
```

### Task 2: Add query intent and scope selection

**Files:**
- Modify: `nexus_paper_fetcher/models.py`
- Modify: `nexus_paper_fetcher/nlp.py`
- Modify: `nexus_paper_fetcher/cli.py`
- Test: `tests/test_cli.py`
- Test: `tests/test_nlp.py`

- [ ] **Step 1: Add `query_intent` and `search_scope` fields to `SearchQuery`**

```python
class SearchQuery(BaseModel):
    ...
    query_intent: str = "domain_search"
    search_scope: Optional[str] = None
```

- [ ] **Step 2: Teach NLP parsing and fallback parsing to populate intent**

```python
def _fallback_query_intent(text: str) -> str:
    ...
```

- [ ] **Step 3: Replace numeric interactive prompt with scope prompt**

```python
scope = typer.prompt("Search scope [specific/broader]", default="specific").strip().lower()
sq.search_scope = scope
sq.keyword_count = 3 if scope == "specific" else 8
```

- [ ] **Step 4: Skip scope prompting for paper lookup and no-expansion cases**

Run: `pytest tests/test_cli.py tests/test_nlp.py -v`
Expected: PASS

- [ ] **Step 5: Commit intent/scope changes**

```bash
git add nexus_paper_fetcher/models.py nexus_paper_fetcher/nlp.py nexus_paper_fetcher/cli.py tests/test_cli.py tests/test_nlp.py
git commit -m "feat: add query intent and scope prompt"
```

### Task 3: Fix OpenReview retrieval

**Files:**
- Modify: `nexus_paper_fetcher/fetchers/openreview.py`
- Modify: `nexus_paper_fetcher/pipeline.py`
- Test: `tests/test_fetchers.py`
- Test: `tests/test_pipeline.py`

- [ ] **Step 1: Add query-driven OpenReview search and current-year defaults**

```python
year_to = query.year_to or datetime.utcnow().year
search_results = await self._search_notes(client, query.query, year_from, year_to, target)
```

- [ ] **Step 2: Keep venue/year enumeration as a secondary enrichment path**

```python
if len(papers) < target:
    papers.extend(await self._fetch_recent_venues(...))
```

- [ ] **Step 3: Deduplicate OpenReview-internal results before returning**

Run: `pytest tests/test_fetchers.py tests/test_pipeline.py -v`
Expected: PASS

- [ ] **Step 4: Commit OpenReview fix**

```bash
git add nexus_paper_fetcher/fetchers/openreview.py nexus_paper_fetcher/pipeline.py tests/test_fetchers.py tests/test_pipeline.py
git commit -m "fix: use query-driven openreview retrieval"
```

### Task 4: Add layered evaluation and lookup fallback behavior

**Files:**
- Create: `nexus_paper_fetcher/evaluation.py`
- Modify: `nexus_paper_fetcher/models.py`
- Modify: `nexus_paper_fetcher/pipeline.py`
- Modify: `nexus_paper_fetcher/scoring/scorer.py`
- Test: `tests/test_pipeline.py`
- Test: `tests/test_scoring.py`

- [ ] **Step 1: Add evaluation metadata fields to `Paper` and `RunResult`**

```python
heuristic_category: Optional[str] = None
llm_category: Optional[str] = None
llm_relevance_score: Optional[float] = None
evaluation_reasoning: Optional[str] = None
exact_match: bool = False

not_found: bool = False
match_strategy: Optional[str] = None
```

- [ ] **Step 2: Implement heuristic filtering and API vote**

```python
REVIEW_VENUE_PATTERNS = (...)

async def evaluate_candidates(papers, query, domain_category):
    ...
```

- [ ] **Step 3: Add `gpt-4o-mini` categorical judge for uncertain/top papers**

```python
{
    "category": "primary",
    "relevance_score": 4,
    "reasoning": "..."
}
```

- [ ] **Step 4: Update ranking to use LLM relevance when available and filter mismatched categories**

Run: `pytest tests/test_pipeline.py tests/test_scoring.py -v`
Expected: PASS

- [ ] **Step 5: Commit layered evaluation**

```bash
git add nexus_paper_fetcher/evaluation.py nexus_paper_fetcher/models.py nexus_paper_fetcher/pipeline.py nexus_paper_fetcher/scoring/scorer.py tests/test_pipeline.py tests/test_scoring.py
git commit -m "feat: add layered publication evaluation"
```

### Task 5: Finish logging and docs

**Files:**
- Modify: `README.md`
- Modify: `nexus_paper_fetcher/cli.py`
- Modify: `nexus_paper_fetcher/pipeline.py`

- [ ] **Step 1: Add stderr logs for intent, scope, heuristic filtering, LLM judging, and lookup fallback**

```python
_err(f"[nexus] query intent... {query.query_intent}")
_err(f"[nexus] evaluation filtered {filtered_count} review/survey papers")
```

- [ ] **Step 2: Update README examples and scoring description**

```markdown
- Interactive scope prompt asks `specific` or `broader`
- Paper lookup returns exact match first, else `not_found` + closest matches
- Layered evaluation excludes review papers by default
```

- [ ] **Step 3: Run targeted verification**

Run: `pytest tests/test_fetchers.py tests/test_cli.py tests/test_nlp.py tests/test_pipeline.py tests/test_scoring.py -v`
Expected: PASS

- [ ] **Step 4: Run full verification**

Run: `pytest -q`
Expected: all tests pass

- [ ] **Step 5: Commit docs/logging updates**

```bash
git add README.md nexus_paper_fetcher/cli.py nexus_paper_fetcher/pipeline.py docs/superpowers/plans/2026-04-03-query-intent-openreview-evaluation.md
git commit -m "docs: describe intent-aware search and evaluation"
```
