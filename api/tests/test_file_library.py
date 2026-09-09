"""Real catalog transactions and API boundaries, with an isolated local schema."""
import json
import os
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from decimal import Decimal
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

import psycopg
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from psycopg import sql
from psycopg.rows import dict_row

from app import db, file_library as library, library_agent, library_routes, table_imports
from app.auth import get_current_user
from app.config import settings
from app.library_schema import ensure_library
from app.storage import StorageService

DSN = os.environ.get("DATAEZ_TEST_DATABASE_URL")


@pytest.fixture
def live(monkeypatch, tmp_path):
    if not DSN:
        pytest.skip("Set DATAEZ_TEST_DATABASE_URL for catalog transaction tests")
    namespace = "dataez_library_test_" + uuid4().hex
    user, store, other, stranger = (str(uuid4()) for _ in range(4))
    with psycopg.connect(DSN, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(namespace)))

    @contextmanager
    def connect():
        with psycopg.connect(DSN, options=f"-c search_path={namespace}", row_factory=dict_row) as conn:
            yield conn
    try:
        with connect() as conn:
            conn.execute("CREATE TABLE projects (id uuid PRIMARY KEY,user_id uuid,name text,description text,created_at timestamp DEFAULT now(),updated_at timestamp DEFAULT now(),deleted_at timestamp)")
            conn.execute("CREATE TABLE files (id uuid PRIMARY KEY,user_id uuid,filename text,storage_key text,size_bytes bigint,created_at timestamp DEFAULT now())")
            conn.execute("""CREATE TABLE table_meta (id uuid PRIMARY KEY,project_id uuid REFERENCES projects(id),user_id uuid,name text,
                description text DEFAULT '',columns_schema jsonb,row_count bigint,source_file_id uuid REFERENCES files(id),
                created_at timestamp DEFAULT now(),updated_at timestamp DEFAULT now(),deleted_at timestamp)""")
            conn.execute("""CREATE TABLE search_index_jobs(id uuid PRIMARY KEY DEFAULT gen_random_uuid(), user_id uuid,project_id uuid,
                file_id uuid UNIQUE, file_sha256 text,status text DEFAULT 'pending')""")
            conn.execute("INSERT INTO projects(id,user_id,name) VALUES (%s,%s,'성수점'),(%s,%s,'연남점')", (store,user,other,user))
        monkeypatch.setattr(db,"_connect",connect)
        monkeypatch.setattr(table_imports,"_connect",connect)
        monkeypatch.setattr(settings,"storage_backend","local")
        monkeypatch.setattr(settings,"local_storage_path",str(tmp_path))
        db.ensure_ledger_import_tables()
        ensure_library()
        app = FastAPI()
        app.include_router(library_routes.router)
        app.dependency_overrides[get_current_user] = lambda: {"id":user}
        yield SimpleNamespace(connect=connect,user=user,store=store,other=other,stranger=stranger,
                              client=TestClient(app),storage=StorageService(),app=app)
    finally:
        assert namespace.startswith("dataez_library_test_") and len(namespace) == len("dataez_library_test_")+32
        with psycopg.connect(DSN, autocommit=True) as admin:
            admin.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(namespace)))


CSV = b"event_id,amount,paid_at\n000012345678901234567890,9007199254740993.01,2026-09-01\n"


def upload(live, *, project=True, filename="payments.csv", content=CSV):
    response = live.client.post("/api/library/files", data={"project_id":live.store} if project else {}, files={"file":(filename,content)})
    assert response.status_code == 201, response.text
    return response.json()


def selection(file):
    return {"file_id":file["file_id"],"table_id":file["bindings"][0].get("table_id")}


