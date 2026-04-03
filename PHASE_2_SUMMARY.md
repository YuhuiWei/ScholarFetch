# Phase 2: Full-Text Download Pipeline — Implementation Summary

## Overview

Phase 2 extends `nexus-paper-fetcher` with a full download pipeline. It reads the ranked JSON output from Phase 1, resolves and downloads full-text files from multiple sources, writes each result to a crash-safe manifest, and exposes a `nexus download` CLI command.

Phase 3 reads `manifest.json` to discover which downloaded files are available for extraction.

---

## CLI Usage

```bash
# Download all papers from a Phase 1 results file
nexus download results/2026-04-01_attention_top20.json

# Save downloaded files to a custom directory
nexus download results/papers.json --output-dir /data/papers

# Download only the top 10 ranked papers
nexus download results/papers.json --top 10

# Combined
nexus download results/papers.json --output-dir /data/papers --top 10
```

**Default output directory:** `$NEXUS_DOWNLOAD_DIR`, else legacy `$NEXUS_PDF_DIR`, else `./papers`.

**Progress output** (stderr):

```
[nexus-dl] loading results/papers.json  ->  20 papers (3 already downloaded)
[nexus-dl] downloading 17 papers (max 3 concurrent)...
[nexus-dl]   rank_01  ok  open_access_url      ( 412 KB)  rank_01_attention_is_all_you_need.pdf
[nexus-dl]   rank_02  ok  arxiv                ( 891 KB)  rank_02_bert_pre_training_of_deep.pdf
[nexus-dl]   rank_03  fail  -                            no downloadable source found
[nexus-dl] done: 16 success, 1 failed, 3 skipped  ->  papers/manifest.json
```

---

## Resolution Order

For each paper, sources are tried in sequence; the first successful download wins:

| Priority | Source | Condition |
|----------|--------|-----------|
| 1 | `open_access_pdf_url` from Phase 1 JSON | Field is non-empty |
| 2 | OpenAlex OA recovery from `openalex_id` | `openalex_id` field is non-empty |
| 3 | arXiv lookup by DOI | `doi` field is non-empty and arXiv DOI match succeeds |
| 4 | Unpaywall lookup by DOI | `doi` field is non-empty |
| 5 | Elsevier full-text XML by DOI | `doi` starts with `10.1016/` and `ELSEVIER_API_KEY` is set |

PDF-oriented sources validate that downloaded content starts with `%PDF`; HTML error pages are silently rejected and the next source is tried. The Elsevier fallback validates full-text XML response structure before saving.

---

## Manifest (`manifest.json`)

Each paper's download result is recorded in `manifest.json` in the output directory.

### Schema

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
    },
    {
      "paper_id": "title:some_paywalled_paper",
      "title": "Some Paywalled Paper",
      "rank": 5,
      "score": 0.743,
      "status": "failed",
      "source_used": null,
      "file_path": null,
      "file_size_kb": null,
      "error": "no downloadable source found"
    }
  ]
}
```

### Field reference

| Field | Type | Description |
|-------|------|-------------|
| `paper_id` | `str` | Stable FK from Phase 1 (`doi:…` or `title:…`) |
| `title` | `str` | Paper title |
| `rank` | `int` | Rank from Phase 1 scoring (1 = best) |
| `score` | `float` | Composite score from Phase 1 |
| `status` | `"success" \| "failed"` | Download outcome |
| `source_used` | `"open_access_url" \| "arxiv" \| "elsevier_api" \| null` | Which source succeeded |
| `file_path` | `str \| null` | Absolute path to saved file (`.pdf` or `.xml`) |
| `file_size_kb` | `int \| null` | File size in KB |
| `error` | `str \| null` | Error message on failure |

### Crash-safety

The manifest is written atomically after **every individual paper** using `os.replace(tmp, target)` (POSIX-atomic). A SLURM job killed mid-batch loses at most one in-flight paper; all previously written entries are preserved.

### Idempotency

Re-running `nexus download` on the same results file skips any paper whose `paper_id` already has `status == "success"` in the manifest. Failed papers are retried.

### File naming

```
rank_{rank:02d}_{first_6_words_of_title}.{pdf|xml}

