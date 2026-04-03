from __future__ import annotations
import json
import os
from pathlib import Path
from typing import Literal, Optional
from pydantic import BaseModel, Field


class ManifestEntry(BaseModel):
    paper_id: str
    title: str
    rank: int
    score: float
    status: Literal["success", "failed"]
    source_used: Optional[Literal["open_access_url", "arxiv"]] = None
    file_path: Optional[str] = None
    file_size_kb: Optional[int] = None
    error: Optional[str] = None


class Manifest(BaseModel):
    entries: list[ManifestEntry] = Field(default_factory=list)

    def by_paper_id(self) -> dict[str, ManifestEntry]:
        return {e.paper_id: e for e in self.entries}

    def successful_ids(self) -> set[str]:
        return {e.paper_id for e in self.entries if e.status == "success"}

    def upsert(self, entry: ManifestEntry) -> None:
        for i, existing in enumerate(self.entries):
            if existing.paper_id == entry.paper_id:
                self.entries[i] = entry
                return
        self.entries.append(entry)


def _normalize_legacy_source(source_used: object) -> object:
    if source_used == "ezproxy":
        return "open_access_url"
    return source_used


def _normalize_legacy_manifest_payload(payload: object) -> object:
    if not isinstance(payload, dict):
        return payload

    entries = payload.get("entries")
    if not isinstance(entries, list):
        return payload

    normalized_entries = []
    changed = False
    for entry in entries:
        if not isinstance(entry, dict):
            normalized_entries.append(entry)
            continue
        normalized_source = _normalize_legacy_source(entry.get("source_used"))
        if normalized_source != entry.get("source_used"):
            changed = True
            normalized_entries.append({**entry, "source_used": normalized_source})
        else:
            normalized_entries.append(entry)

    if not changed:
        return payload
    return {**payload, "entries": normalized_entries}


def load_manifest(path: Path) -> Manifest:
    if not path.exists():
        return Manifest()
    payload = json.loads(path.read_text())
    normalized_payload = _normalize_legacy_manifest_payload(payload)
    return Manifest.model_validate(normalized_payload)


def save_manifest(manifest: Manifest, path: Path) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(manifest.model_dump_json(indent=2))
    os.replace(tmp, path)
