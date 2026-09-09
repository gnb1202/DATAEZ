"""Materialize original bytes once, never copy a possibly changed ledger."""
import hashlib
import json
from uuid import uuid4

from fastapi import HTTPException
from psycopg import sql

from . import db
from .storage import StorageService


def original_table(user_id, file_id, project_id):
    from .file_library import CATALOG, own_project
    from .data_import import prepare_import, write_import
    # Explicit selection was checked by resolve_references. Lock the file as
    # remove/prepare do, and recheck visibility before creating any derived data.
    with db._connect() as conn, conn.cursor() as cur:
        own_project(cur, user_id, project_id)
        cur.execute('SELECT id FROM files WHERE id=%s AND user_id=%s FOR UPDATE', (file_id, user_id))
        if not cur.fetchone():
            raise HTTPException(404, '파일을 찾을 수 없습니다.')
        cur.execute('SELECT deleted_at FROM library_entries WHERE file_id=%s AND user_id=%s', (file_id,user_id))
        entry = cur.fetchone()
        if entry and entry['deleted_at']:
            raise HTTPException(404, '보관함에서 제외된 파일입니다.')
        cur.execute('SELECT * FROM table_meta WHERE user_id=%s AND project_id=%s AND original_file_id=%s', (user_id,project_id,file_id))
        existing = cur.fetchone()
        if existing:
            if existing['deleted_at']:
                raise HTTPException(410, '원본 분석 자료를 사용할 수 없습니다.')
            return existing
        cur.execute(CATALOG + "SELECT * FROM catalog WHERE id=%(fid)s", {"uid":user_id,"fid":file_id})
        row = cur.fetchone()
        if not row:
            raise HTTPException(404, "파일을 찾을 수 없습니다.")
        try:
            content = StorageService().read_bytes(row['storage_key'])
        except FileNotFoundError:
            raise HTTPException(410, '원본 파일을 찾을 수 없습니다.') from None
        digest = hashlib.sha256(content).hexdigest()
        if row.get('content_hash') and row['content_hash'] != digest:
            raise HTTPException(409, '보관한 원본과 파일 내용이 다릅니다. 원본을 확인해주세요.')
        prepared = prepare_import(content, row['filename'])
        tid = str(uuid4())
        physical = db.get_user_table_name(user_id, tid)
        write_import(cur, physical, prepared, create=True)
        cur.execute(sql.SQL('CREATE TRIGGER original_file_readonly BEFORE INSERT OR UPDATE OR DELETE OR TRUNCATE ON {} FOR EACH STATEMENT EXECUTE FUNCTION reject_original_file_write()').format(sql.Identifier(physical)))
        cur.execute('''INSERT INTO table_meta(id,project_id,user_id,name,columns_schema,row_count,original_file_id,original_content_hash)
            VALUES(%s,%s,%s,%s,%s::jsonb,%s,%s,%s) RETURNING *''',
            (tid,project_id,user_id,row['filename'][:180]+' · 파일 원본',json.dumps(prepared.columns_schema),len(prepared.rows),file_id,digest))
        return cur.fetchone()


def source_scope(meta):
    if meta.get('original_file_id'):
        return {'scope':'original_file','scope_label':'파일 원본만',
                'file_id':str(meta['original_file_id']),'content_hash':meta.get('original_content_hash'),
                'refresh_note':'업로드 당시 행으로 재계산합니다. 연결 장부에 추가된 거래는 포함하지 않습니다.'}
    return {'scope':'linked_ledger','scope_label':'누적 장부 전체',
            'refresh_note':'새로고침할 때 연결 장부의 최신 거래를 반영합니다.'}
