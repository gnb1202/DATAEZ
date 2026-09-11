"""Real scheduled indexing, metric refresh and expiration with synthetic data.

Uses the configured embedding API for one tiny document and schema, never the
chat agent. Account/DB/Storage fixtures are removed even when checks fail.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import logging
import os
from pathlib import Path
import secrets
import sys
import time
from uuid import uuid4

from dotenv import dotenv_values
import httpx
import psycopg
from psycopg import sql

ROOT=Path(__file__).resolve().parents[2]
REF='whbygnzoaehvlddltwlb'


def main(deployment, scheduled=False):
    config=dict(dotenv_values(ROOT/'.env.supabase.local'))
    assert config['SUPABASE_URL']==f'https://{REF}.supabase.co'
    os.environ.update(config);sys.path.insert(0,str(ROOT/'api'))
    from app import db
    from app.storage import StorageService
    store=StorageService();logging.disable(logging.CRITICAL)
    bypass={'x-vercel-protection-bypass':config['MAINTENANCE_VERCEL_BYPASS']}
    maintenance={'Authorization':'Bearer '+config['MAINTENANCE_SECRET']}
    emails=[];keys=set();checks=[]
    report={'deployment':deployment,'scheduled':scheduled,'checks':checks,'real_embeddings':True,'chat_agent_called':False}
    try:
        with httpx.Client(base_url=deployment,headers=bypass,timeout=160,follow_redirects=False) as client:
            def request(method,path,**kwargs):
                r=client.request(method,path,**kwargs)
                assert r.status_code in (200,201),f'{method} {path} HTTP {r.status_code}'
                return r.json()
            assert client.post('/api/internal/maintenance/index').status_code==401
            assert client.post('/api/internal/maintenance/index',headers={'Authorization':'Bearer wrong'}).status_code==401
            checks.append('internal_runner_rejects_missing_and_wrong_secret')
            email=f'maintenance-check-{uuid4().hex}@example.invalid';emails.append(email)
            user=request('POST','/api/auth/signup',json={'email':email,'password':'Aa1!'+secrets.token_urlsafe(24)})
            uid=user['user_id'];headers={'Authorization':'Bearer '+user['access_token']}
            assert client.post('/api/internal/maintenance/index',headers=headers).status_code==401
            project=request('POST','/api/projects',headers=headers,json={'name':'Maintenance verification'})['id']
            csv=request('POST','/api/library/files',headers=headers,data={'project_id':project},files={'file':('매출.csv',b'amount\n100\n','text/csv')})
            prepared=request('POST',f"/api/library/files/{csv['file_id']}/prepare",headers=headers,json={'project_id':project})
            tid=prepared['bindings'][0]['table_id']
            metric=request('POST',f'/api/projects/{project}/metrics',headers=headers,json={'title':'예약 합계','definition':{'table_id':tid,'column':'amount','operation':'sum'},'refresh_interval_seconds':3600})
            assert str(metric['widget_data']['value'])=='100'
            document=request('POST','/api/library/files',headers=headers,data={'project_id':project},files={'file':('환불규정.txt','환불은 예약일 하루 전까지 가능합니다. 당일 취소는 환불되지 않습니다.'.encode(),'text/plain')})
            request('POST',f"/api/library/files/{document['file_id']}/prepare",headers=headers,json={'project_id':project})
            # Expired reservation has never issued a token, so synthetic cleanup
            # is safe immediately. A live sibling must remain untouched.
            expired,active=str(uuid4()),str(uuid4())
            for sid in (expired,active):
                key=f"uploads/direct/{sid.replace('-','')}.txt";keys.add(key);store._supabase.put(key,b'fixture')
                with db._connect() as conn:
                    conn.execute('''INSERT INTO upload_sessions(id,user_id,project_id,request_id,filename,storage_key,size_bytes,content_hash)
                        VALUES(%s,%s,%s,%s,'fixture.txt',%s,7,%s)''',(sid,uid,project,str(uuid4()),key,'a'*64))
            with db._connect() as conn:
                conn.execute("UPDATE upload_sessions SET expires_at=now()-interval '11 minutes' WHERE id=%s",(expired,))
                table=db.get_user_table_name(uid,tid)
                conn.execute(sql.SQL('INSERT INTO {}(amount) VALUES (200)').format(sql.Identifier(table)))
                conn.execute("UPDATE dashboard_widgets SET next_refresh_at=now()-interval '1 second' WHERE id=%s",(metric['id'],))
            if scheduled:
                from configure_maintenance_cron import run_sql,dispatch_sql
                # Same pg_net dispatch as the ten-minute cleanup schedule.
                run_sql(dispatch_sql('cleanup'))
                print('Waiting for actual Supabase index/metric cron ticks...',flush=True)
                deadline=time.monotonic()+150
                while time.monotonic()<deadline:
                    with db._connect() as conn:
                        pending=conn.execute("SELECT count(*) AS n FROM search_index_jobs WHERE user_id=%s AND status<>'succeeded'",(uid,)).fetchone()['n']
                        value=conn.execute("SELECT widget_data->>'value' AS value FROM dashboard_widgets WHERE id=%s",(metric['id'],)).fetchone()['value']
                        remaining=conn.execute('SELECT count(*) AS n FROM upload_sessions WHERE id=%s',(expired,)).fetchone()['n']
                    if pending==0 and value=='300' and remaining==0:break
                    time.sleep(3)
                else:raise AssertionError('Scheduled fixtures did not complete within 150 seconds')
                checks.append('actual_cron_index_and_metric_ticks_with_pg_net_cleanup_dispatch')
            else:
                for kind in ('index','metrics','cleanup'):
                    result=request('POST','/api/internal/maintenance/'+kind,headers=maintenance)
                    assert result['status']=='succeeded',f'{kind} runner did not finish'
                checks.append('all_three_child_processes_complete_in_deployed_python_runtime')
            with db._connect() as conn:
                jobs=conn.execute('SELECT status FROM search_index_jobs WHERE user_id=%s',(uid,)).fetchall()
                assert len(jobs)==2 and all(j['status']=='succeeded' for j in jobs)
                assert conn.execute('SELECT count(*) AS n FROM document_chunks WHERE file_id=%s AND embedding IS NOT NULL',(document['file_id'],)).fetchone()['n']>0
                assert conn.execute('SELECT count(*) AS n FROM schema_embeddings WHERE table_meta_id=%s AND embedding IS NOT NULL',(tid,)).fetchone()['n']==1
                row=conn.execute('SELECT widget_data,next_refresh_at>now() AS future,refresh_failures FROM dashboard_widgets WHERE id=%s',(metric['id'],)).fetchone()
                assert str(row['widget_data']['value'])=='300' and row['future'] and row['refresh_failures']==0
                assert conn.execute('SELECT count(*) AS n FROM upload_sessions WHERE id=%s',(expired,)).fetchone()['n']==0
                assert conn.execute('SELECT count(*) AS n FROM upload_sessions WHERE id=%s',(active,)).fetchone()['n']==1
            checks.extend(['real_document_and_schema_vectors_committed','scheduled_metric_100_to_300_and_next_refresh_advanced','expired_upload_removed_live_upload_preserved'])
            for sid in (active,):
                assert store._supabase.get(f"uploads/direct/{sid.replace('-','')}.txt")==b'fixture'
            try:
                store._supabase.get(f"uploads/direct/{expired.replace('-','')}.txt")
                raise AssertionError('Expired original still present')
            except FileNotFoundError:pass
            assert request('GET',f"/api/library/files/{document['file_id']}",headers=headers)['status']=='document_ready'
            checks.append('library_reports_document_ready')
            report['maintenance_status']=request('GET','/api/internal/maintenance/status',headers=maintenance)
    finally:
        db.close_pool()
        with psycopg.connect(config['DATABASE_URL'],prepare_threshold=None,connect_timeout=10) as conn:
            ids=[r[0] for r in conn.execute('SELECT id FROM users WHERE email=ANY(%s)',(emails,)).fetchall()]
            if ids:
                keys.update(r[0] for r in conn.execute('SELECT storage_key FROM upload_sessions WHERE user_id=ANY(%s)',(ids,)).fetchall())
                keys.update(r[0] for r in conn.execute('SELECT storage_key FROM files WHERE user_id=ANY(%s)',(ids,)).fetchall())
                for uid,tid in conn.execute('SELECT user_id,id FROM table_meta WHERE user_id=ANY(%s)',(ids,)).fetchall():
                    conn.execute(sql.SQL('DROP TABLE IF EXISTS {}').format(sql.Identifier(db.get_user_table_name(str(uid),str(tid)))))
                for name in ('upload_sessions','audit_log','query_history','dashboard_widgets','conversations','search_index_jobs','schema_embeddings','document_chunks','table_meta','library_entries','refresh_tokens','projects','files','users'):
                    conn.execute(sql.SQL('DELETE FROM {} WHERE {}=ANY(%s)').format(sql.Identifier(name),sql.Identifier('id' if name=='users' else 'user_id')),(ids,))
        for key in keys:store._supabase.delete(key)
        report['synthetic_data_removed']=True
    name='maintenance-cron.json' if scheduled else 'maintenance-vercel.json'
    (ROOT/'docs/evaluations/vercel-api'/name).write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--deployment',required=True);parser.add_argument('--scheduled',action='store_true');args=parser.parse_args()
    try:main(args.deployment,args.scheduled)
    except Exception as error:
        import traceback
        print('Failure location:',[(Path(f.filename).name,f.lineno) for f in traceback.extract_tb(error.__traceback__)])
        print('Maintenance verification failed:',type(error).__name__,str(error) if isinstance(error,AssertionError) else '')
        raise SystemExit(1)
