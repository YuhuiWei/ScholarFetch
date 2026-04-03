# Codex Change Log

This file records project changes made during Codex sessions.

## 2026-04-01

### Methodology-classifier truncation fix

- Investigated repeated runtime warnings such as:
  - `Methodology classification failed: Unterminated string ...; using heuristic fallback`
- Root cause:
  - the methodology classifier was sending too many papers per batch with long abstracts
  - the model response could be truncated before the JSON finished, which then failed `json.loads(...)`
- Updated `nexus_paper_fetcher/methodology.py` to make the response much smaller and more stable:
  - reduced batch size
  - shortened abstract payload length
  - switched to compact category codes:
    - `R`
    - `V`
    - `D`
    - `M`
  - lowered output-token needs by asking for only the ordered code list instead of repeated category names or extra structure
- Kept the heuristic fallback in place when JSON parsing still fails.
- Added `tests/test_methodology.py` covering:
  - compact-code parsing
  - malformed JSON fallback
- Verified with:
  - `pytest tests/test_methodology.py tests/test_pipeline.py tests/test_scoring.py -q`

### Hybrid planning, ranking, and methodology update

- Reworked query planning again so ranking intent such as `top` and `best` is treated as ranking preference instead of search criteria contamination.
- Updated `nexus_paper_fetcher/domain.py` to:
  - strip ranking-only language from retrieval planning
  - let the OpenAI planner return:
    - multiple domain categories
    - a cleaned search seed
    - required terms
    - optional terms
  - preserve a simple required-vs-optional relationship instead of flattening everything into one keyword list immediately
- Added hybrid-domain support:
  - when a query spans multiple domains such as `cs_ml` and `biology`, the system now keeps the domain mix and averages the scoring matrices instead of forcing a single-domain weight profile
- Updated venue expansion so publisher-style requests such as `Nature` expand into a broader venue family including:
  - `Nature`
  - `Nature Communications`
  - `Nature Neuroscience`
  - `Scientific Reports`
  - related Nature-family journals
- Updated `nexus_paper_fetcher/scoring/citation.py` to use a stronger logarithmic citation scale that blends:
  - batch-relative log scaling
  - absolute order-of-magnitude scaling
  This preserves the practical distinction between papers with roughly `10^2` and `10^5` citations.
- Added `nexus_paper_fetcher/methodology.py` with title+abstract methodology categorization:
  - uses `gpt-4o-mini` when `OPENAI_API_KEY` is available
  - falls back to heuristics when it is not
  - categories: `research`, `review`, `data`, `method`
- Updated `nexus_paper_fetcher/pipeline.py` so:
  - methodology classification runs before scoring
  - explicit publication-category requests still filter the candidate pool
  - default `primary_research` is now a soft preference rather than a hard filter
- Updated `nexus_paper_fetcher/scoring/scorer.py` so:
  - hybrid domain weights are averaged
  - methodology contributes a bonus/penalty during ranking
  - recency scoring also respects hybrid-domain decay
- Updated `nexus_paper_fetcher/cli.py` so approval now shows:
  - required criteria
  - optional criteria
  rather than a single undifferentiated keyword list
- Updated fallback NLP behavior in `nexus_paper_fetcher/nlp.py` so `top` / `best` queries automatically bias ranking toward citation and impact instead of being treated as literal retrieval intent.
- Added and updated tests covering:
  - OpenAI search planning with domain mixtures
  - Nature publisher-group expansion
  - hybrid-domain weight averaging
  - stronger logarithmic citation separation
  - softened default primary-research handling
- Verified with:
  - `pytest tests/test_domain.py tests/test_nlp.py tests/test_models.py tests/test_fetchers.py tests/test_pipeline.py tests/test_scoring.py tests/test_cli.py -q`

### OpenAI search-criteria planner

- Reworked query preparation so OpenAI is now used to understand the user request and generate structured search criteria, instead of only producing expanded keywords.
- Added `plan_search_criteria()` in `nexus_paper_fetcher/domain.py`.
- The new OpenAI planner returns:
  - inferred domain category
  - required search terms
  - optional search terms
