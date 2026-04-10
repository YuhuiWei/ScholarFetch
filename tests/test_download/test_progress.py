import pytest
from pathlib import Path
from nexus_paper_fetcher.download.progress import (
    DownloadProgress, load_progress, save_progress,
)


def test_progress_empty_on_missing_file(tmp_path):
    p = load_progress(tmp_path / "progress.json")
    assert p.entries == {}


def test_progress_upsert_and_get():
    prog = DownloadProgress()
    prog.upsert("id1", "success", "/papers/paper1.pdf")
    entry = prog.get("id1")
    assert entry is not None
    assert entry.status == "success"
    assert entry.file_path == "/papers/paper1.pdf"


def test_progress_upsert_overwrites():
    prog = DownloadProgress()
    prog.upsert("id1", "failed")
    prog.upsert("id1", "success", "/papers/paper1.pdf")
    assert prog.get("id1").status == "success"


def test_progress_roundtrips_to_disk(tmp_path):
    path = tmp_path / "download_progress.json"
    prog = DownloadProgress()
    prog.upsert("id1", "success", "/papers/a.pdf")
    prog.upsert("id2", "failed")
    save_progress(prog, path)
    loaded = load_progress(path)
    assert loaded.get("id1").status == "success"
    assert loaded.get("id2").status == "failed"


def test_progress_save_is_atomic(tmp_path):
    """save_progress writes via .tmp then renames — no partial writes."""
    path = tmp_path / "download_progress.json"
    prog = DownloadProgress()
    prog.upsert("id1", "success")
    save_progress(prog, path)
    assert path.exists()
    assert not (tmp_path / "download_progress.tmp").exists()
