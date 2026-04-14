from __future__ import annotations
import re
from datetime import datetime, timezone
from pathlib import Path
from scholar_fetch.models import Paper

_MANUAL_FILENAME = "manual.md"
_PAPER_ID_PATTERN = re.compile(r"\*\*paper_id:\*\*\s+([a-f0-9]+)")

_HEADER = """\
# Manual Download Queue

Papers below could not be auto-downloaded by ScholarFetch.
To download manually:
1. Use the DOI link to access via your institution
2. Drop the PDF into the ScholarWiki manual_inbox/ directory
3. Run `scholarwiki ingest` to register it

"""

_DOWNLOADED_SECTION = """\

---

## Downloaded (0 papers)
<!-- Updated by scholarwiki ingest when manual PDFs are matched -->
"""


def _existing_paper_ids(md_text: str) -> set[str]:
    return set(_PAPER_ID_PATTERN.findall(md_text))


def _format_entry(paper: Paper, rank: int) -> str:
    doi_line = ""
    if paper.doi:
        doi_line = f"- **DOI:** [{paper.doi}](https://doi.org/{paper.doi})\n"
    authors_str = "; ".join(paper.authors[:3]) if paper.authors else "—"
    tags_str = ", ".join(paper.domain_tags) if paper.domain_tags else "—"
    return (
        f"### [Rank {rank}] {paper.title}\n"
        f"{doi_line}"
        f"- **paper_id:** {paper.paper_id}\n"
        f"- **Authors:** {authors_str}\n"
        f"- **Year:** {paper.year or '—'} | **Venue:** {paper.venue or '—'}\n"
        f"- **Tags:** {tags_str}\n"
        f"- **Score:** {paper.scores.composite:.2f}\n"
        f"- **Status:** awaiting manual download\n\n"
    )


def update_manual_md(
    output_dir: Path,
    failed_papers: list[tuple[Paper, int]],
    *,
    source_json: str,
) -> None:
    """Append new pending entries to manual.md; never duplicate by paper_id."""
    md_path = output_dir / _MANUAL_FILENAME
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")

    if md_path.exists():
        existing_text = md_path.read_text()
        already_present = _existing_paper_ids(existing_text)
    else:
        existing_text = None
        already_present = set()

    new_entries = [
        (paper, rank)
        for paper, rank in failed_papers
        if paper.paper_id not in already_present
    ]
    if not existing_text:
        pending_count = len(new_entries)
        header = (
            _HEADER
            + f"Last updated: {now}\n"
            + f"Source: {source_json}\n\n"
            + "---\n\n"
            + f"## Pending ({pending_count} papers)\n\n"
        )
        body = "".join(_format_entry(p, r) for p, r in new_entries)
        md_path.write_text(header + body + _DOWNLOADED_SECTION)
    else:
        # Append new entries before the Downloaded section
        downloaded_marker = "\n---\n\n## Downloaded"
        if downloaded_marker in existing_text:
            split_idx = existing_text.index(downloaded_marker)
            before = existing_text[:split_idx]
            after = existing_text[split_idx:]
        else:
            before = existing_text
            after = ""

        appended = before
        for paper, rank in new_entries:
            appended += _format_entry(paper, rank)

        # Update last-updated timestamp in header
        appended = re.sub(
            r"Last updated: [^\n]+",
            f"Last updated: {now}",
            appended,
        )
        md_path.write_text(appended + after)