def test_store_preview_download_and_concurrent_prepare_reuses_one_table(live):
    file = upload(live)
    second = upload(live,filename="renamed.csv")
    assert second["file_id"] == file["file_id"] and second["replayed"]
    preview = live.client.get(f"/api/library/files/{file['file_id']}/preview").json()
    assert preview["rows"][0]["amount"] == "9007199254740993.01"
    assert preview["rows"][0]["event_id"] == "000012345678901234567890"
    raw = live.client.get(f"/api/library/files/{file['file_id']}/download")
    assert raw.content == CSV and raw.headers['cache-control'] == 'private, no-store'
    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(lambda _: library.prepare_file(live.user,file['file_id'],live.store),range(3)))
    ids = {r['bindings'][0]['table_id'] for r in results}
    assert len(ids) == 1
    with live.connect() as conn:
        assert conn.execute('SELECT count(*) AS n FROM table_meta').fetchone()['n'] == 1
        table = db.get_user_table_name(live.user,ids.pop())
        rows = conn.execute(sql.SQL('SELECT * FROM {}').format(sql.Identifier(table))).fetchall()
        assert len(rows) == 1 and rows[0]['amount'] == Decimal('9007199254740993.01')


def test_owner_store_filters_search_and_removed_references(live):
    file = upload(live,filename="cash_100%.csv")
    upload(live,project=False,filename="unassigned.txt",content=b"Notes")
    assert library.list_library(live.user,project_id=live.store)['total'] == 1
    assert library.list_library(live.user)['total'] == 2
    assert library.list_library(live.stranger)['total'] == 0
    assert library.list_library(live.user,search="100%")['total'] == 1
    assert library.list_library(live.user,search="%' OR 1=1 --")['total'] == 0
    assert library.list_library(live.user,kind='document')['total'] == 1
    assert library.list_library(live.user,offset=1,limit=1)['files'][0]['file_id'] == file['file_id']
    ready = library.prepare_file(live.user,file['file_id'],live.store)
    refs = library.resolve_references(live.user,live.store,[selection(ready)],confirmed=True)
    assert refs[0]['scope'] == 'linked_ledger'
    live.app.dependency_overrides[get_current_user] = lambda: {"id":live.stranger}
    for suffix in ('','/preview','/download'):
        assert live.client.get(f"/api/library/files/{file['file_id']}{suffix}").status_code == 404
    assert live.client.post(f"/api/library/files/{file['file_id']}/prepare",json={'project_id':live.store}).status_code == 404
    assert live.client.delete(f"/api/library/files/{file['file_id']}").status_code == 404
    live.app.dependency_overrides[get_current_user] = lambda: {"id":live.user}
    assert live.client.delete(f"/api/library/files/{file['file_id']}").status_code == 200
    assert library.list_library(live.user)['total'] == 1
    with pytest.raises(HTTPException) as error:
        library.resolve_references(live.user,live.store,[selection(ready)],confirmed=True)
    assert error.value.status_code == 404
    with live.connect() as conn:
        assert conn.execute('SELECT count(*) AS n FROM table_meta').fetchone()['n'] == 1
    original = library.get_record(live.user,file['file_id'],include_removed=True)
    assert live.storage.read_bytes(original['storage_key']) == CSV


def test_legacy_import_uses_existing_cumulative_ledger_without_appending(live):
    meta = table_imports.create_imported_table(live.user,live.store,"누적 매출",CSV,"old.csv",live.storage)
    table_imports.append_imported_table(live.user,live.store,str(meta['id']),b'event_id,amount,paid_at\n002,100,2026-09-02\n','next.csv')
    files = library.list_library(live.user,project_id=live.store)['files']
    assert len(files) == 1  # ordinary append does not retain another original
    file = library.prepare_file(live.user,files[0]['file_id'],live.store)
    assert file['replayed'] and file['bindings'][0]['row_count'] == 2
    refs = library.resolve_references(live.user,live.store,[selection(file)],confirmed=True)
    assert refs[0]['row_count'] == 2 and refs[0]['scope'] == 'linked_ledger'
    with pytest.raises(HTTPException):
        library.resolve_references(live.user,live.store,[selection(file)],confirmed=False)


