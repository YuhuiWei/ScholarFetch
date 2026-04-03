# DOI OA Resolvers Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace EZproxy with DOI-based open-access resolution using arXiv and Unpaywall in the downloader.

**Architecture:** Keep `resolve()` in `download/downloader.py` as the single resolution orchestrator. Preserve the existing saved-URL and OpenAlex recovery paths, then add DOI-based arXiv and Unpaywall helpers, and remove EZproxy-specific runtime behavior from the CLI and pipeline.

**Tech Stack:** Python 3.12, httpx, pytest, respx, Pydantic

---

### Task 1: Lock The New Resolver Order With Failing Tests

**Files:**
- Modify: `tests/test_download/test_downloader.py`
- Modify: `tests/test_download/test_pipeline.py`
- Test: `tests/test_download/test_downloader.py`
- Test: `tests/test_download/test_pipeline.py`

- [ ] **Step 1: Write the failing arXiv-by-DOI test**

```python
@respx.mock
async def test_doi_resolves_to_arxiv_pdf(tmp_path):
    respx.get("https://export.arxiv.org/api/query").mock(
        return_value=httpx.Response(
            200,
            text="""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"
      xmlns:arxiv="http://arxiv.org/schemas/atom">
  <entry>
    <id>http://arxiv.org/abs/1706.03762v7</id>
    <arxiv:doi>10.5555/test.paper</arxiv:doi>
  </entry>
</feed>""",
        )
    )
    respx.get("https://arxiv.org/pdf/1706.03762v7.pdf").mock(
        return_value=httpx.Response(200, content=FAKE_PDF)
    )
    paper = _paper(open_access_pdf_url=None, arxiv_id=None, openalex_id=None)
    async with httpx.AsyncClient() as client:
        entry = await resolve(paper, rank=1, output_dir=tmp_path, session=client)
    assert entry.status == "success"
    assert entry.source_used == "arxiv"
```

- [ ] **Step 2: Write the failing Unpaywall test**

```python
@respx.mock
async def test_doi_resolves_through_unpaywall_pdf(tmp_path):
    respx.get("https://export.arxiv.org/api/query").mock(
        return_value=httpx.Response(
            200,
            text="""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"></feed>""",
        )
    )
    respx.get("https://api.unpaywall.org/v2/10.5555/test.paper").mock(
        return_value=httpx.Response(
            200,
            json={
                "best_oa_location": {
                    "url_for_pdf": "https://example.com/unpaywall.pdf",
                }
            },
        )
    )
    respx.get("https://example.com/unpaywall.pdf").mock(
        return_value=httpx.Response(200, content=FAKE_PDF)
    )
    paper = _paper(open_access_pdf_url=None, arxiv_id=None, openalex_id=None)
    async with httpx.AsyncClient() as client:
        entry = await resolve(paper, rank=1, output_dir=tmp_path, session=client)
    assert entry.status == "success"
    assert entry.source_used == "open_access_url"
```

- [ ] **Step 3: Write the failing no-EZproxy regression tests**

```python
async def test_no_ezproxy_branch_is_used(tmp_path):
    paper = _paper(open_access_pdf_url=None, arxiv_id=None, openalex_id=None)
    mock_ez = AsyncMock(spec=EZProxySession)
    async with httpx.AsyncClient() as client:
        entry = await resolve(paper, rank=1, output_dir=tmp_path, session=client, ezproxy=mock_ez)
    assert entry.status == "failed"
    mock_ez.get_pdf.assert_not_called()
```

```python
@respx.mock
async def test_run_download_recovers_doi_only_paper_without_ezproxy(tmp_path):
    papers = [
        Paper.create(
            title="Recovered Through DOI Resolver",
            doi="10.5555/test.paper",
            year=2022,
            scores=ScoreBreakdown(composite=0.9),
        ),
    ]
    respx.get("https://export.arxiv.org/api/query").mock(
        return_value=httpx.Response(
            200,
            text="""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"
      xmlns:arxiv="http://arxiv.org/schemas/atom">
  <entry>
    <id>http://arxiv.org/abs/1706.03762v7</id>
    <arxiv:doi>10.5555/test.paper</arxiv:doi>
  </entry>
</feed>""",
        )
    )
    respx.get("https://arxiv.org/pdf/1706.03762v7.pdf").mock(
        return_value=httpx.Response(200, content=FAKE_PDF)
    )
    manifest = await run_download(_make_results_file(tmp_path, papers=papers), tmp_path / "papers")
    assert manifest.entries[0].status == "success"
    assert manifest.entries[0].source_used == "arxiv"
```

- [ ] **Step 4: Run the targeted tests to verify they fail**

Run:

```bash
pytest \
  tests/test_download/test_downloader.py::test_doi_resolves_to_arxiv_pdf \
  tests/test_download/test_downloader.py::test_doi_resolves_through_unpaywall_pdf \
  tests/test_download/test_pipeline.py::test_run_download_recovers_doi_only_paper_without_ezproxy \
  -v
```

Expected:

