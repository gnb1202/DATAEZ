import logging
from pathlib import Path
from uuid import uuid4

import boto3

from .config import settings

logger = logging.getLogger(__name__)


class StorageService:
    """File storage with two interchangeable backends: S3 and local disk.

    The S3 client is created lazily so a local-only deployment never depends on
    AWS configuration being present.
    """

    def __init__(self) -> None:
        self._local_root = Path(settings.local_storage_path)
        self._s3_client_cache = None
        if settings.storage_backend == "local":
            self._local_root.mkdir(parents=True, exist_ok=True)
            logger.info("Storage backend: local (%s)", self._local_root.resolve())
        else:
            logger.info("Storage backend: s3 (bucket=%s)", settings.s3_bucket)

    @property
    def _s3_client(self):
        if self._s3_client_cache is None:
            self._s3_client_cache = (
                boto3.client("s3", region_name=settings.aws_region)
                if settings.aws_region
                else boto3.client("s3")
            )
        return self._s3_client_cache

    def upload_bytes(self, content: bytes, filename: str) -> str:
        key = f"{settings.s3_prefix}/{uuid4()}-{filename}"

        if settings.storage_backend == "s3":
            if not settings.s3_bucket:
                raise ValueError("S3_BUCKET is required when STORAGE_BACKEND=s3")
            self._s3_client.put_object(Bucket=settings.s3_bucket, Key=key, Body=content)
            logger.info("Uploaded %s to S3 (%d bytes)", filename, len(content))
            return key

        self._local_root.mkdir(parents=True, exist_ok=True)
        local_path = self._local_root / key.replace("/", "_")
        local_path.write_bytes(content)
        logger.info("Saved %s locally (%d bytes)", filename, len(content))
        return str(local_path)

    def read_bytes(self, storage_key: str) -> bytes:
        if settings.storage_backend == "s3":
            if not settings.s3_bucket:
                raise ValueError("S3_BUCKET is required when STORAGE_BACKEND=s3")
            response = self._s3_client.get_object(Bucket=settings.s3_bucket, Key=storage_key)
            return response["Body"].read()

        return Path(storage_key).read_bytes()
