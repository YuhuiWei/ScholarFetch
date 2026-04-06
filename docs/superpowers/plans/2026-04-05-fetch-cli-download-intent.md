# Fetch CLI Download Intent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `nexus fetch "..."` handle plain search-then-prompt, natural-language search-plus-download, and existing-results-JSON download routing in one integrated workflow.

**Architecture:** Keep `nexus fetch` as the only human-facing command, extend `SearchQuery` parsing with workflow-level download intent, and route everything through `run_fetch_workflow(...)`. Detect existing JSON files before NLP parsing, reuse the existing downloader paths, and preserve the paper-lookup `not_found=True` safety rule.

**Tech Stack:** Python 3.11+, Typer, Pydantic, pytest, pytest-asyncio

---

## File Map

- Modify: `nexus_paper_fetcher/models.py`
  - Add workflow-level fields needed by the parser and workflow.
- Modify: `nexus_paper_fetcher/nlp.py`
  - Parse natural-language download intent and clean fallback query text.
- Modify: `nexus_paper_fetcher/workflow.py`
  - Add fetch routing for existing results JSON files and honor parsed download intent.
- Modify: `nexus_paper_fetcher/cli.py`
  - Keep delegating to the workflow layer while exposing any new routing behavior through the same `fetch` command.
- Modify: `tests/test_nlp.py`
  - Lock parser behavior for download-intent queries.
- Modify: `tests/test_workflow.py`
  - Lock search-plus-download, results-file routing, and lookup `not_found=True` behavior.
- Modify: `tests/test_cli.py`
  - Lock CLI delegation and human-facing behavior contracts.
- Modify: `README.md`
  - Document the new CLI and API usage patterns.
- Modify: `CODEX_CHANGES.md`
  - Record the implementation details and verification evidence.

## Task 1: Lock Parser Behavior With Failing Tests

**Files:**
- Modify: `tests/test_nlp.py`
- Modify: `nexus_paper_fetcher/models.py`
- Modify: `nexus_paper_fetcher/nlp.py`

- [ ] **Step 1: Add failing parser tests for natural-language download intent**

```python
async def test_parse_natural_language_query_fallback_detects_download_request(monkeypatch):
    import nexus_paper_fetcher.nlp as nlp

    monkeypatch.setattr(nlp, "config", type("c", (), {"OPENAI_API_KEY": ""})())

    search_query, _ = await parse_natural_language_query(
        "download 10 papers about graph transformers"
    )

    assert search_query.query == "graph transformers"
    assert search_query.top_n == 10
    assert search_query.download_requested is True
    assert search_query.download_top_n == 10
    assert search_query.query_intent == "domain_search"
```

- [ ] **Step 2: Add failing parser test for paper lookup download intent**

```python
async def test_parse_natural_language_query_fallback_detects_lookup_download(monkeypatch):
    import nexus_paper_fetcher.nlp as nlp

    monkeypatch.setattr(nlp, "config", type("c", (), {"OPENAI_API_KEY": ""})())

    search_query, _ = await parse_natural_language_query(
        'download the paper "Attention Is All You Need"'
    )

    assert search_query.paper_titles == ["Attention Is All You Need"]
    assert search_query.download_requested is True
    assert search_query.query_intent == "paper_lookup"
```

- [ ] **Step 3: Run parser tests to verify they fail**

Run: `pytest -q tests/test_nlp.py -k download`

Expected: FAIL because the parser does not yet expose `download_requested`, `download_top_n`, or query cleanup for download phrases.

- [ ] **Step 4: Implement minimal parser/model support**

```python
class SearchQuery(BaseModel):
    ...
    download_requested: bool = False
    download_top_n: Optional[int] = None
```

```python
def _fallback_download_intent(text: str) -> tuple[bool, Optional[int], str]:
    ...
```

- [ ] **Step 5: Run parser tests to verify they pass**

Run: `pytest -q tests/test_nlp.py -k download`

Expected: PASS

## Task 2: Lock Workflow Routing With Failing Tests

**Files:**
- Modify: `tests/test_workflow.py`
- Modify: `nexus_paper_fetcher/workflow.py`

- [ ] **Step 1: Add failing workflow test for natural-language auto-download**