- `resolve()` still tries EZproxy instead of DOI-based OA helpers
- the new tests fail with `entry.status == "failed"` or old branch assumptions

### Task 2: Implement arXiv DOI Resolution

**Files:**
- Modify: `nexus_paper_fetcher/download/downloader.py`
- Test: `tests/test_download/test_downloader.py`

- [ ] **Step 1: Add DOI normalization and Atom parsing helpers**

```python
ARXIV_API_URL = "https://export.arxiv.org/api/query"


def _normalize_doi(doi: Optional[str]) -> str | None:
    if not doi:
        return None
    return (
        doi.lower()
        .removeprefix("https://doi.org/")
        .removeprefix("http://doi.org/")
        .strip()
    ) or None
```

```python
def _extract_arxiv_pdf_from_feed(feed_xml: str, expected_doi: str) -> str | None:
    root = ET.fromstring(feed_xml)
    ns = {
        "atom": "http://www.w3.org/2005/Atom",
        "arxiv": "http://arxiv.org/schemas/atom",
    }
    for entry in root.findall("atom:entry", ns):
        doi_node = entry.find("arxiv:doi", ns)
        id_node = entry.find("atom:id", ns)
        if doi_node is None or id_node is None or not doi_node.text or not id_node.text:
            continue
        if _normalize_doi(doi_node.text) != expected_doi:
            continue
        arxiv_id = id_node.text.rsplit("/", 1)[-1]
        return f"https://arxiv.org/pdf/{arxiv_id}.pdf"
    return None
```

- [ ] **Step 2: Add the arXiv DOI helper**

```python
async def _find_arxiv_pdf_by_doi(
    session: httpx.AsyncClient,
    doi: Optional[str],
) -> str | None:
    normalized = _normalize_doi(doi)
    if not normalized:
        return None
    try:
        response = await session.get(
            ARXIV_API_URL,
            params={"search_query": f'doi:"{normalized}"', "start": 0, "max_results": 5},
        )
        response.raise_for_status()
        return _extract_arxiv_pdf_from_feed(response.text, normalized)
    except Exception as exc:
        logger.debug("arXiv DOI lookup failed for %s: %s", normalized, exc)
        return None
```

- [ ] **Step 3: Insert the helper into `resolve()` ahead of Unpaywall**

```python
    arxiv_pdf_url = await _find_arxiv_pdf_by_doi(session, paper.doi)
    if arxiv_pdf_url:
        content = await _fetch_url(session, arxiv_pdf_url)
        if content:
            file_path.write_bytes(content)
            return _success_entry(paper, rank, file_path, content, "arxiv")
```

- [ ] **Step 4: Run the arXiv-focused tests**

Run:

```bash
pytest \
  tests/test_download/test_downloader.py::test_doi_resolves_to_arxiv_pdf \
  tests/test_download/test_downloader.py::test_source2_arxiv_only \
  -v
```

Expected:

- both tests pass

### Task 3: Implement Unpaywall DOI Resolution

**Files:**
- Modify: `nexus_paper_fetcher/download/downloader.py`
- Test: `tests/test_download/test_downloader.py`

- [ ] **Step 1: Add Unpaywall URL extraction**

```python
UNPAYWALL_API_URL = "https://api.unpaywall.org/v2"
UNPAYWALL_EMAIL = "weiy@ohsu"


def _extract_unpaywall_pdf_url(payload: dict) -> str | None:
    best = payload.get("best_oa_location") or {}
    if isinstance(best, dict):
        if best.get("url_for_pdf"):
            return best["url_for_pdf"]
        if best.get("url"):
            return best["url"]

    for location in payload.get("oa_locations") or []:
        if not isinstance(location, dict):
            continue
        if location.get("url_for_pdf"):
            return location["url_for_pdf"]
        if location.get("url"):
            return location["url"]
    return None
```

- [ ] **Step 2: Add the Unpaywall helper**

```python
async def _find_unpaywall_pdf_by_doi(
    session: httpx.AsyncClient,
    doi: Optional[str],
    email: str = UNPAYWALL_EMAIL,
) -> str | None:
    normalized = _normalize_doi(doi)
    if not normalized:
        return None
    try:
        response = await session.get(
            f"{UNPAYWALL_API_URL}/{normalized}",
            params={"email": email},
        )
        if response.status_code == 404:
            return None
        response.raise_for_status()
        return _extract_unpaywall_pdf_url(response.json())
    except Exception as exc:
        logger.debug("Unpaywall lookup failed for %s: %s", normalized, exc)
        return None
```

- [ ] **Step 3: Insert Unpaywall after arXiv DOI lookup**

```python
    unpaywall_pdf_url = await _find_unpaywall_pdf_by_doi(session, paper.doi)
    if unpaywall_pdf_url:
        content = await _fetch_url(session, unpaywall_pdf_url)
        if content:
            file_path.write_bytes(content)
            return _success_entry(paper, rank, file_path, content, "open_access_url")
```

- [ ] **Step 4: Run the Unpaywall-focused tests**

Run:

