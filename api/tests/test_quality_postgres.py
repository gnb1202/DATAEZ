"""Real PostgreSQL ownership, persistence, retention and export isolation."""
import os
from contextlib import contextmanager
from unittest.mock import patch
from uuid import uuid4

import psycopg
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from psycopg import sql
from psycopg.rows import dict_row

from app import db, quality
from app.auth import get_current_user

DSN = os.environ.get('DATAEZ_TEST_DATABASE_URL')
pytestmark = pytest.mark.skipif(not DSN, reason='Set DATAEZ_TEST_DATABASE_URL for real PostgreSQL')


@pytest.fixture
def live():
    schema = 'dataez_quality_test_' + uuid4().hex
    owner, other, admin, conv = [str(uuid4()) for _ in range(4)]
    with psycopg.connect(DSN, autocommit=True) as conn:
        conn.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(schema)))
    @contextmanager
    def connect():
        with psycopg.connect(DSN, options=f'-c search_path={schema}', row_factory=dict_row) as conn: yield conn
    try:
        with connect() as conn:
            conn.execute('CREATE TABLE users(id uuid PRIMARY KEY); CREATE TABLE files(id uuid PRIMARY KEY)')
            for user in (owner,other,admin): conn.execute('INSERT INTO users VALUES(%s)', (user,))
        app = FastAPI(); app.include_router(quality.router)
        identity = {'id':owner}
        app.dependency_overrides[get_current_user] = lambda: identity
        with patch.object(db,'_connect',connect), patch.object(db,'record_audit') as audit, patch.object(quality.settings,'quality_admin_user_ids',admin), TestClient(app) as client:
            db.ensure_conversation_tables()
            with connect() as conn:
                conn.execute('ALTER TABLE conversations ADD COLUMN project_id uuid; ALTER TABLE conversations ADD COLUMN table_id uuid')
            db.create_conversation(conv,owner,None)
            quality.ensure_quality(); quality.ensure_quality()
            run = quality.start_run(conv)
            token = quality.active_run.set(run)
            q, a = str(uuid4()),str(uuid4())
            db.save_message(q,conv,'user','PRIVATE QUESTION',steps=[{'type':'library_references','file_id':'PRIVATE'}])
            db.save_message(a,conv,'assistant','PRIVATE ANSWER',steps=[{'type':'tool_call','tool_name':'query_data','tool_input':{'operation':'sum'}}], charts=[{'chart_type':'line','data':[{'amount':300}]}], table_data=[{'amount':300}], usage={'total_tokens':30,'cost_usd':0.1})
            quality.active_run.reset(token)
            quality.finish_run(run,'completed')
            yield client,connect,identity,owner,other,admin,conv,run,q,a,audit
    finally:
        assert schema.startswith('dataez_quality_test_') and len(schema) == 52
        with psycopg.connect(DSN,autocommit=True) as conn:
            conn.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(schema)))


def test_owner_feedback_retry_and_isolation(live):
    client,connect,identity,owner,other,admin,conv,run,q,a,_ = live
    path=f'/api/quality/messages/{a}/feedback'
    for _ in range(2): assert client.put(path,json={'rating':-1,'reason':'calculation'}).status_code == 200
    with connect() as conn: assert conn.execute('SELECT count(*) AS n FROM message_feedback').fetchone()['n'] == 1
    assert client.get(path).json()['feedback']['rating'] == -1
    assert client.put(f'/api/quality/messages/{q}/feedback',json={'rating':1}).status_code == 404
    identity['id']=other
    assert client.get(path).status_code == 404
    assert client.put(path,json={'rating':1}).status_code == 404
    assert client.get('/api/quality/runs').status_code == 403
    assert client.get(f'/api/quality/runs/{run}').status_code == 403
    assert client.put(f'/api/quality/runs/{run}/review',json={'verdict':'pass'}).status_code == 403
    assert client.get('/api/quality/access').json() == {'admin':False}


