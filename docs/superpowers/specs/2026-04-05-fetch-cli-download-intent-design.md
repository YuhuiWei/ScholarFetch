# Fetch CLI Download Intent Design

## Goal

Extend the integrated workflow on `feature/integrated-fetch-download-workflow`
so `nexus fetch "..."` becomes the single human-facing entrypoint for:

1. plain search followed by an optional interactive download decision
2. natural-language search-plus-download queries such as
   `download 10 papers about graph transformers`
3. downloading from an existing Phase 1 results JSON file passed to `fetch`

The implementation must preserve the existing workflow rule that a paper lookup
with `not_found=True` never auto-downloads closest-match results.

## Context

The branch already contains:

- an integrated search-plus-download workflow API in `workflow.py`
- CLI wiring for explicit flags such as `--download`
- a standalone `nexus download <results.json>` command

What is still missing is CLI behavior that feels natural for humans when they
type one free-form query into `nexus fetch`.

The desired UX is:

- if the user types a normal search query, search first and then ask whether to
  download
- if the user types a query that explicitly asks to download papers, treat that
  as an integrated workflow request automatically
- if the user gives a search-results JSON path to `fetch`, route directly into
  the download pipeline instead of running search again

## Command Behavior

`nexus fetch` remains the only entrypoint for these human workflows. It gains
three internal routing paths.

### 1. Search Then Prompt

Input example:

- `nexus fetch "graph transformers for molecular property prediction"`

Behavior:

1. parse the query as search
2. run search and save full ranked JSON
3. show the ranked preview
4. ask whether to download the search result
5. if yes, ask where to save files
6. ask how many ranked papers to download
7. run download

### 2. Search Plus Download From Natural Language

Input example:

- `nexus fetch "download 10 papers about graph transformers"`

Behavior:

1. parse the query as a domain search with explicit download intent
2. run search and save full ranked JSON
3. show the ranked preview
4. skip the "do you want to download?" confirmation, because the query already
   answered it
5. ask for output directory if none was supplied by flags or query-derived
   defaults
6. use the parsed download limit if available
7. run download

### 3. Download From Existing Results JSON

Input examples:

- `nexus fetch results/graph_transformers.json`
- `nexus fetch "results/graph_transformers.json"`

Behavior:

1. detect that the input resolves to an existing `.json` file
2. skip NLP parsing, search preparation, and search execution
3. route straight into the same downloader used by `nexus download`
4. if needed, ask where to save files and how many top results to download

This mode is a UX alias for the standalone downloader, not a separate pipeline.

## Parsing Contract

The existing `SearchQuery` parsing already distinguishes:

- `query_intent="domain_search"`
- `query_intent="paper_lookup"`

That search intent should remain intact. The extension adds a workflow-level
intent layer describing what should happen after or instead of search.

Required workflow-level fields:

- `download_requested: bool`
- `download_top_n: int | None`
- `results_file: str | None`

Examples:

- `"graph transformers"`
  - `query_intent="domain_search"`
  - `download_requested=False`
  - `download_top_n=None`
  - `results_file=None`

- `"download 10 papers about graph transformers"`
  - `query_intent="domain_search"`
  - `download_requested=True`
  - `download_top_n=10`
  - `results_file=None`

- `'download the paper "Attention Is All You Need"'`
  - `query_intent="paper_lookup"`
  - `download_requested=True`
  - `download_top_n=None`
  - `results_file=None`

- `"results/graph_transformers.json"` when that file exists
  - `results_file="results/graph_transformers.json"`
  - search parsing is bypassed

The NLP/parser layer should be the source of truth for natural-language download
intent so the CLI and Python API share one contract.

## Workflow Routing

The workflow layer should own routing, not the CLI command body.

Required routing decisions:

- if `results_file` is set, run download-from-file flow
- otherwise, run search flow
- after search:
  - if `download_requested=False`, prompt interactively whether to download
  - if `download_requested=True`, skip that prompt and continue to download

This keeps CLI behavior and API behavior aligned.

## Paper Lookup Rule

Paper lookup keeps its current ranking semantics:

- exact title matches first
- closest matches when no exact title exists
- `not_found=True` when only approximate matches exist

Download rule:

- if the search result is a paper lookup and `not_found=True`, the workflow
  still saves and returns the closest matches
- but it must not auto-download those matches, even when download was requested
  by query text or CLI flags

This prevents unintended downloads for approximate title matches.

## CLI Prompting Rules

### Plain search query

Ask:

1. `Download PDFs for these results?`
2. `Download output directory`
3. `How many top papers to download?`

### Explicit download query

Skip:

- `Download PDFs for these results?`

Still ask when needed:

1. `Download output directory`
2. `How many top papers to download?`

If the download count was clearly specified in the query, use it as the default
or direct value instead of forcing the user to re-enter it.

### Existing results JSON path

No search prompt should appear. Only downloader-related prompts may appear.

## API Contract

The Python workflow API must support the same routing behaviors as the CLI:

- plain search with optional post-search download prompt behavior when
  interactive
- search-plus-download driven by parsed workflow intent
- download from an existing results JSON file without requiring the caller to
  invoke a separate CLI command

The returned workflow result should make the chosen path obvious:

- saved results path when search ran
- download requested/executed booleans
- download directory and limit when used
- no download execution for lookup `not_found=True`

## Testing

Required test coverage:

- normal search query prompts whether to download after search completes
- natural-language query like `download 10 papers about X` triggers integrated
  download automatically
- explicit download query still asks for output directory when needed
- `fetch results.json` routes directly to download-from-file flow
- paper lookup with `not_found=True` does not auto-download even when the query
  requests download
- existing explicit `--download` workflow behavior keeps working
- CLI tests cover the routing behavior instead of testing only low-level helpers

## Scope Boundaries

In scope:

- extending NLP/workflow parsing for download intent
- routing `fetch` to search or download-from-file
- interactive prompt behavior for post-search download
- results JSON handoff into downloader
- tests, README updates, and `CODEX_CHANGES.md`

Out of scope:

- changing resolver priority inside the downloader
- changing manifest schema
- replacing `nexus download` as a standalone command
- changing `master` before this branch is ready

## Design Decisions

- keep one human-facing command: `nexus fetch`
- make parser/workflow the source of truth for download intent
- treat an existing results JSON path as a first-class `fetch` route
- preserve the `paper_lookup` `not_found=True` safety rule
- reuse the existing downloader rather than creating a new download path