```bash
pytest \
  tests/test_download/test_downloader.py::test_doi_resolves_through_unpaywall_pdf \
  tests/test_download/test_downloader.py::test_all_sources_fail \
  -v
```

Expected:

- Unpaywall success test passes
- failure test still passes when no resolver yields a PDF

### Task 4: Remove EZproxy From Runtime Behavior

**Files:**
- Modify: `nexus_paper_fetcher/download/downloader.py`
- Modify: `nexus_paper_fetcher/download/pipeline.py`
- Modify: `nexus_paper_fetcher/download/cli.py`
- Modify: `nexus_paper_fetcher/download/manifest.py`
- Modify: `tests/test_download/test_downloader.py`
- Modify: `tests/test_download/test_pipeline.py`

- [ ] **Step 1: Remove EZproxy from `resolve()` signature and logic**

```python
async def resolve(
    paper: Paper,
    rank: int,
    output_dir: Path,
    session: httpx.AsyncClient,
) -> ManifestEntry:
```

Delete:

```python
    # Source 3: EZproxy (DOI)
    if not skip_ezproxy and ezproxy is not None and paper.doi:
        content = await ezproxy.get_pdf(paper.doi)
        if content:
            file_path.write_bytes(content)
            return _success_entry(paper, rank, file_path, content, "ezproxy")
```

- [ ] **Step 2: Remove EZproxy setup from the pipeline**

```python
    async with httpx.AsyncClient(follow_redirects=True, timeout=30.0) as client:
        _err(
            f"[nexus-dl] downloading {len(to_download)} papers "
            f"(max {_CONCURRENCY} concurrent)..."
        )
```

Delete imports and state related to:

```python
from nexus_paper_fetcher.download.ezproxy import EZProxySession
skip_ezproxy
ezproxy
```

- [ ] **Step 3: Remove EZproxy-specific CLI option**

```python
def download_command(
    results_file: Path = typer.Argument(..., help="Path to Phase 1 results JSON"),
    output_dir: Path = typer.Option(
        _DEFAULT_OUTPUT_DIR, "--output-dir", help="Directory to save PDFs"
    ),
    top: Optional[int] = typer.Option(None, "--top", help="Download only top N papers"),
) -> None:
```

- [ ] **Step 4: Tighten manifest source type**

```python
source_used: Optional[Literal["open_access_url", "arxiv"]] = None
```

- [ ] **Step 5: Update tests to remove EZproxy assumptions**

Replace the old EZproxy-specific tests with assertions that DOI-only resolution now depends on arXiv/Unpaywall helpers instead of credentialed access.

- [ ] **Step 6: Run the runtime cleanup tests**

Run:

```bash
pytest tests/test_download/test_downloader.py tests/test_download/test_pipeline.py -q
```

Expected:

- all updated download tests pass
- no EZproxy-specific failures remain

### Task 5: Update User-Facing Docs And CLI Coverage

**Files:**
- Modify: `README.md`
- Modify: `CLAUDE.md`
- Modify: `tests/test_download/test_pipeline.py`

- [ ] **Step 1: Update README examples and download order**

Replace the download-order section with:

```markdown
1. `open_access_pdf_url` from Phase 1 metadata
2. OpenAlex OA recovery from `openalex_id`
3. arXiv lookup by DOI
4. Unpaywall lookup by DOI
```

Remove:

- OHSU credential setup
- `--skip-ezproxy`
- EZproxy narrative

- [ ] **Step 2: Update `CLAUDE.md` setup and design notes**

Remove EZproxy environment variables and any statements that Phase 2 depends on institutional proxy access.

- [ ] **Step 3: Update CLI smoke coverage**

Keep:

```python
result = runner.invoke(
    app,
    ["download", str(results_path), "--output-dir", str(output_dir)],
)
assert result.exit_code == 0, result.output
```

Delete CLI tests that assert `--skip-ezproxy` behavior.

- [ ] **Step 4: Run the doc-adjacent CLI test**

Run:

```bash
pytest tests/test_download/test_pipeline.py::test_cli_download_command -v
```

Expected:

- CLI smoke test passes with the simplified interface

### Task 6: Full Verification

**Files:**
- Test: `tests/test_download/test_downloader.py`
- Test: `tests/test_download/test_pipeline.py`
- Test: `tests/test_download/test_manifest.py`
- Test: `tests/test_download/test_ezproxy.py`

- [ ] **Step 1: Run the focused download suite**

Run:

```bash
pytest tests/test_download -q
```

Expected:

- all active download tests pass

- [ ] **Step 2: Decide what to do with `tests/test_download/test_ezproxy.py`**

Either:

```python
# delete the file if EZproxy support is intentionally removed
```

or:

```python
@pytest.mark.skip(reason="EZproxy support removed from downloader")
```

Choose one and make the suite explicit rather than leaving dead behavior ambiguous.

- [ ] **Step 3: Run the final verification command**

Run:

```bash
pytest tests/test_fetchers.py tests/test_download -q
```

Expected:

- fetcher and download suites pass together
