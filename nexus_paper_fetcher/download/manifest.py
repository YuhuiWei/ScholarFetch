from __future__ import annotations
import os
from pathlib import Path
from typing import Literal, Optional
from pydantic import BaseModel, Field


class ManifestEntry(BaseModel):
    paper_id: str
    title: str
    rank: int
    score: float
    status: Literal["success", "failed", "skipped"]
    source_used: Optional[Literal["open_access_url", "arxiv", "ezproxy"]] = None
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


def load_manifest(path: Path) -> Manifest:
    if not path.exists():
        return Manifest()
    return Manifest.model_validate_json(path.read_text())


def save_manifest(manifest: Manifest, path: Path) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(manifest.model_dump_json(indent=2))
    os.replace(tmp, path)