- Query preparation now builds the final upstream search text from those planned criteria plus any venue constraints.
- The non-OpenAI fallback path still uses the previous keyword-extraction behavior.
- Updated CLI messaging to present the generated list as `search criteria` instead of `keywords`, while keeping the same approve/remove/regenerate/add flow.
- Updated pipeline logging to print `search plan...` instead of `keyword plan...`.
- Added tests covering:
  - OpenAI search-criteria planning
  - `prepare_query()` using the new planner
- Verified with:
  - `pytest tests/test_domain.py tests/test_nlp.py tests/test_models.py tests/test_fetchers.py tests/test_pipeline.py tests/test_scoring.py tests/test_cli.py -q`

### Venue and publisher-name retrieval fix

- Fixed a remaining venue-resolution bug that affected queries such as:
  - `find 10 best paper from neurips`
  - `find 10 best paper from nature`
- Updated `nexus_paper_fetcher/domain.py` so:
  - default search-text construction now uses plain term expansion instead of implicitly joining everything with `AND`
  - exact venue names are treated deterministically and are no longer broadened by OpenAI into publisher families or unrelated venue sets
  - broad venue groups such as `top tier cs conference` still expand into explicit venue lists
  - raw venue preferences are appended to upstream search text so venue-only requests are more likely to retrieve the right candidate set before post-filtering
- Updated `nexus_paper_fetcher/pipeline.py` so venue matching now handles proceedings-style venue strings more robustly using token-set matching in addition to the previous substring and fuzzy checks.
- Updated `nexus_paper_fetcher/nlp.py` so fallback parsing can recognize exact venue names such as `NeurIPS` and `Nature`, and so boolean keyword logic defaults to `AUTO` unless the user explicitly asks for `AND` or `OR`.
- Updated `nexus_paper_fetcher/cli.py` so the keyword-approval loop rebuilds search text using the same venue-aware planning path as the main pipeline.
- Added and updated tests covering:
  - default search-text behavior without implicit boolean operators
  - venue-aware search-text construction
  - exact `Nature` venue handling
  - `NeurIPS` alias expansion
  - proceedings-style venue matching
  - fallback NLP extraction of exact venues
- Verified with:
  - `pytest tests/test_domain.py tests/test_nlp.py tests/test_models.py tests/test_fetchers.py tests/test_pipeline.py tests/test_scoring.py tests/test_cli.py -q`

### Publication-category filtering

- Added `publication_categories` to `SearchQuery` with default `primary_research`.
- Added `publication_type` to `Paper`.
- Extended NLP parsing so requests can express publication categories such as:
  - primary research
  - review
  - methods
  - data
  - perspective
  - comment
- Added publication-category filtering in `nexus_paper_fetcher/pipeline.py`.
- Default searches now keep primary research and filter out obvious review, perspective, and comment-style papers unless the user asks for those categories.

### Exact-match-first specific paper search

- Refined specific-paper lookup in `nexus_paper_fetcher/pipeline.py` so named-paper search now tries exact matching first with a small fetch budget per source.
- If a requested paper is found in an early source, the pipeline stops widening the search for that title instead of doing a full top-100 style search.
- If a paper is still not found, similar-paper suggestions are returned as before.

### Boolean keyword logic

- Added `keyword_logic` to `SearchQuery`.
- Extended NLP parsing so user intent can express `AND` or `OR` keyword relationships.
- Updated search-text construction in `nexus_paper_fetcher/domain.py` so expanded search text preserves the requested boolean relationship.

### Venue alias expansion and Semantic Scholar zero-result fallback

- Improved venue expansion so venue filters now add aliases for common conference names such as `NeurIPS` and its long-form title.
- This fixes cases where venue filtering previously returned zero papers because the fetched venue name used a different alias than the user request.
- Added a second Semantic Scholar fallback path:
  - if the expanded query returns zero papers on the first page, retry once with the raw query text

### Keyword approval workflow

- Added an interactive approval loop in `nexus_paper_fetcher/cli.py` before expanded keywords are used for search.
- The CLI now shows the proposed keywords and supports:
  - remove and proceed
  - remove and regenerate
  - add and proceed
  - proceed