def test_admin_review_export_excludes_original_and_requires_failure(live):
    client,_,identity,_,_,admin,_,run,_,_,audit=live
    identity['id']=admin
    detail=client.get(f'/api/quality/runs/{run}')
    assert detail.headers['cache-control'] == 'no-store'
    data=detail.json(); assert data['answer']=='PRIVATE ANSWER' and data['usage']['total_tokens']==30
    assert data['duration_ms'] >= 0 and len(data['version']['code_sha256']) == 64
    candidate={'question':'합성 가게의 일별 매출을 보여줘','expected_behavior':'합성 원본에 있는 금액만 집계한다','synthetic_confirmed':True}
    path=f'/api/quality/runs/{run}'
    assert client.put(path+'/candidate',json=candidate).status_code==409
    assert client.put(path+'/review',json={'verdict':'fail','category':'scope','note':'범위 오류'}).status_code==200
    assert client.put(path+'/candidate',json={**candidate,'synthetic_confirmed':False}).status_code==422
    assert client.put(path+'/candidate',json=candidate).status_code==200
    export=client.get(path+'/candidate')
    assert export.status_code==200 and 'PRIVATE' not in export.text and run not in export.text and admin not in export.text
    assert client.get('/api/quality/runs?status=completed').json()['total']==1
    assert client.get('/api/quality/runs?status=failed').json()['total']==0
    assert client.get('/api/quality/runs?offset=30').json()['runs']==[]
    assert audit.call_count >= 5
    client.put(path+'/review',json={'verdict':'pass'})
    assert client.get(path+'/candidate').status_code==409


def test_stale_not_success_and_delete_cascades(live):
    client,connect,identity,owner,_,admin,conv,run,_,a,_=live
    client.put(f'/api/quality/messages/{a}/feedback',json={'rating':1})
    with connect() as conn: conn.execute("UPDATE quality_runs SET status='running',started_at=now()-interval '20 minutes',finished_at=NULL WHERE id=%s",(run,))
    identity['id']=admin
    assert client.get('/api/quality/runs?status=unconfirmed').json()['total']==1
    assert db.delete_conversation(conv,owner)
    with connect() as conn:
        for table in ('quality_runs','message_feedback','messages'):
            assert conn.execute(f'SELECT count(*) AS n FROM {table}').fetchone()['n']==0


def test_rls_and_no_public_grants(live):
    _,connect,*_=live
    with connect() as conn:
        rows=conn.execute("SELECT relname,relrowsecurity FROM pg_class WHERE relnamespace=current_schema()::regnamespace AND relname IN ('quality_runs','message_feedback')").fetchall()
        assert len(rows)==2 and all(r['relrowsecurity'] for r in rows)
        assert not conn.execute("SELECT 1 FROM pg_class c,LATERAL aclexplode(c.relacl) a WHERE c.relnamespace=current_schema()::regnamespace AND c.relname IN ('quality_runs','message_feedback') AND a.grantee=0").fetchall()


def test_feedback_validation_and_unauthenticated(live):
    client,_,identity,_,_,admin,_,run,_,a,_=live
    assert client.put(f'/api/quality/messages/{a}/feedback',json={'rating':0}).status_code==422
    assert client.put(f'/api/quality/messages/{a}/feedback',json={'rating':-1,'comment':'a'*1001}).status_code==422
    identity['id']=admin
    assert client.get('/api/quality/runs?limit=1000').status_code==422
    client.app.dependency_overrides.clear()
    assert client.get('/api/quality/runs').status_code in (401,403)
    assert client.get(f'/api/quality/runs/{run}').status_code in (401,403)


def test_terminal_write_is_idempotent(live):
    _,connect,_,_,_,_,_,run,*_=live
    quality.finish_run(run,'failed','late_error')
    with connect() as conn: assert conn.execute('SELECT status FROM quality_runs WHERE id=%s',(run,)).fetchone()['status']=='completed'


@pytest.mark.parametrize('streaming', [False, True])
def test_http_wrapper_links_both_messages_and_persists_state(live, streaming):
    from starlette.responses import StreamingResponse
    client,connect,_,_,_,_,conv,*_=live
    @client.app.post('/test/messages/{conversation_id}')
    @quality.observed_chat
    async def endpoint(conversation_id: str):
        db.save_message(str(uuid4()),conversation_id,'user','synthetic request')
        if not streaming:
            db.save_message(str(uuid4()),conversation_id,'assistant','synthetic answer')
            return {'steps':[]}
        async def body():
            db.save_message(str(uuid4()),conversation_id,'assistant','synthetic answer')
            yield 'data: {"type":"done"}\n\n'
        return StreamingResponse(body())
    assert client.post(f'/test/messages/{conv}').status_code == 200
    with connect() as conn:
        rows=conn.execute('SELECT * FROM quality_runs ORDER BY started_at').fetchall()
        assert len(rows)==2
        assert rows[-1]['user_message_id'] and rows[-1]['assistant_message_id']
        assert rows[-1]['status']=='completed'