```python
async def test_query_requested_download_runs_without_confirmation(...):
    ...
    parse_mock = AsyncMock(
        return_value=(
            SearchQuery(
                query="graph transformers",
                query_intent="domain_search",
                download_requested=True,
                download_top_n=10,
            ),
            "cs_ml",
        )
    )
    ...
    assert workflow_result.download_requested is True
    assert workflow_result.download_top == 10
```

- [ ] **Step 2: Add failing workflow test for existing results JSON routing**

```python
async def test_results_file_query_routes_to_download_without_search(...):
    ...
    await workflow_module.run_fetch_workflow(
        query=str(results_path),
        interactive=False,
        output_dir=tmp_path / "papers",
    )
    run_mock.assert_not_awaited()
```

- [ ] **Step 3: Run workflow tests to verify they fail**

Run: `pytest -q tests/test_workflow.py -k "download or results_file"`

Expected: FAIL because `run_fetch_workflow(...)` does not yet route existing JSON files or honor parser-driven download intent.

- [ ] **Step 4: Implement minimal workflow routing**

```python
if _looks_like_results_file(query):
    return await _run_download_from_results_file(...)

download_requested = bool(download or search_query.download_requested)
chosen_download_top = cli_download_top or search_query.download_top_n
```

- [ ] **Step 5: Re-run workflow tests**

Run: `pytest -q tests/test_workflow.py -k "download or results_file"`

Expected: PASS

## Task 3: Lock CLI Contracts With Failing Tests

**Files:**
- Modify: `tests/test_cli.py`
- Modify: `nexus_paper_fetcher/cli.py`

- [ ] **Step 1: Add failing CLI test for `fetch results.json`**

```python
def test_fetch_results_json_still_delegates_to_workflow(tmp_path, monkeypatch):
    workflow_mock = AsyncMock(return_value=_workflow_result(tmp_path))
    ...
    result = runner.invoke(cli.app, ["fetch", str(tmp_path / "results.json"), "--yes", "--output-dir", str(tmp_path / "papers")])
    assert result.exit_code == 0
    assert workflow_mock.await_args.kwargs["query"] == str(tmp_path / "results.json")
```

- [ ] **Step 2: Add failing CLI test for download-intent query passthrough**

```python
def test_fetch_download_phrase_is_forwarded_verbatim_to_workflow(tmp_path, monkeypatch):
    ...
    result = runner.invoke(cli.app, ["fetch", "download 10 papers about graph transformers"])
    assert result.exit_code == 0
    assert workflow_mock.await_args.kwargs["query"] == "download 10 papers about graph transformers"
```

- [ ] **Step 3: Run CLI tests**

Run: `pytest -q tests/test_cli.py -k "results_json or download_phrase"`

Expected: PASS or targeted failures only if the CLI contract needs adjustment.

- [ ] **Step 4: Make any minimal CLI adjustments required by the tests**

```python
workflow_result = await run_fetch_workflow(...)
```

- [ ] **Step 5: Re-run CLI tests**

Run: `pytest -q tests/test_cli.py`

Expected: PASS

## Task 4: Documentation And Change Log

**Files:**
- Modify: `README.md`
- Modify: `CODEX_CHANGES.md`

- [ ] **Step 1: Update README usage docs**

```markdown
- `nexus fetch "graph transformers"` prompts whether to download after search
- `nexus fetch "download 10 papers about graph transformers"` triggers integrated download automatically
- `nexus fetch results/run.json` routes directly to download-from-results behavior
```

- [ ] **Step 2: Update `CODEX_CHANGES.md`**

```markdown
## 2026-04-05 Fetch CLI Download Intent
- added parser-driven download intent
- added `fetch` routing for existing results JSON input
- preserved lookup `not_found=True` no-download behavior
```

- [ ] **Step 3: Verify docs diffs**

Run: `git diff -- README.md CODEX_CHANGES.md`

Expected: only the intended documentation updates

## Task 5: Full Verification

**Files:**
- Modify: none

- [ ] **Step 1: Run focused NLP/workflow/CLI tests**

Run: `pytest -q tests/test_nlp.py tests/test_workflow.py tests/test_cli.py`

Expected: PASS

- [ ] **Step 2: Run broader regression tests for integrated branch paths**

Run: `pytest -q tests/test_download/test_pipeline.py tests/test_pipeline.py`

Expected: PASS

- [ ] **Step 3: Review final branch diff**

Run: `git status --short && git diff --stat`

Expected: only the intended feature-branch changes for parser, workflow, tests, README, and `CODEX_CHANGES.md`
