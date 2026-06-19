from __future__ import annotations

import asyncio
from pathlib import Path

from google.cloud import storage as gcs
from google.cloud.exceptions import Conflict, NotFound

from app.core.settings import get_settings


class GCSStorage:
    def __init__(self, bucket_name: str, project: str, path_prefix: str) -> None:
        self._bucket_name = bucket_name
        self._client = gcs.Client(project=project)
        self._prefix = path_prefix.strip("/")

    def _blob_path(self, relative_path: str) -> str:
        return f"{self._prefix}/{relative_path.lstrip('/')}"

    def _bucket(self) -> gcs.Bucket:
        return self._client.bucket(self._bucket_name)

    def ensure_bucket(self) -> None:
        bucket = self._bucket()
        try:
            self._client.create_bucket(bucket)
        except Conflict:
            pass  # already exists

    async def upload(self, blob_path: str, local: Path) -> None:
        full = self._blob_path(blob_path)

        def _sync() -> None:
            self._bucket().blob(full).upload_from_filename(str(local))

        await asyncio.to_thread(_sync)

    async def download(self, blob_path: str, dest: Path) -> None:
        full = self._blob_path(blob_path)

        def _sync() -> None:
            dest.parent.mkdir(parents=True, exist_ok=True)
            self._bucket().blob(full).download_to_filename(str(dest))

        await asyncio.to_thread(_sync)

    async def read_bytes(self, blob_path: str) -> bytes:
        full = self._blob_path(blob_path)

        def _sync() -> bytes:
            return self._bucket().blob(full).download_as_bytes()

        return await asyncio.to_thread(_sync)

    async def delete_prefix(self, prefix: str) -> None:
        full_prefix = self._blob_path(prefix)

        def _sync() -> None:
            blobs = list(self._client.list_blobs(self._bucket_name, prefix=full_prefix))
            for blob in blobs:
                try:
                    blob.delete()
                except NotFound:
                    pass

        await asyncio.to_thread(_sync)


def get_storage() -> GCSStorage:
    s = get_settings()
    return GCSStorage(bucket_name=s.gcs_bucket, project=s.gcs_project, path_prefix=s.gcs_path_prefix)
