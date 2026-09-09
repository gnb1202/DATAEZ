from pathlib import Path
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from app.config import settings
from app.storage import StorageService


def test_staged_keys_ignore_filename_and_delete_only_generated_paths(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "local_storage_path", str(tmp_path))
    storage = StorageService()
    key = storage.staged_key(str(uuid4()))
    storage.write_staged(key, b"ledger")
    assert storage.read_bytes(key) == b"ledger"
    unrelated = tmp_path / "keep.txt"
    unrelated.write_text("keep")
    for invalid in ("../keep.txt", str(unrelated), "ledger-staging/../../keep.txt", "ledger-staging/anything.bin"):
        with pytest.raises(ValueError):
            storage.delete_staged(invalid)
    assert unrelated.read_text() == "keep"
    storage.delete_staged(key)
    storage.delete_staged(key)
    assert not (tmp_path / key).exists()


def test_staged_s3_operations_share_one_key(monkeypatch):
    monkeypatch.setattr(settings, "storage_backend", "s3")
    monkeypatch.setattr(settings, "s3_bucket", "test-ledgers")
    storage = StorageService()
    client = MagicMock()
    storage._s3_client_cache = client
    client.get_object.return_value["Body"].read.return_value = b"exact bytes"
    key = storage.staged_key(str(uuid4()))
    storage.write_staged(key, b"exact bytes")
    assert storage.read_bytes(key) == b"exact bytes"
    storage.delete_staged(key)
    expected = {"Bucket": "test-ledgers", "Key": f"{settings.s3_prefix}/{key}"}
    client.put_object.assert_called_once_with(**expected, Body=b"exact bytes")
    client.get_object.assert_called_once_with(**expected)
    client.delete_object.assert_called_once_with(**expected)
