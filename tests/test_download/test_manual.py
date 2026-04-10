import pytest
from pathlib import Path
from nexus_paper_fetcher.download.manual import update_manual_md
from nexus_paper_fetcher.models import Paper


def _make_paper(title, doi=None, rank=1, score=0.80, year=2024,
                venue="Nature", authors=None, domain_tags=None):
    p = Paper.create(
        title=title, doi=doi, year=year, venue=venue,
        authors=authors or ["Smith, J."],
        sources=["openalex"],
    )
    p.scores.composite = score
    p.domain_tags = domain_tags or []
    return p, rank


def test_creates_manual_md_when_missing(tmp_path):
    paper, rank = _make_paper("Liver Atlas", doi="10.1038/s41586-024-xxxxx")
    update_manual_md(tmp_path, [(paper, rank)], source_json="results/liver/2026-04-09_top20.json")
    md = (tmp_path / "manual.md").read_text()
    assert "Liver Atlas" in md
    assert "10.1038/s41586-024-xxxxx" in md
    assert "Pending" in md or "awaiting" in md


def test_does_not_duplicate_existing_entry(tmp_path):
    paper, rank = _make_paper("Liver Atlas", doi="10.1038/s41586-024-xxxxx")
    update_manual_md(tmp_path, [(paper, rank)], source_json="results/liver/2026-04-09_top20.json")
    # Call again with same paper
    update_manual_md(tmp_path, [(paper, rank)], source_json="results/liver/2026-04-09_top20.json")
    md = (tmp_path / "manual.md").read_text()
    assert md.count("Liver Atlas") == 1


def test_appends_new_paper_to_existing_md(tmp_path):
    p1, r1 = _make_paper("Paper One", doi="10.1/one")
    p2, r2 = _make_paper("Paper Two", doi="10.1/two")
    update_manual_md(tmp_path, [(p1, r1)], source_json="results/x/2026-04-09_top20.json")
    update_manual_md(tmp_path, [(p2, r2)], source_json="results/x/2026-04-09_top20.json")
    md = (tmp_path / "manual.md").read_text()
    assert "Paper One" in md
    assert "Paper Two" in md


def test_no_doi_paper_omits_doi_line(tmp_path):
    paper, rank = _make_paper("No DOI Paper", doi=None)
    update_manual_md(tmp_path, [(paper, rank)], source_json="s.json")
    md = (tmp_path / "manual.md").read_text()
    assert "No DOI Paper" in md
    # Should not crash and should not have a broken DOI line
    assert "doi.org/None" not in md
