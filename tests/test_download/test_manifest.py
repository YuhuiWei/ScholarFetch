from __future__ import annotations
import json
from pathlib import Path
from scholar_fetch.download.manifest import (
    Manifest, ManifestEntry, load_manifest, save_manifest,
)


def _entry(paper_id: str, status="success", rank=1) -> ManifestEntry:
    return ManifestEntry(
        paper_id=paper_id,
        title=f"Paper {paper_id}",
        rank=rank,
        score=0.9,
        status=status,
        source_used="arxiv" if status == "success" else None,
        file_path=f"/papers/rank_01_paper.pdf" if status == "success" else None,
        file_size_kb=500 if status == "success" else None,
    )


def test_round_trip(tmp_path):
    path = tmp_path / "manifest.json"
    manifest = Manifest(entries=[_entry("abc123"), _entry("def456", status="failed")])
    save_manifest(manifest, path)
    loaded = load_manifest(path)
    assert len(loaded.entries) == 2
    assert loaded.entries[0].paper_id == "abc123"
    assert loaded.entries[1].status == "failed"


def test_load_missing_file(tmp_path):
    path = tmp_path / "nonexistent.json"
    manifest = load_manifest(path)
    assert manifest.entries == []


def test_successful_ids():
    manifest = Manifest(entries=[
        _entry("abc", status="success"),
        _entry("def", status="failed"),
        _entry("ghi", status="success"),
    ])
    assert manifest.successful_ids() == {"abc", "ghi"}


def test_upsert_new_entry():
    manifest = Manifest()
    manifest.upsert(_entry("abc"))
    assert len(manifest.entries) == 1
    assert manifest.entries[0].paper_id == "abc"


def test_upsert_replaces_existing():
    manifest = Manifest(entries=[_entry("abc", status="failed")])
    manifest.upsert(_entry("abc", status="success"))
    assert len(manifest.entries) == 1
    assert manifest.entries[0].status == "success"


def test_by_paper_id():
    manifest = Manifest(entries=[_entry("abc"), _entry("def", status="failed")])
    index = manifest.by_paper_id()
    assert set(index.keys()) == {"abc", "def"}
    assert index["def"].status == "failed"


def test_atomic_write_no_tmp_left(tmp_path):
    path = tmp_path / "manifest.json"
    save_manifest(Manifest(entries=[_entry("abc")]), path)
    assert path.exists()
    assert not (tmp_path / "manifest.json.tmp").exists()


def test_load_legacy_manifest_ezproxy_source_normalized(tmp_path):
    path = tmp_path / "manifest.json"
    path.write_text(
        json.dumps(
            {
                "entries": [
                    {
                        "paper_id": "legacy1",
                        "title": "Legacy Paper",
                        "rank": 1,
                        "score": 0.8,
                        "status": "success",
                        "source_used": "ezproxy",
                        "file_path": "/papers/legacy1.pdf",
                        "file_size_kb": 123,
                        "error": None,
                    }
                ]
            }
        )
    )
    manifest = load_manifest(path)
    assert len(manifest.entries) == 1
    assert manifest.entries[0].status == "success"
    assert manifest.entries[0].source_used == "open_access_url"
