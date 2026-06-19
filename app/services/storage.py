from __future__ import annotations

import asyncio
from pathlib import Path

from google.cloud import storage as gcs
from google.cloud.exceptions import Conflict, NotFound

from app.core.settings import get_settings


class GCSStorage:
    def __init__(self, bucket_name: str, project: str) -> None:
        self._bucket_name = bucket_name
        self._client = gcs.Client(project=project)

    def _bucket(self) -> gcs.Bucket:
        return self._client.bucket(self._bucket_name)

    def ensure_bucket(self) -> None:
        bucket = self._bucket()
        try:
            self._client.create_bucket(bucket)
        except Conflict:
            pass  # already exists

    async def upload(self, blob_path: str, local: Path) -> None:
        def _sync() -> None:
            self._bucket().blob(blob_path).upload_from_filename(str(local))

        await asyncio.to_thread(_sync)

    async def download(self, blob_path: str, dest: Path) -> None:
        def _sync() -> None:
            dest.parent.mkdir(parents=True, exist_ok=True)
            self._bucket().blob(blob_path).download_to_filename(str(dest))

        await asyncio.to_thread(_sync)

    async def read_bytes(self, blob_path: str) -> bytes:
        def _sync() -> bytes:
            return self._bucket().blob(blob_path).download_as_bytes()

        return await asyncio.to_thread(_sync)

    async def delete_prefix(self, prefix: str) -> None:
        def _sync() -> None:
            blobs = list(self._client.list_blobs(self._bucket_name, prefix=prefix))
            for blob in blobs:
                try:
                    blob.delete()
                except NotFound:
                    pass

        await asyncio.to_thread(_sync)


def get_storage() -> GCSStorage:
    s = get_settings()
    return GCSStorage(bucket_name=s.gcs_bucket, project=s.gcs_project)
