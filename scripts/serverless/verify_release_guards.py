"""Protected deployed API: stored-source paths and one real streamed AI greeting."""
import argparse
import hashlib
import json
import logging
import os
from pathlib import Path
import secrets
import sys
from uuid import uuid4

from dotenv import dotenv_values
import httpx
import psycopg
from psycopg import sql

ROOT=Path(__file__).resolve().parents[2]


def main(deployment):
    config=dict(dotenv_values(ROOT/'.env.supabase.local'))
    assert config['SUPABASE_URL']=='https://whbygnzoaehvlddltwlb.supabase.co'
    os.environ.update(config);sys.path.insert(0,str(ROOT/'api'))
    from app import db
    from app.storage import StorageService
    logging.disable(logging.CRITICAL)
    storage=StorageService();emails=[];keys=set();staged=set();checks=[]
    report={'deployment':deployment,'checks':checks,'real_llm_calls':True}
    try:
        with httpx.Client(base_url=deployment,headers={'x-vercel-protection-bypass':config['MAINTENANCE_VERCEL_BYPASS']},timeout=235) as client:
            def request(method,path,**kwargs):
                response=client.request(method,path,**kwargs)
                assert response.status_code in (200,201),f'{method} {path}: HTTP {response.status_code}'
                return response.json()
            email='release-guards-'+uuid4().hex+'@example.invalid';emails.append(email)
            account=request('POST','/api/auth/signup',json={'email':email,'password':'Aa1!'+secrets.token_urlsafe(24)})
            user=account['user_id'];headers={'Authorization':'Bearer '+account['access_token']}
            project=request('POST','/api/projects',headers=headers,json={'name':'Release verification'})['id']
            other=request('POST','/api/projects',headers=headers,json={'name':'Scope verification'})['id']
            base='/api/projects/'+project
            def upload(name,content):
                reservation=request('POST','/api/uploads',headers=headers,json={'request_id':str(uuid4()),'project_id':project,
                    'filename':name,'size_bytes':len(content),'content_hash':hashlib.sha256(content).hexdigest()})
                response=httpx.put(reservation['upload_url'],content=content,headers={'Content-Type':'application/octet-stream'},timeout=60)
                assert response.status_code==200
                return request('POST','/api/uploads/'+reservation['session_id']+'/complete',headers=headers)['file_id']
            csv=upload('매출.csv',b'event_id,amount,occurred_at\nx-1,20000,2026-09-01\n')
            body={'stored_file_id':csv,'table_name':'Sales'}
            table=request('POST',base+'/tables/import',headers=headers,data=body)
            again=request('POST',base+'/tables/import',headers=headers,data=body)
            assert table['id']==again['id'] and table['source_file_id']==csv
            appended=request('POST',base+'/tables/'+table['id']+'/append',headers=headers,data={'stored_file_id':csv})
            assert appended['rows_inserted']==1 and appended['total_row_count']==2
            checks.append('stored_source_import_replays_same_table_and_append_preserves_semantics')
            denied=client.post('/api/projects/'+other+'/tables/import',headers=headers,data=body)
            assert denied.status_code==409
            assert client.post(base+'/tables/import',headers=headers,data=body,files={'file':('x.csv',b'amount\n1\n')}).status_code==422
            checks.append('cross_store_and_ambiguous_uploads_rejected')
            mapping={'amount_column':'amount','occurred_at_column':'occurred_at','event_id_column':'event_id','event_kind':'payment'}
            inspected=request('POST',base+'/import-mapping/inspect',headers=headers,data={'stored_file_id':csv})
            assert inspected['row_count']==1
            checked=request('POST',base+'/import-mapping/validate',headers=headers,data={'stored_file_id':csv,'mapping':json.dumps(mapping)})
            assert str(checked['amount']) in ('20000','20000.00')
            source=request('POST',base+'/ledger-sources',headers=headers,json={'name':'Test PG','provider':'fixture','account':'fixture','feed':'payments','mapping':mapping})
            batch=request('POST',base+'/imports',headers=headers,data={'source_id':source['id'],'request_key':str(uuid4()),'stored_file_id':csv})
            assert batch['status']=='uploaded'
            checks.append('mapping_inspect_validate_and_payment_batch_accept_only_file_id')
            doc=upload('환불규정.txt','예약 하루 전까지 환불할 수 있습니다.'.encode())
            document=request('POST',base+'/documents',headers=headers,data={'stored_file_id':doc})
            assert document['file_id']==doc
            checks.append('document_registration_reuses_owned_original')
            conversation=request('POST','/api/conversations',headers=headers,json={'project_id':project})['conversation_id']
            response=client.post('/api/conversations/'+conversation+'/messages/stream',headers=headers,data={'message':'안녕하세요'})
            assert response.status_code==200
            frames=[json.loads(line[5:]) for line in response.text.splitlines() if line.startswith('data:')]
            assert not any(f['type']=='error' for f in frames), 'Agent returned an error frame'
            done=next(f['data'] for f in frames if f['type']=='done')
            assert done['content'] and done['usage']['total_tokens']>0
            report['ai_usage']=done['usage']
            checks.append('real_streamed_llm_runs_in_bounded_child_and_persists_usage')
            with db._connect() as conn:
                for key in ('ai-day:user:'+user,'ai-day:application'):
                    assert conn.execute('SELECT used FROM request_limits WHERE key_hash=%s',(hashlib.sha256(key.encode()).hexdigest(),)).fetchone()['used']>=1
                row=conn.execute("SELECT rowsecurity,tableowner FROM pg_tables WHERE schemaname='public' AND tablename='request_limits'").fetchone()
                assert row['rowsecurity'] and row['tableowner']=='dataez_app'
                assert not conn.execute("SELECT has_table_privilege('anon','request_limits','SELECT') allowed").fetchone()['allowed']
            checks.append('deployed_shared_ai_budget_and_rls_verified')
    finally:
        db.close_pool()
        with psycopg.connect(config['DATABASE_URL'],prepare_threshold=None,connect_timeout=10) as conn:
            ids=[r[0] for r in conn.execute('SELECT id FROM users WHERE email=ANY(%s)',(emails,))]
            if ids:
                keys.update(r[0] for r in conn.execute('SELECT storage_key FROM upload_sessions WHERE user_id=ANY(%s)',(ids,)))
                keys.update(r[0] for r in conn.execute('SELECT storage_key FROM files WHERE user_id=ANY(%s)',(ids,)))
                sources=[r[0] for r in conn.execute('SELECT id FROM ledger_sources WHERE user_id=ANY(%s)',(ids,))]
                if sources:
                    staged.update(r[0] for r in conn.execute('SELECT storage_key FROM import_batches WHERE source_id=ANY(%s)',(sources,)))
                    conn.execute('DELETE FROM import_requests WHERE source_id=ANY(%s)',(sources,))
                    conn.execute('DELETE FROM import_batches WHERE source_id=ANY(%s)',(sources,))
                    conn.execute('DELETE FROM ledger_sources WHERE user_id=ANY(%s)',(ids,))
                for uid,tid in conn.execute('SELECT user_id,id FROM table_meta WHERE user_id=ANY(%s)',(ids,)):
                    conn.execute(sql.SQL('DROP TABLE IF EXISTS {}').format(sql.Identifier(db.get_user_table_name(str(uid),str(tid)))))
                for name in ('upload_sessions','audit_log','query_history','dashboard_widgets','conversations','search_index_jobs','schema_embeddings','document_chunks','table_meta','library_entries','refresh_tokens','projects','files','users'):
                    field='id' if name=='users' else 'user_id'
                    conn.execute(sql.SQL('DELETE FROM {} WHERE {}=ANY(%s)').format(sql.Identifier(name),sql.Identifier(field)),(ids,))
        for key in keys: storage._supabase.delete(key)
        for key in staged: storage.delete_staged(key)
        report['synthetic_data_removed']=True
    (ROOT/'docs/evaluations/vercel-api/release-guards-vercel.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--deployment',required=True)
    main(parser.parse_args().deployment)
