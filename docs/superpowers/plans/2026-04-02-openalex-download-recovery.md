# OpenAlex Download Recovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Preserve OpenAlex open-access PDF URLs during fetch and recover them during download for existing saved result files.

**Architecture:** Extend the OpenAlex fetcher to map OA PDF metadata into `Paper.open_access_pdf_url`, then add a download-time OpenAlex metadata lookup when a paper has an `openalex_id` but no direct free-source URL. Keep the change narrowly scoped to existing fetcher and downloader boundaries.

**Tech Stack:** Python 3.12, httpx, pytest, respx, Pydantic

---

### Task 1: Lock OpenAlex OA Mapping With Tests

**Files:**
- Modify: `tests/test_fetchers.py`
- Test: `tests/test_fetchers.py`

- [ ] Add a failing fetcher assertion that OpenAlex list responses populate `Paper.open_access_pdf_url` from OA metadata.
- [ ] Run: `pytest tests/test_fetchers.py::test_openalex_fetcher_parses_papers -v`
- [ ] Expect: FAIL because the field is currently `None`.

### Task 2: Lock Download Recovery For Existing Result Files

**Files:**
- Modify: `tests/test_download/test_downloader.py`
- Modify: `tests/test_download/test_pipeline.py`
- Test: `tests/test_download/test_downloader.py`
- Test: `tests/test_download/test_pipeline.py`

- [ ] Add a failing downloader test covering a paper with `openalex_id` but no `open_access_pdf_url` or `arxiv_id`.
- [ ] Add a failing pipeline test covering `run_download()` recovering a PDF through OpenAlex metadata lookup.
- [ ] Run: `pytest tests/test_download/test_downloader.py::test_openalex_metadata_fallback_recovers_open_access_pdf tests/test_download/test_pipeline.py::test_run_download_recovers_openalex_pdf_for_saved_results -v`
- [ ] Expect: FAIL because no OpenAlex recovery path exists.

### Task 3: Implement Minimal Production Fix

**Files:**
- Modify: `nexus_paper_fetcher/fetchers/openalex.py`
- Modify: `nexus_paper_fetcher/download/downloader.py`

- [ ] Map OpenAlex OA metadata into `Paper.open_access_pdf_url`.
- [ ] Add a small downloader helper that fetches OpenAlex work metadata by `openalex_id` and extracts an OA PDF URL when needed.
- [ ] Keep manifest behavior unchanged aside from successful recovery.

### Task 4: Verify

**Files:**
- Test: `tests/test_fetchers.py`
- Test: `tests/test_download/test_downloader.py`
- Test: `tests/test_download/test_pipeline.py`

- [ ] Run: `pytest tests/test_fetchers.py tests/test_download/test_downloader.py tests/test_download/test_pipeline.py -q`
- [ ] Run: `pytest tests/test_download -q`
- [ ] Confirm the new tests pass and existing download tests stay green.
