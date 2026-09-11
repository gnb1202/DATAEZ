import asyncio
from io import BytesIO
from unittest.mock import MagicMock

from fastapi import HTTPException, UploadFile
import pytest

from app import upload_sources as sources, file_library, table_imports, index_jobs
from app.config import settings
from .test_file_library import live  # noqa: F401


def test_multipart_is_bounded_and_exclusive(monkeypatch):
    monkeypatch.setattr(settings, 'max_upload_size_mb', 1)
    content = BytesIO(b'x' * (1024 * 1024 + 100))
    file = UploadFile(file=content, filename='test.csv')
    with pytest.raises(HTTPException):
        asyncio.run(sources.read_source('u','p',file,None,None))
    assert content.tell() == 1024 * 1024 + 1
    for file, stored in [(file, 'id'), (None, None)]:
        with pytest.raises(HTTPException) as error:
            asyncio.run(sources.read_source('u','p',file,stored,None))
        assert error.value.status_code == 422


def test_stored_ownership_scope_hash_and_reuse(live, monkeypatch):
    content = b'amount\n20000\n'
    record = file_library.store_file(live.user, live.store, 'sales.csv', content, live.storage)
    fid = record['file_id']
    assert sources.stored_source(live.user, live.store, fid, live.storage, ('.csv',)) == ('sales.csv',content)
    for user, project in [(live.stranger,live.store),(live.user,live.other)]:
        with pytest.raises(HTTPException):
            sources.stored_source(user,project,fid,live.storage,('.csv',))
    with pytest.raises(HTTPException):
        sources.stored_source(live.user,live.store,fid,live.storage,('.pdf',))
    monkeypatch.setattr(live.storage, 'upload_bytes', MagicMock(side_effect=AssertionError('Original copied')))
    table = table_imports.create_imported_table(live.user,live.store,'매출',content,'sales.csv',live.storage,source_file_id=fid)
    again = table_imports.create_imported_table(live.user,live.store,'again',content,'sales.csv',live.storage,source_file_id=fid)
    assert table['id'] == again['id'] and table['name'] == '매출'
    with live.connect() as conn:
        assert conn.execute('SELECT count(*) n FROM files').fetchone()['n'] == 1
        conn.execute("UPDATE library_entries SET content_hash=%s WHERE file_id=%s", ('0'*64,fid))
    with pytest.raises(HTTPException) as error:
        sources.stored_source(live.user,live.store,fid,live.storage,('.csv',))
    assert error.value.status_code == 409
    file_library.remove_file(live.user,fid)
    with pytest.raises(HTTPException) as error:
        sources.stored_source(live.user,live.store,fid,live.storage,('.csv',))
    assert error.value.status_code == 404


def test_stored_document_reuses_original_and_job(live):
    content = b'Refunds are available before the appointment.'
    fid = file_library.store_file(live.user,live.store,'policy.txt',content,live.storage)['file_id']
    first = index_jobs.register_document(live.user,live.store,'policy.txt',content,live.storage,source_file_id=fid)
    second = index_jobs.register_document(live.user,live.store,'policy.txt',content,live.storage,source_file_id=fid)
    assert first == second and first['file_id'] == fid
    with live.connect() as conn:
        assert conn.execute('SELECT count(*) n FROM files').fetchone()['n'] == 1
