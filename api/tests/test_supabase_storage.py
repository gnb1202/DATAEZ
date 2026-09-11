from uuid import uuid4

import httpx
import pytest
from pydantic import ValidationError

from app.config import Settings, settings
from app.storage import StorageService
from app.supabase_storage import SupabaseObjectStore


def test_supabase_serverless_configuration():
    config = Settings(runtime_mode="serverless", storage_backend="supabase",
                      supabase_url="https://example.supabase.co", supabase_secret_key="sb_secret_test")
    assert config.db_pool_max_size == 2 and not config.startup_migrations_enabled


@pytest.mark.parametrize("url", ["http://example.com", "https://user:pass@example.com", "https://example.com/other", "https://example.com?key=x"])
def test_storage_rejects_invalid_credential_destination(url):
    with pytest.raises(ValidationError):
        Settings(storage_backend="supabase", supabase_url=url, supabase_secret_key="sb_secret_test")


def test_supabase_adapter_round_trip_and_staging(monkeypatch):
    monkeypatch.setattr(settings, "storage_backend", "supabase")
    monkeypatch.setattr(settings, "supabase_url", "https://example.supabase.co")
    monkeypatch.setattr(settings, "supabase_secret_key", "sb_secret_test")
    objects = {}

    def request(method, url, **kwargs):
        assert kwargs["headers"]["apikey"] == "sb_secret_test"
        assert "Authorization" not in kwargs["headers"]
        assert kwargs["follow_redirects"] is False
        if method == "GET":
            assert "/object/authenticated/" in url
            assert len(kwargs["params"]["cacheNonce"]) == 32
            url = url.replace("/object/authenticated/", "/object/", 1)
        if method == "POST":
            assert kwargs["headers"]["Cache-Control"] == "no-store"
        prefix = "https://example.supabase.co/storage/v1/object/dataez-files"
        assert url.startswith(prefix)
        key = url.removeprefix(prefix + "/")
        if method == "POST":
            objects[key] = kwargs["content"]
        if method == "GET":
            return httpx.Response(200, content=objects[key])
        if method == "DELETE":
            from urllib.parse import quote
            for raw in kwargs["json"]["prefixes"]:
                objects.pop(quote(raw, safe="/"), None)
        return httpx.Response(200, json={})

    monkeypatch.setattr(httpx, "request", request)
    storage = StorageService()
    key = storage.upload_bytes("매출,금액\n카드,12000".encode(), "매출.csv")
    assert key.isascii() and key.endswith(".csv")
    assert storage.read_bytes(key).startswith("매출".encode())
    staged = storage.staged_key(str(uuid4()))
    storage.write_staged(staged, b"one")
    storage.write_staged(staged, b"two")
    assert storage.read_bytes(staged) == b"two"
    storage.delete_staged(staged)
    storage.delete_staged(staged)
    assert len(objects) == 1


@pytest.mark.parametrize("key", ["../other", "uploads/../other", "/absolute", "a\\b", "a//b"])
def test_storage_rejects_path_traversal(key):
    with pytest.raises(ValueError):
        SupabaseObjectStore._path(key)


def test_storage_missing_object_and_errors_do_not_expose_response(monkeypatch):
    store = SupabaseObjectStore("https://example.supabase.co", "sb_secret_test", "files")
    monkeypatch.setattr(httpx, "request", lambda *a, **kw: httpx.Response(400, json={"statusCode": "404"}))
    with pytest.raises(FileNotFoundError):
        store.get("uploads/missing.csv")
    monkeypatch.setattr(httpx, "request", lambda *a, **kw: httpx.Response(403, text="sensitive response"))
    with pytest.raises(RuntimeError, match="HTTP 403") as error:
        store.get("uploads/file.csv")
    assert "sensitive" not in str(error.value)


def test_signed_url_scoped_to_exact_object_and_origin(monkeypatch):
    store = SupabaseObjectStore("https://example.supabase.co", "secret", "files")
    def request(method, url, **kwargs):
        assert method == "POST" and kwargs['headers']['x-upsert'] == 'false'
        return httpx.Response(200, json={'url':'/object/upload/sign/files/uploads/a.csv?token=scoped'})
    monkeypatch.setattr(httpx, 'request', request)
    assert store.create_upload_url('uploads/a.csv') == 'https://example.supabase.co/storage/v1/object/upload/sign/files/uploads/a.csv?token=scoped'
    for url in ('https://other.example/object/upload/sign/files/uploads/a.csv?token=x',
                '/object/upload/sign/files/uploads/b.csv?token=x',
                '/object/upload/sign/files/uploads/a.csv'):
        with pytest.raises(RuntimeError):
            store._signed_url(url, 'upload/sign', 'uploads/a.csv')


def test_verification_reads_are_bounded(monkeypatch):
    from contextlib import contextmanager
    store = SupabaseObjectStore('https://example.supabase.co', 'secret', 'files')
    @contextmanager
    def stream(method, url, **kwargs):
        assert '/object/authenticated/' in url and kwargs['follow_redirects'] is False
        yield httpx.Response(200, content=b'a'*100)
    monkeypatch.setattr(httpx, 'stream', stream)
    assert store.get_limited('file.txt', 100) == b'a'*100
    with pytest.raises(ValueError):
        store.get_limited('file.txt', 99)
