# Integrated Fetch Download Workflow Design

## Goal

Integrate the current Phase 1 paper search flow and Phase 2 full-text download flow into a single workflow owned by a Python API, while keeping `nexus fetch` as the user-facing entry point.

The new behavior must support two usage patterns:

1. interactive CLI usage for humans
2. non-interactive programmatic usage from other projects

In both cases, the workflow should:

1. run paper search
2. save the full ranked result JSON
3. expose a top-10 preview for humans
4. optionally run download against the ranked result set

## Context

The current implementation has a hard boundary between:

- Phase 1: `nexus fetch` -> ranked JSON
- Phase 2: `nexus download <results.json>` -> downloaded files + `manifest.json`

That split works for manual operation but is awkward for the next planned pipeline stage. The downstream citation-processing project will extract citations from downloaded papers, filter common citations, and hand them back to this project for additional search and download. That caller cannot depend on terminal prompts and needs a stable Python API that directly runs the combined workflow with explicit settings.

The CLI still needs interactive behavior for human users, but the CLI must become a wrapper over the Python workflow instead of being the source of truth.

## Design

### Ownership

Introduce a new workflow module, expected at `nexus_paper_fetcher/workflow.py`, as the orchestration layer for the combined flow.

Responsibility split:

- `nexus_paper_fetcher/pipeline.py`
  - stays focused on search, ranking, and returning `RunResult`
- `nexus_paper_fetcher/download/pipeline.py`
  - stays focused on downloading papers from a ranked result set and returning a manifest
- `nexus_paper_fetcher/workflow.py`
  - owns search result persistence, preview selection, interactive prompting decisions, and optional download execution
- `nexus_paper_fetcher/cli.py`
  - translates CLI flags and prompts into workflow API calls

This keeps Phase 1 and Phase 2 independently testable while providing one stable integration point for future automation.

### Workflow API

Add a Python-first async entry point in `nexus_paper_fetcher/workflow.py`. The exact function name can be decided during implementation, but it should represent the full fetch workflow, for example:

`async def run_fetch_workflow(...) -> FetchWorkflowResult`

Required capabilities:

- accept a raw query or a prepared `SearchQuery`
- accept the same search overrides currently supported by `nexus fetch`
- support `interactive=True | False`
- support `download=True | False`
- support `download_limit`
- support `output_dir`
- support explicit search result output path override

Behavior:

- always run search first
- always persist the full ranked search result JSON
- always return the saved result path
- optionally run download
- never prompt when `interactive=False`

The workflow result object should carry enough information for both CLI and other programs:

- full `RunResult`
- preview papers shown to humans
- saved search result path
- whether download was requested
- whether download was executed
- selected download limit
- selected download directory
- download manifest or manifest path when download ran

### Interactive CLI Flow

`nexus fetch` remains the entry point for humans, but it now runs the combined workflow.

For domain searches:

1. run search with a ranked result set larger than the preview
2. save the full ranked result JSON
3. print only the top 10 papers as example preview
4. print the path to the full search result JSON
5. ask whether to proceed with download
6. if yes, ask where to store downloaded files
7. ask how many papers to download
8. download in ranked order until the requested count is reached

For single-paper or batch paper-finding queries:

1. run search
2. save the ranked result JSON
3. print the found results
4. print the path to the saved result JSON
5. ask whether to proceed with download
6. if yes, ask where to store downloaded files
7. ask how many found papers to download, defaulting to all found results
8. download from the found result set in ranked order

The CLI should preserve current search controls like domain override, year filters, author filter, journal filter, fetch-per-source, and keyword expansion controls.

### Non-Interactive Flow

Other programs must be able to call the combined workflow without any terminal interaction.

When `interactive=False`:

- the workflow must not prompt
- the caller decides whether download should run
- the caller provides download settings directly
- an explicit output directory should be required whenever download is requested

This mode supports the citation-processing follow-up flow:

1. another project extracts citations from downloaded papers
2. that project filters common citations
3. it calls this project through the Python API or CLI
4. this project searches those titles or queries and downloads papers directly into the caller-specified directory

### CLI Flags

Keep `nexus fetch` as the primary command and add non-interactive controls so the CLI can also be used safely by automation.

Expected additions:

- `--download`
  - run download after search without interactive confirmation
- `--download-top N`
  - limit download count
- `--output-dir PATH`
  - destination directory for downloaded papers
- `--yes` or `--non-interactive`
  - disable prompts and require CLI-provided decisions

Human default behavior:

- search always runs
- result JSON is always saved
- top-10 preview is shown
- confirmation prompt is shown before download

Automation default behavior:

- prompts disabled
- missing required download arguments should fail fast with a clear error

### Search Result Sizing

The human preview and the stored ranked result should not be the same concept.

Requirements:

- preview size is fixed at 10 for human CLI output
- the saved ranked result JSON contains the full search result set returned by the search pipeline
- download decisions operate on the full saved ranked result set, not only on the previewed 10 papers

For domain search, this means the user can preview 10 examples and still choose to download more than 10 papers from the larger ranked set.

### Data Flow

The combined workflow should follow this sequence:

1. parse query into `SearchQuery`
2. apply CLI or caller overrides
3. prepare query
4. run search pipeline
5. save full `RunResult` to JSON
6. derive preview subset for presentation
7. decide whether to download
8. if download is enabled, call the download pipeline on the ranked result set with the selected limit and output directory
9. return a structured workflow result to the caller

The download pipeline should be able to consume an in-memory `RunResult` directly or an equivalent ranked result object. Implementation can still reuse file-based entry points where convenient, but the Python orchestration API should not be forced to round-trip through the CLI to trigger download.

### Error Handling

Search and download should remain separate failure domains.

Requirements:

- if search returns no papers, the workflow should fail before any download prompt or download attempt
- if search succeeds and download is declined, the workflow is still successful
- if search succeeds and download runs, download outcomes should be reflected through manifest data without invalidating the saved ranked result
- non-interactive mode should reject missing required arguments for download before attempting prompts
- interactive mode should use the configured default download directory when the user accepts the suggested default

The saved ranked result JSON is the durable artifact for the search stage and should still exist even when download later fails partially or completely.

### Testing

Keep existing search and download tests focused on their own modules and add workflow-level coverage for the integration contract.

Required test coverage:

- interactive search flow that saves full results and stops when the user declines download
- interactive search flow that confirms download and passes the selected directory and limit into the downloader
- non-interactive workflow that downloads immediately when `download=True`
- non-interactive workflow that fails fast when download is requested without required arguments
- domain search preview limited to 10 while the saved result contains more papers
- paper lookup flow requiring confirmation before download
- CLI coverage verifying that `nexus fetch` delegates to the workflow layer instead of owning integration logic itself

## Design Decisions

- Python API is the source of truth for the integrated workflow
- CLI wraps the workflow API rather than orchestrating search and download directly
- search results are always saved before download decisions
- human preview is capped at 10 and is not the full ranked result
- interactive and non-interactive modes share one orchestration path
- Phase 1 and Phase 2 remain independently testable modules behind the orchestration layer

## Scope Boundaries

In scope:

- integrated workflow module
- `nexus fetch` interactive continuation into download
- non-interactive CLI mode for automation
- Python API for downstream projects
- workflow result model and tests

Out of scope:

- citation extraction or citation deduplication itself
- Phase 3 paper processing
- changes to downloader resolver order or manifest schema unrelated to orchestration
- replacing `nexus download` as a standalone command
