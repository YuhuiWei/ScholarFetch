from __future__ import annotations
import os
from pathlib import Path
from typing import Literal, Optional
from pydantic import BaseModel

ProgressStatus = Literal["success", "failed", "not_attempted"]


class ProgressEntry(BaseModel):
    paper_id: str
    status: ProgressStatus
    file_path: Optional[str] = None


class DownloadProgress(BaseModel):
    entries: dict[str, ProgressEntry] = {}

    def upsert(
        self,
        paper_id: str,
        status: ProgressStatus,
        file_path: Optional[str] = None,
    ) -> None:
        self.entries[paper_id] = ProgressEntry(
            paper_id=paper_id, status=status, file_path=file_path
        )

    def get(self, paper_id: str) -> Optional[ProgressEntry]:
        return self.entries.get(paper_id)

    def successful_ids(self) -> set[str]:
        return {pid for pid, e in self.entries.items() if e.status == "success"}


def load_progress(path: Path) -> DownloadProgress:
    if not path.exists():
        return DownloadProgress()
    return DownloadProgress.model_validate_json(path.read_text())


def save_progress(progress: DownloadProgress, path: Path) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(progress.model_dump_json(indent=2))
    os.replace(tmp, path)
