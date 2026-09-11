"""Public, credential-free transport checks plus a real browser/LLM demo; clean fixtures."""
import argparse
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
from uuid import uuid4

from dotenv import dotenv_values
import httpx
import psycopg
from psycopg import sql

ROOT=Path(__file__).resolve().parents[2]


def main(api):
    config=dict(dotenv_values(ROOT/'.env.supabase.local'))
    assert config['SUPABASE_URL']=='https://whbygnzoaehvlddltwlb.supabase.co'
    os.environ.update(config);sys.path.insert(0,str(ROOT/'api'))
    from app import db
    from app.storage import StorageService
    email='public-demo-'+uuid4().hex+'@example.invalid'
    password='Aa1!'+secrets.token_urlsafe(24)
    report={'api':api,'ui':'https://dataez.vercel.app','checks':[],'browser_exit_code':None}
    keys=set()
    try:
        with httpx.Client(base_url=api,timeout=45,follow_redirects=False) as client:
            assert client.get('/health').status_code==200
            assert client.get('/api/projects').status_code in (401,403)
            assert client.get('/api/internal/maintenance/status').status_code==401
            for origin,allowed in [('https://dataez.vercel.app',True),('https://untrusted.example',False)]:
                cors=client.options('/api/auth/login',headers={'Origin':origin,'Access-Control-Request-Method':'POST','Access-Control-Request-Headers':'authorization,content-type'})
                assert (cors.headers.get('access-control-allow-origin')==origin)==allowed
            report['checks'].append('Public health; account/internal authentication and allowed/disallowed CORS origins')
            response=client.post('/api/auth/signup',json={'email':email,'password':password})
            assert response.status_code==200,f'Signup HTTP {response.status_code}'
            account=response.json();token=account['access_token']
            project=client.post('/api/projects',headers={'Authorization':'Bearer '+token},json={'name':'성수점 · 공개 데모 검증'}).json()['id']
            payload={'api':api,'email':email,'password':password,'token':token,'project':project}
        run=subprocess.run(['node',str(ROOT/'scripts/ui-eval/public-demo.cjs')],input=json.dumps(payload),
            cwd=ROOT,capture_output=True,text=True,encoding='utf-8',timeout=420)
        report['browser_exit_code']=run.returncode
        print(run.stdout)
        if run.returncode:print(run.stderr.replace(password,'[redacted]').replace(token,'[redacted]')[-1800:])
    finally:
        db.close_pool()
        with psycopg.connect(config['DATABASE_URL'],prepare_threshold=None,connect_timeout=10) as conn:
            ids=[row[0] for row in conn.execute('SELECT id FROM users WHERE email=%s',(email,))]
            if ids:
                keys.update(row[0] for row in conn.execute('SELECT storage_key FROM upload_sessions WHERE user_id=ANY(%s)',(ids,)))
                keys.update(row[0] for row in conn.execute('SELECT storage_key FROM files WHERE user_id=ANY(%s)',(ids,)))
                for uid,tid in conn.execute('SELECT user_id,id FROM table_meta WHERE user_id=ANY(%s)',(ids,)):
                    conn.execute(sql.SQL('DROP TABLE IF EXISTS {}').format(sql.Identifier(db.get_user_table_name(str(uid),str(tid)))))
                for name in ('upload_sessions','audit_log','query_history','dashboard_widgets','conversations','search_index_jobs','schema_embeddings','document_chunks','table_meta','library_entries','refresh_tokens','projects','files','users'):
                    field='id' if name=='users' else 'user_id'
                    conn.execute(sql.SQL('DELETE FROM {} WHERE {}=ANY(%s)').format(sql.Identifier(name),sql.Identifier(field)),(ids,))
        store=StorageService()._supabase
        for key in keys:store.delete(key)
        report['synthetic_data_removed']=True
        target=ROOT/'docs/evaluations/public-demo';target.mkdir(parents=True,exist_ok=True)
        (target/'deployment-check.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    return report['browser_exit_code'] or 0


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--api',required=True)
    raise SystemExit(main(parser.parse_args().api))