- Regeneration now respects an exclusion list so removed keywords are not proposed again in the next round.
- Specific-paper lookups automatically disable keyword expansion so they go straight to paper search.

### Specific paper lookup flow

- Added support for `paper_titles` in `SearchQuery`.
- Added specific-paper lookup handling in `nexus_paper_fetcher/pipeline.py`.
- When the user asks for one or more named papers:
  - the system fetches by paper title directly
  - matched papers are returned first
  - if a requested paper is not found, up to 3 similar paper titles are returned
- Added `PaperLookupResult` and stored lookup details in `RunResult.paper_lookup`.

### User-controlled scoring preferences

- Added `weight_preferences` to `SearchQuery`.
- Extended NLP parsing so natural-language requests can express scoring preferences such as:
  - more cited
  - more relevant
  - high impact
  - more recent
- Added `resolve_weights()` in `nexus_paper_fetcher/scoring/scorer.py`.
- The pipeline now records the applied scoring weights in `RunResult.applied_weights`.

### Venue and journal set selection

- Added `venue_preferences`, `venue_filters`, and `venue_filter_strategy` to `SearchQuery`.
- Added venue expansion in `nexus_paper_fetcher/domain.py`.
- Broad venue-group requests can now be expanded into explicit venues, with OpenAI when available and a deterministic fallback map otherwise.
- Added post-fetch venue filtering in `nexus_paper_fetcher/pipeline.py`.
- The pipeline now records the applied venue filters in `RunResult.venue_filters_applied`.

### Semantic Scholar regression fix

- Investigated the new Semantic Scholar `HTTP 400` failures after keyword-planning changes.
- Adjusted `nexus_paper_fetcher/fetchers/semantic_scholar.py` to stop requesting the newly added `keywords` and `fieldsOfStudy` response fields on `/graph/v1/paper/search`.
- Added a defensive fallback for Semantic Scholar:
  - if the expanded search text gets a `400`, retry once with the raw query text
- Updated `nexus_paper_fetcher/fetchers/base.py` so HTTP errors log part of the response body for easier diagnosis.

### Keyword expansion controls

- Added `keyword_count` to `SearchQuery` in `nexus_paper_fetcher/models.py`.
- Default keyword expansion is now `5`.
- Added support for disabling expansion with `keyword_count = 0`.
- Added support for bounded keyword counts with internal clamping.
- Updated `nexus_paper_fetcher/nlp.py` so natural-language parsing can extract:
  - exact keyword counts
  - `no keyword expansion`
  - `less` keyword expansion
  - `more` keyword expansion
- Updated `nexus_paper_fetcher/domain.py` so query preparation respects the requested keyword count.
- Updated `nexus_paper_fetcher/pipeline.py` to pass the requested keyword count into query planning and print `keyword plan... disabled` when expansion is turned off.
- Updated `nexus_paper_fetcher/cli.py` to add:
  - `--keyword-count`
  - `--no-keyword-expansion`
  for both `fetch` and `shell`.

### Query planning and domain behavior

- Added explicit query planning in `nexus_paper_fetcher/domain.py`.
- When `OPENAI_API_KEY` is present, the project now:
  - uses OpenAI to classify the query domain
  - expands search keywords constrained by the classified field
- When `OPENAI_API_KEY` is not present, the project now:
  - falls back to hardcoded domain detection
  - derives fallback keywords from the raw query
- Added `prepare_query()` to return domain, expanded keywords, planned search text, and keyword strategy.

### Searchable metadata and ranking

- Extended `SearchQuery` in `nexus_paper_fetcher/models.py` with:
  - `expanded_keywords`
  - `search_text`
  - `keyword_strategy`
- Extended `Paper` with a `keywords` field.
- Added `Paper.searchable_text()` so ranking can use:
  - title only when abstract and keywords are empty
  - title, abstract, and keywords when abstract or keywords are available
- Updated relevance scoring in `nexus_paper_fetcher/scoring/scorer.py` to score against `Paper.searchable_text()`.