def test_multistore_and_ambiguous_or_unprepared_selection_fail_closed(live):
    file = library.store_file(live.user,live.other,'other.csv',CSV)
    ready = library.prepare_file(live.user,file['file_id'],live.other)
    pick = selection(ready)
    for flag in (False,'true',None):
        with pytest.raises(HTTPException):
            library.resolve_references(live.user,live.store,[{**pick,'include_other_store':flag}],confirmed=True)
    result = library.resolve_references(live.user,live.store,[{**pick,'include_other_store':True}],confirmed=True)
    assert result[0]['project_id'] == live.other
    for picks in ([{'file_id':file['file_id']}],[{**pick,'table_id':str(uuid4())}], [pick]*11):
        with pytest.raises(HTTPException):
            library.resolve_references(live.user,live.store,picks,confirmed=True)
    response = live.client.post('/api/library/files/resolve',json={'project_id':live.store,'selections':[pick],'confirmed':True})
    assert response.status_code == 422


def test_document_readiness_and_unassigned_duplicate_conflict_are_explicit(live):
    file = upload(live,project=False,filename='notes.md',content=b'# Sales rules')
    ready = library.prepare_file(live.user,file['file_id'],live.store)
    assert ready['status'] == 'index_pending'
    with pytest.raises(HTTPException) as error:
        library.resolve_references(live.user,live.store,[{'file_id':file['file_id']}],confirmed=True)
    assert error.value.status_code == 409
    with live.connect() as conn:
        conn.execute("UPDATE search_index_jobs SET status='succeeded'")
    assert library.resolve_references(live.user,live.store,[{'file_id':file['file_id']}],confirmed=True)[0]['kind'] == 'document'
    upload(live)
    duplicate = upload(live,project=False)
    with pytest.raises(HTTPException) as error:
        library.prepare_file(live.user,duplicate['file_id'],live.store)
    assert error.value.status_code == 409
    with live.connect() as conn:
        assert conn.execute('SELECT count(*) AS n FROM table_meta').fetchone()['n'] == 0


def test_upload_rejects_unsupported_empty_and_foreign_project(live):
    for filename,content in [('app.exe',b'not a document'),('empty.csv',b'')]:
        assert live.client.post('/api/library/files',files={'file':(filename,content)}).status_code == 422
    assert live.client.post('/api/library/files',data={'project_id':str(uuid4())},files={'file':('test.csv',CSV)}).status_code == 404


def test_scope_guard_blocks_outside_ids_and_writes_and_filters_discovery():
    ref = {'file_id':'file','table_id':'chosen','table_name':'sales','project_id':'store','project_name':'성수점','kind':'ledger'}
    executor = SimpleNamespace(library_refs=[ref],project_id='store')
    for name,args in [('insert_rows',{}),('import_file',{}),('preview_metric',{'definition':{'sources':[{'table_id':'outside'}]}}),('inspect_store_table',{'project_id':'store','table_id':'outside'})]:
        assert library_agent.guard(executor,name,args)['error'] == 'library_scope'
    assert library_agent.guard(executor,'list_store_tables',{'project_id':'store'})['tables'][0]['id'] == 'chosen'
    assert len(library_agent.guard(executor,'list_stores',{})['stores']) == 1
    assert library_agent.guard(executor,'search_schema',{})['count'] == 1


def test_supabase_s3_adapter_keeps_server_credentials_and_roundtrips_bytes(monkeypatch):
    monkeypatch.setattr(settings,'storage_backend','s3')
    monkeypatch.setattr(settings,'s3_endpoint_url','https://example.storage.supabase.co/storage/v1/s3')
    monkeypatch.setattr(settings,'s3_access_key_id','test-server-id')
    monkeypatch.setattr(settings,'s3_secret_access_key','test-server-secret')
    client = MagicMock()
    client.get_object.return_value = {'Body':BytesIO(CSV)}
    with patch('app.storage.boto3.client',return_value=client) as create:
        storage = StorageService()
        key = storage.upload_bytes(CSV,'../../payments.csv')
        assert storage.read_bytes(key) == CSV
        options = create.call_args.kwargs
        assert options['endpoint_url'] == settings.s3_endpoint_url
        assert options['config'].s3['addressing_style'] == 'path'
        assert '..' not in key
        assert client.put_object.call_args.kwargs['Body'] == CSV
        assert create.call_count == 1


