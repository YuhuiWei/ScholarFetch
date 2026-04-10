import json
from pathlib import Path
from datetime import datetime, timezone
from nexus_paper_fetcher.models import Paper, RunResult, SearchQuery
from nexus_paper_fetcher.search import search_results, SearchHit


def _write_result(tmp_path: Path, papers: list[Paper], slug: str) -> Path:
    sq = SearchQuery(query=slug.replace("-", " "), top_n=len(papers))
    result = RunResult(
        query=slug, domain_category=["biology"],
        params=sq, sources_used=["openalex"],
        papers=papers, timestamp=datetime.now(timezone.utc),
    )
    path = tmp_path / "results" / slug / "2026-04-09_top10.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(result.model_dump(mode="json"), default=str))
    return path


def _make_paper(title, doi=None, abstract="", domain_tags=None, download_status=None):
    p = Paper.create(title=title, doi=doi, year=2024, sources=["openalex"], abstract=abstract)
    p.domain_tags = domain_tags or []
    p.download_status = download_status
    return p


def test_search_finds_by_title_keyword(tmp_path):
    p = _make_paper("FlashAttention: Fast Memory-Efficient Attention")
    _write_result(tmp_path, [p], "attention-mechanisms")
    hits = search_results("flash", results_dir=tmp_path / "results")
    assert any("FlashAttention" in h.paper.title for h in hits)


def test_search_finds_by_abstract(tmp_path):
    p = _make_paper("Obscure Title", abstract="This paper uses CRISPR editing technology")
    _write_result(tmp_path, [p], "crispr")
    hits = search_results("crispr", results_dir=tmp_path / "results")
    assert len(hits) >= 1


def test_search_not_downloadable_filter(tmp_path):
    p_success = _make_paper("Downloaded", download_status="success")
    p_failed = _make_paper("Failed Paper", download_status="failed")
    p_none = _make_paper("Pending Paper", download_status=None)
    _write_result(tmp_path, [p_success, p_failed, p_none], "mixed")
    hits = search_results("", results_dir=tmp_path / "results", not_downloadable=True)
    titles = {h.paper.title for h in hits}
    assert "Downloaded" not in titles
    assert "Failed Paper" in titles
    assert "Pending Paper" in titles


def test_search_downloaded_filter(tmp_path):
    p_success = _make_paper("Downloaded", download_status="success")
    p_failed = _make_paper("Failed Paper", download_status="failed")
    _write_result(tmp_path, [p_success, p_failed], "mixed")
    hits = search_results("", results_dir=tmp_path / "results", downloaded_only=True)
    assert all(h.paper.download_status == "success" for h in hits)


def test_search_domain_filter(tmp_path):
    p1 = _make_paper("Bio Paper")
    p2 = _make_paper("CS Paper")
    _write_result(tmp_path, [p1], "biology-domain")
    _write_result(tmp_path, [p2], "cs-domain")
    hits = search_results("", results_dir=tmp_path / "results", domain_slug="biology-domain")
    titles = {h.paper.title for h in hits}
    assert "Bio Paper" in titles
    assert "CS Paper" not in titles


def test_search_hit_includes_source_file(tmp_path):
    p = _make_paper("Test Paper")
    result_file = _write_result(tmp_path, [p], "test-query")
    hits = search_results("test", results_dir=tmp_path / "results")
    assert any(h.source_file == result_file for h in hits)
