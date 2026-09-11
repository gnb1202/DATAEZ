import logging
import re
from pathlib import Path
from uuid import uuid4

import boto3

from .config import settings

logger = logging.getLogger(__name__)


class StorageService:
    """File storage backed by Supabase, S3, or local disk.

    The S3 client is created lazily so a local-only deployment never depends on
    AWS configuration being present.
    """

    def __init__(self) -> None:
        self._local_root = Path(settings.local_storage_path)
        self._s3_client_cache = None
        self._supabase_cache = None
        if settings.storage_backend == "local":
            self._local_root.mkdir(parents=True, exist_ok=True)
            logger.info("Storage backend: local (%s)", self._local_root.resolve())
        elif settings.storage_backend == "s3":
            logger.info("Storage backend: s3 (bucket=%s)", settings.s3_bucket)
        else:
            logger.info("Storage backend: supabase (bucket=%s)", settings.supabase_storage_bucket)

    @property
    def _supabase(self):
        if self._supabase_cache is None:
            from .supabase_storage import SupabaseObjectStore
            self._supabase_cache = SupabaseObjectStore(settings.supabase_url,
                settings.supabase_secret_key, settings.supabase_storage_bucket)
        return self._supabase_cache

    @property
    def _s3_client(self):
        if self._s3_client_cache is None:
            from botocore.config import Config
            options = {"config": Config(signature_version="s3v4", s3={"addressing_style":"path"},
                request_checksum_calculation="when_required", response_checksum_validation="when_required")}
            if settings.aws_region: options["region_name"] = settings.aws_region
            if settings.s3_endpoint_url: options["endpoint_url"] = settings.s3_endpoint_url
            if settings.s3_access_key_id: options["aws_access_key_id"] = settings.s3_access_key_id
            if settings.s3_secret_access_key: options["aws_secret_access_key"] = settings.s3_secret_access_key
            self._s3_client_cache = boto3.client("s3", **options)
        return self._s3_client_cache

    def upload_bytes(self, content: bytes, filename: str) -> str:
        safe_name = Path(filename.replace("\\", "/")).name
        safe_name = re.sub(r"[^a-zA-Z0-9가-힣._-]", "_", safe_name)[:180]
        key = f"{settings.s3_prefix}/{uuid4()}-{safe_name}"

        if settings.storage_backend == "supabase":
            # Supabase rejects non-ASCII object keys. Keep the original filename
            # in file metadata, and use an opaque ASCII object key for storage.
            suffix = re.sub(r"[^a-zA-Z0-9.]", "", Path(safe_name).suffix)[:12]
            key = f"{settings.s3_prefix}/{uuid4()}{suffix}"
            self._supabase.put(key, content)
            return key

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
        if storage_key.startswith("ledger-staging/"):
            return self.read_staged(storage_key)
        if settings.storage_backend == "supabase":
            return self._supabase.get(storage_key)
        if settings.storage_backend == "s3":
            if not settings.s3_bucket:
                raise ValueError("S3_BUCKET is required when STORAGE_BACKEND=s3")
            response = self._s3_client.get_object(Bucket=settings.s3_bucket, Key=storage_key)
            return response["Body"].read()

        target = Path(storage_key).resolve()
        if not target.is_relative_to(self._local_root.resolve()):
            raise ValueError("File path escapes storage root")
        return target.read_bytes()

    @staticmethod
    def staged_key(batch_id: str) -> str:
        # No original filename or client-supplied path enters a storage key.
        from uuid import UUID
        return f"ledger-staging/{UUID(batch_id).hex}.bin"

    def _staged_location(self, key: str):
        if not re.fullmatch(r"ledger-staging/[0-9a-f]{32}\.bin", key):
            raise ValueError("Invalid ledger staging key")
        if settings.storage_backend in ("s3", "supabase"):
            if settings.storage_backend == "s3" and not settings.s3_bucket:
                raise ValueError("S3_BUCKET is required")
            return f"{settings.s3_prefix}/{key}"
        root = self._local_root.resolve()
        target = (root / key).resolve()
        if not target.is_relative_to(root):
            raise ValueError("Staging path escapes storage root")
        return target

    def write_staged(self, key: str, content: bytes) -> None:
        target = self._staged_location(key)
        if settings.storage_backend == "supabase":
            self._supabase.put(target, content, upsert=True)
        elif settings.storage_backend == "s3":
            self._s3_client.put_object(Bucket=settings.s3_bucket, Key=target, Body=content)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)

    def read_staged(self, key: str) -> bytes:
        target = self._staged_location(key)
        if settings.storage_backend == "supabase":
            return self._supabase.get(target)
        if settings.storage_backend == "s3":
            return self._s3_client.get_object(Bucket=settings.s3_bucket, Key=target)["Body"].read()
        return target.read_bytes()

    def delete_staged(self, key: str) -> None:
        target = self._staged_location(key)
        if settings.storage_backend == "supabase":
            self._supabase.delete(target)
        elif settings.storage_backend == "s3":
            self._s3_client.delete_object(Bucket=settings.s3_bucket, Key=target)
        else:
            target.unlink(missing_ok=True)