### Fetcher behavior

- Updated `nexus_paper_fetcher/fetchers/openalex.py` to:
  - extract keywords from OpenAlex keyword or concept metadata
  - use planned `search_text` for upstream search
- Updated `nexus_paper_fetcher/fetchers/semantic_scholar.py` to:
  - request keyword-related fields
  - extract keywords from Semantic Scholar metadata
  - use planned `search_text` for upstream search
- Updated `nexus_paper_fetcher/fetchers/openreview.py` to capture keywords when present on notes.

### Pipeline and CLI

- Updated `nexus_paper_fetcher/pipeline.py` to:
  - prepare the query before fetching
  - persist keyword-planning details on the query object
  - print keyword-plan status in CLI output
- Refactored `nexus_paper_fetcher/cli.py` around a shared `_execute_fetch()` helper.
- Added a long-running interactive CLI command:
  - `nexus shell`
- `nexus shell` accepts repeated queries until `quit` or `exit` and writes one result file per query.

### Tests

- Added and updated tests covering:
  - domain classification and keyword expansion behavior
  - keyword count parsing from NLP responses
  - specific-paper parsing fields from NLP responses
  - publication-category parsing
  - new `SearchQuery` and `Paper` fields
  - richer searchable text used for scoring
  - fetcher keyword parsing
  - Semantic Scholar fallback from expanded query to raw query after `400`
  - Semantic Scholar fallback from expanded query to raw query after zero results
  - specific-paper lookup behavior
  - exact-match-first specific-paper short-circuiting
  - score-weight preference resolution
  - venue-filter application
  - venue alias expansion
  - interactive CLI behavior
- Added `tests/test_cli.py`.
- Added `tests/test_nlp.py`.
- Verified with:
  - `pytest tests/test_domain.py tests/test_nlp.py tests/test_models.py tests/test_fetchers.py tests/test_pipeline.py tests/test_scoring.py tests/test_cli.py -q`

### Workflow note

- Going forward, each Codex change in this project should be accompanied by an update to this file describing what changed.

## 2026-04-03

### Elsevier subscription download fallback redo

- Replayed the verified Elsevier subscription-download implementation into the main project worktree on branch `codex/elsevier-subscription-downloads` after recovering the clean feature branch left by the crashed session.
- Updated `nexus_paper_fetcher/download/downloader.py` so the download order is now:
  - saved `open_access_pdf_url`
  - OpenAlex `openalex_id` recovery
  - DOI to arXiv
  - DOI to Unpaywall
  - Elsevier full-text XML by DOI for `10.1016/...` papers when `ELSEVIER_API_KEY` is set
- Added stricter XML parsing and validation for Elsevier responses:
  - parses XML safely
  - requires a `full-text-retrieval-response` root element
  - requires `coredata` to be present before treating the response as a successful full-text download
- Updated file writing so successful downloads can now be saved as either:
  - `.pdf`
  - `.xml`
- Updated `nexus_paper_fetcher/download/manifest.py` to allow `source_used: "elsevier_api"` for successful manifest entries.
- Updated `nexus_paper_fetcher/download/cli.py` help text so `--output-dir` is described as a directory for downloaded files rather than PDFs only.
- Added downloader coverage in `tests/test_download/test_downloader.py` for:
  - successful Elsevier XML fallback
  - skipping Elsevier when `ELSEVIER_API_KEY` is absent
  - refusing Elsevier calls for non-Elsevier DOI namespaces
  - tighter validation around acceptable Elsevier XML responses
- Added pipeline coverage in `tests/test_download/test_pipeline.py` for:
  - end-to-end XML fallback after OA recovery paths fail
  - manifest persistence for `.xml` downloads
  - CLI help text reflecting mixed download outputs
- Updated `README.md`, `PHASE_2_SUMMARY.md`, and `CLAUDE.md` to document:
  - the new fallback order
  - `ELSEVIER_API_KEY`
  - mixed `.pdf` and `.xml` download directories
  - the Elsevier `view=FULL` API request
- Verified with:
  - `pytest tests/test_download -q`
