# DOI OA Resolvers Design

## Goal

Replace the current EZproxy-dependent DOI fallback with two non-institutional DOI-based resolvers:

1. arXiv lookup by DOI
2. Unpaywall lookup by DOI using `weiy@ohsu`

The revised download order must be:

1. `paper.open_access_pdf_url`
2. OpenAlex recovery from `paper.openalex_id`
3. arXiv lookup by DOI
4. Unpaywall lookup by DOI
5. fail

EZproxy must be removed from the active download order.

## Context

The current downloader already recovers some open-access PDFs through saved URLs and OpenAlex metadata, but it still fails for many DOI-only records. Testing on the school server showed three distinct cases:

- some publisher URLs are directly downloadable
- some publisher URLs reject programmatic requests
- many papers expose no OpenAlex PDF URL at all

EZproxy authentication is currently unreliable in this environment and is no longer part of the intended workflow.

## Design

### Resolver Order

`resolve()` in `nexus_paper_fetcher/download/downloader.py` remains the single orchestration point for PDF resolution.

It should attempt, in order:

1. existing `paper.open_access_pdf_url`
2. OpenAlex lookup from `paper.openalex_id`
3. DOI -> arXiv lookup
4. DOI -> Unpaywall lookup
5. return failed `ManifestEntry`

### arXiv DOI Resolver

Add a helper in `downloader.py`:

`async def _find_arxiv_pdf_by_doi(session: httpx.AsyncClient, doi: Optional[str]) -> str | None`

Responsibilities:

- return `None` immediately when DOI is missing
- query arXiv using the DOI as the search key
- parse the returned feed
- accept a result only when the returned DOI matches the requested DOI after normalization
- convert the arXiv identifier into `https://arxiv.org/pdf/<id>.pdf`

Normalization rules:

- lowercase
- strip surrounding whitespace
- remove `https://doi.org/` and `http://doi.org/`

### Unpaywall DOI Resolver

Add a helper in `downloader.py`:

`async def _find_unpaywall_pdf_by_doi(session: httpx.AsyncClient, doi: Optional[str], email: str) -> str | None`

Responsibilities:

- return `None` immediately when DOI is missing
- query Unpaywall with the normalized DOI and `email=weiy@ohsu`
- inspect best OA location first, then any OA locations
- prefer a direct PDF URL when present
- allow landing-page URLs to be ignored unless they resolve to a PDF through the existing PDF validator

The helper should treat malformed payloads, 404s, timeouts, and non-PDF end responses as misses, not hard failures.

### Runtime Simplification

Remove EZproxy from active runtime behavior:

- no `EZProxySession` setup in `download/pipeline.py`
- no `ezproxy` branch in `resolve()`
- no `--skip-ezproxy` behavior in the CLI
- no `"ezproxy"` source label in manifest logic

The download command should become purely open-access oriented.

## Error Handling

- all resolver helpers return `None` on failure
- `_fetch_url()` remains the only place that validates final content as a PDF
- download logging should continue to report one line per paper and the chosen source when successful

## Testing

Add tests for:

- arXiv DOI lookup success
- arXiv DOI lookup miss on DOI mismatch
- Unpaywall DOI lookup success
- Unpaywall DOI lookup miss when only a landing page or no PDF is available
- pipeline-level DOI-only paper recovery through the new fallback chain
- CLI behavior after removing EZproxy support

## Scope Boundaries

In scope:

- downloader resolver order
- DOI-based OA helpers
- associated tests
- CLI/doc cleanup for EZproxy removal

Out of scope:

- publisher-specific scraping
- browser automation
- credential-based access
- fetch-phase metadata changes beyond what already exists