Examples:
  rank_01_attention_is_all_you_need.pdf
  rank_02_bert_pre_training_of_deep.pdf
  rank_03_cell_xyz.xml
```

---

## Unpaywall Integration

For DOI fallback, the downloader queries:

```
GET https://api.unpaywall.org/v2/{normalized_doi}?email=<email>
```

Email resolution is runtime-configurable:

1. `NEXUS_UNPAYWALL_EMAIL` environment variable
2. fallback default `weiy@ohsu`

The resolver prefers `best_oa_location.url_for_pdf`, then other OA location URLs, and still validates final content as PDF bytes before saving.

---

## Elsevier Subscription XML Fallback

If OA sources fail and the DOI is an Elsevier DOI (`10.1016/...`), the downloader attempts:

```
GET https://api.elsevier.com/content/article/doi/{normalized_doi}
Headers:
  X-ELS-APIKey: <ELSEVIER_API_KEY>
  Accept: application/xml
```

Notes:

- `ELSEVIER_API_KEY` is required for this fallback.
- Successful responses are saved as `.xml`.
- Manifest entries for these successes use `source_used: "elsevier_api"`.
- Output directories can contain a mix of `.pdf` and `.xml` files.

---

## Concurrency

Downloads run with `asyncio` and a `Semaphore(3)` — at most 3 papers download concurrently. A single shared `httpx.AsyncClient` is reused across concurrent requests.

The manifest upsert + atomic save are both synchronous (no `await` between them), so they cannot be interleaved by the event loop even under concurrent execution — no lock needed.

---

## Module Structure

```
nexus_paper_fetcher/download/
  __init__.py          empty package marker
  manifest.py          ManifestEntry / Manifest Pydantic models; atomic load/save
  ezproxy.py           Legacy module (not used in active resolver order)
  downloader.py        resolve() — OA URL -> OpenAlex -> DOI arXiv -> DOI Unpaywall -> DOI Elsevier XML
  pipeline.py          run_download() — batch orchestration, Semaphore(3)
  cli.py               download_command() registered as `nexus download`

tests/test_download/
  constants.py         shared FAKE_PDF / FAKE_HTML bytes
  test_manifest.py     7 tests
  test_ezproxy.py      6 tests
  test_downloader.py   downloader source fallthrough tests (including Elsevier XML fallback)
  test_pipeline.py     batch download + manifest behavior tests
```

---

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `NEXUS_DOWNLOAD_DIR` | No | Preferred default output directory for downloaded files |
| `NEXUS_PDF_DIR` | No | Legacy fallback output directory when `NEXUS_DOWNLOAD_DIR` is unset |
| `NEXUS_UNPAYWALL_EMAIL` | No | Email used for Unpaywall API requests (default: `weiy@ohsu`) |
| `ELSEVIER_API_KEY` | No | Required to enable Elsevier subscription XML fallback |

---

## Branch History

Branch: `phase2-download` from base `9ec65cf` (Phase 1 complete)

| Commit | Description |
|--------|-------------|
| `f47c793` | Manifest models and atomic read/write |
| `0df2089` | EZProxy session auth |
| `28015f1` | Fix: EZProxy auth requires 302, not 200 |
| `ae988cf` | PDF resolver with 3-source fallthrough |
| `55f5f31` | Fix: pad FAKE_PDF for size test; title fallback in filename |
| `7e5b82e` | Batch download pipeline with incremental manifest writes |
| `851e701` | Fix: guard `top_n` with `is not None` |
| `1036a23` | `nexus download` CLI subcommand |
| `831a6db` | Post-review cleanup |
| `92ff6ae` | Fix 11 pre-existing Phase 1 test failures |