@pytest.mark.parametrize('streaming',[False,True])
def test_message_endpoints_resolve_owned_refs_before_agent_and_persist_sources(live,monkeypatch,streaming):
    from app import main
    from app.agent import AgentResult, AgentStep
    file = upload(live)
    file = library.prepare_file(live.user,file['file_id'],live.store)
    conversation = str(uuid4())
    saved, calls = [], []
    def save(**kwargs):
        saved.append({**kwargs,'id':kwargs['message_id']})
    def run(**kwargs):
        calls.append(kwargs)
        return AgentResult(answer='선택한 장부 전체를 분석했습니다.',steps=[])
    async def stream(**kwargs):
        calls.append(kwargs)
        yield AgentStep(type='answer',content='선택한 장부 전체를 분석했습니다.')
    monkeypatch.setattr(main,'save_message',save)
    monkeypatch.setattr(main,'list_messages',lambda _:saved[:])
    monkeypatch.setattr(main,'get_project',lambda *_:{'name':'성수점'})
    monkeypatch.setattr(main,'list_table_metas',lambda *_:[])
    monkeypatch.setattr(main,'update_conversation_title',lambda *_:None)
    monkeypatch.setattr(main,'touch_conversation',lambda *_:None)
    monkeypatch.setattr(main,'run_agent',run)
    monkeypatch.setattr(main,'run_agent_streaming',stream)
    original = dict(main.app.dependency_overrides)
    main.app.dependency_overrides[get_current_user] = lambda:{'id':live.user}
    main.app.dependency_overrides[main._get_owned_conversation] = lambda:{'id':conversation,'project_id':live.store}
    try:
        client = TestClient(main.app)
        path = f'/api/conversations/{conversation}/messages'+('/stream' if streaming else '')
        payload = {'message':'합계를 보여줘','library_selections':json.dumps([selection(file)]),'library_scope_confirmed':'true'}
        bad = client.post(path,data={**payload,'library_scope_confirmed':'false'})
        assert bad.status_code == 422 and not saved and not calls
        mixed = client.post(path,data=payload,files={'files':('new.csv',CSV)})
        assert mixed.status_code == 422 and not saved and not calls
        response = client.post(path,data=payload)
        assert response.status_code == 200, response.text
        if streaming:
            frames = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith('data: ')]
            answer = next(frame['data'] for frame in frames if frame['type']=='done')
        else:
            answer = response.json()
        assert answer['steps'][0]['tool_name'] == 'library_references'
        assert len(calls) == 1 and calls[0]['attached_files'] is None
        assert calls[0]['library_refs'][0]['table_id'] == file['bindings'][0]['table_id']
        assert [row['role'] for row in saved] == ['user','assistant']
        assert all(row['steps'][0]['tool_output']['files'][0]['file_id'] == file['file_id'] for row in saved)
        library.remove_file(live.user,file['file_id'])
        assert client.post(path,data=payload).status_code == 404
        assert len(saved) == 2 and len(calls) == 1
    finally:
        main.app.dependency_overrides.clear()
        main.app.dependency_overrides.update(original)


