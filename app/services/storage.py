from __future__ import annotations

import shutil
from pathlib import Path

import aiofiles

from app.core.settings import get_settings


class LocalStorage:
    """Filesystem-backed storage rooted at settings.storage_root."""

    def __init__(self, root: Path | None = None):
        self.root = Path(root or get_settings().storage_root)
        self.root.mkdir(parents=True, exist_ok=True)

    def doc_dir(self, document_id: str) -> Path:
        p = self.root / "documents" / document_id
        p.mkdir(parents=True, exist_ok=True)
        return p

    def pages_dir(self, document_id: str) -> Path:
        p = self.doc_dir(document_id) / "pages"
        p.mkdir(parents=True, exist_ok=True)
        return p

    async def save_upload(self, document_id: str, filename: str, data: bytes) -> Path:
        target = self.doc_dir(document_id) / "original.pdf"
        async with aiofiles.open(target, "wb") as f:
            await f.write(data)
        # Keep a hint of the original filename
        async with aiofiles.open(self.doc_dir(document_id) / "filename.txt", "w") as f:
            await f.write(filename)
        return target

    def delete_doc(self, document_id: str) -> None:
        d = self.root / "documents" / document_id
        if d.exists():
            shutil.rmtree(d, ignore_errors=True)


def get_storage() -> LocalStorage:
    return LocalStorage()
