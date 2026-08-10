import logging
from pathlib import Path
from uuid import uuid4

import boto3

from .config import settings

logger = logging.getLogger(__name__)


class StorageService:
    def __init__(self) -> None:
        self._local_root = Path("/tmp/dataez_uploads")
        self._local_root.mkdir(parents=True, exist_ok=True)
        self._s3_client = boto3.client("s3", region_name=settings.aws_region) if settings.aws_region else boto3.client("s3")

    def upload_bytes(self, content: bytes, filename: str) -> str:
        key = f"{settings.s3_prefix}/{uuid4()}-{filename}"

        if settings.storage_backend == "s3":
            if not settings.s3_bucket:
                raise ValueError("S3_BUCKET is required when STORAGE_BACKEND=s3")
            self._s3_client.put_object(Bucket=settings.s3_bucket, Key=key, Body=content)
            logger.info("Uploaded %s to S3 (%d bytes)", filename, len(content))
            return key

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