def test_executor_limits_sql_lookup_and_passes_document_filter(monkeypatch):
    from app import agent_tools, rag
    ref = {'file_id':str(uuid4()),'kind':'ledger','table_id':str(uuid4()),'table_name':'selected','project_id':str(uuid4()),'project_name':'성수점'}
    metas = [{'id':ref['table_id'],'name':'selected','columns_schema':[]}, {'id':str(uuid4()),'name':'outside','columns_schema':[]}]
    monkeypatch.setattr(agent_tools,'list_table_metas',lambda *_:metas)
    executor = agent_tools.ToolExecutor(str(uuid4()),ref['project_id'],library_refs=[ref])
    assert executor._resolve_table('outside') is None
    assert executor._resolve_table('selected') is not None
    assert executor.execute('query_data','[]')['error'] == 'validation_error'
    assert executor.execute('insert_rows','{}')['error'] == 'library_scope'
    search = MagicMock(return_value=[])
    monkeypatch.setattr(rag,'hybrid_search_documents',search)
    monkeypatch.setattr(rag,'document_index_coverage',lambda *_:{'updating':0})
    assert executor.execute('search_documents','{"query":"정책"}')['count'] == 0
    search.assert_not_called()
    executor.library_refs = [{'file_id':str(uuid4()),'kind':'document','project_id':str(uuid4())}]
    executor.execute('search_documents','{"query":"정책"}')
    assert search.call_args.kwargs['file_ids'] == [executor.library_refs[0]['file_id']]
    assert search.call_args.kwargs['project_id'] is None


def test_external_store_file_is_queryable_without_loading_unselected_tables(live,monkeypatch):
    from app import agent_tools, sql_executor
    monkeypatch.setattr(sql_executor,'_connect',live.connect)
    external = library.store_file(live.user,live.other,'branch.csv',b'amount\n123.45\n')
    external = library.prepare_file(live.user,external['file_id'],live.other)
    table_imports.create_imported_table(live.user,live.other,'Unselected',b'amount\n9999.99\n','outside.csv',live.storage)
    refs = library.resolve_references(live.user,live.store,[{**selection(external),'include_other_store':True}],confirmed=True)
    executor = agent_tools.ToolExecutor(live.user,live.store,library_refs=refs)
    assert len(executor._tables) == 1
    assert executor._resolve_table('Unselected') is None
    assert '연남점' in refs[0]['query_table_name']
    result = executor.execute('query_data',json.dumps({'table_name':refs[0]['query_table_name'],'operation':'sum','value_column':'amount'}))
    assert 'error' not in result, result
    assert Decimal(str(next(iter(result['data'][0].values())))) == Decimal('123.45')


def test_discovery_keeps_large_candidate_pages_structured_for_ui():
    from app.agent import AgentStep, _tool_result_content
    output = {'files':[{'file_id':str(uuid4()),'filename':'월별매출'*50+'.csv','bindings':[{'table_name':'원본에 연결된 누적 장부','project_name':'성수점','table_id':str(uuid4())}]} for _ in range(10)],'next_offset':10}
    assert len(json.dumps(output,ensure_ascii=False)) > 3000
    stored = AgentStep(type='tool_call',tool_name='search_library_files',tool_output=output).to_dict()
    assert len(stored['tool_output']['files']) == 10
    assert json.loads(_tool_result_content('search_library_files',output))['next_offset'] == 10


def test_project_purge_keeps_originals_even_with_identical_unassigned_file(live):
    upload(live)
    upload(live,project=False)
    with live.connect() as conn:
        conn.execute('DELETE FROM projects WHERE id=%s',(live.store,))
    files = library.list_library(live.user)['files']
    assert len(files) == 2 and all(f['project_id'] is None for f in files)


def test_missing_original_has_clear_gone_response(live):
    file = upload(live)
    row = library.get_record(live.user,file['file_id'])
    from pathlib import Path
    target = Path(row['storage_key']).resolve()
    assert target.is_relative_to(live.storage._local_root.resolve())
    target.unlink()
    for suffix in ('/preview','/download'):
        assert live.client.get(f"/api/library/files/{file['file_id']}{suffix}").status_code == 410
    assert live.client.post(f"/api/library/files/{file['file_id']}/prepare",json={'project_id':live.store}).status_code == 410
