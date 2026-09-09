"""Multi-store acceptance using a fresh loopback DB, real API, models, and browser."""
from datetime import datetime, timedelta
from decimal import Decimal
import importlib.util
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import sys
from uuid import uuid4
from unittest.mock import patch
from zoneinfo import ZoneInfo
import httpx
import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from psycopg.rows import dict_row
from dotenv import dotenv_values

ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('live_runtime',ROOT/'scripts/ui-eval/live-run.py')
runtime=importlib.util.module_from_spec(spec); spec.loader.exec_module(runtime)


def dump(path,value):
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2,default=str)+'\n',encoding='utf-8')


def main():
    admin=os.environ['DATAEZ_RAG_TEST_DATABASE_URL']; config=conninfo_to_dict(admin)
    assert config.get('host') in {'127.0.0.1','localhost','::1'} and not config.get('hostaddr')
    name='dataez_stores_eval_'+uuid4().hex
    out=ROOT/'scripts/store-metrics-eval/artifacts'/name; out.mkdir(parents=True)
    ordinary=os.environ.copy(); env=ordinary.copy(); local=dotenv_values(ROOT/'.env')
    env['OPENAI_API_KEY']=env.get('OPENAI_API_KEY') or local.get('OPENAI_API_KEY','')
    if not env['OPENAI_API_KEY']: raise ValueError('Real model API key required')
    api_port,web_port=runtime.free_port(),runtime.free_port()
    dsn=make_conninfo(admin,dbname=name)
    env.update(DATABASE_URL=dsn,JWT_SECRET_KEY=secrets.token_hex(32),APP_ENV='development',RAG_ENABLED='true',
        INDEX_WORKER_ENABLED='true',STORAGE_BACKEND='local',LOCAL_STORAGE_PATH=str(out/'uploads'),
        METRIC_SCHEDULER_ENABLED='false',IMPORT_CLEANUP_ENABLED='false',REDIS_URL='redis://127.0.0.1:1/0',
        UPLOAD_RATE_LIMIT_PER_MINUTE='100',QUERY_RATE_LIMIT_PER_MINUTE='100',
        OPENAI_MODEL='gpt-5.4',OPENAI_ORCHESTRATOR_MODEL='gpt-5.4-nano',
        ALLOWED_ORIGINS=f'http://127.0.0.1:{web_port}',NEXT_PUBLIC_API_URL=f'http://127.0.0.1:{api_port}',
        LIVE_UI_URL=f'http://127.0.0.1:{web_port}',LIVE_ARTIFACTS=str(out),PYTHONIOENCODING='utf-8')
    node=shutil.which('node'); processes=[]; logs=[]; created=built=False
    report={'run_id':name,'synthetic':True,'real_browser':True,'real_models':True,'api_mocks':False,'passed':False,'checks':[]}
    def check(label,actual,expected):
        ok=actual==expected; report['checks'].append({'check':label,'actual':actual,'expected':expected,'passed':ok})
        assert ok,f'{label}: {actual!r} != {expected!r}'
    def start(args,cwd,label):
        log=(out/(label+'.log')).open('w',encoding='utf-8'); logs.append(log)
        process=subprocess.Popen(args,cwd=cwd,env=env,stdout=log,stderr=subprocess.STDOUT,creationflags=runtime.HIDDEN)
        processes.append(process); return process
    try:
        with psycopg.connect(admin,autocommit=True) as conn: conn.execute(sql.SQL("CREATE DATABASE {} TEMPLATE template0 ENCODING 'UTF8'").format(sql.Identifier(name)))
        created=True
        with psycopg.connect(dsn) as conn: conn.execute((ROOT/'db/init.sql').read_text(encoding='utf-8'))
        api=start([sys.executable,'-m','uvicorn','app.main:app','--host','127.0.0.1','--port',str(api_port)],ROOT/'api','api')
        runtime.wait_http(env['NEXT_PUBLIC_API_URL']+'/health',api)
        with httpx.Client(base_url=env['NEXT_PUBLIC_API_URL'],timeout=240) as client:
            def request(method,path,**kw):
                response=client.request(method,path,**kw); response.raise_for_status(); return response.json()
            email,password=name+'@example.test',secrets.token_urlsafe(20)+'Aa1!'
            owner=request('POST','/api/auth/signup',json={'email':email,'password':password,'name':'지표·현금 검증'})
            uid=owner['user_id']; client.headers['Authorization']='Bearer '+owner['access_token']
            stores={}; tables={}
            month=datetime.now(ZoneInfo('Asia/Seoul')).date().replace(day=1); previous=(month-timedelta(days=1)).replace(day=1)
            for label,current,refund,prior in [('강남점',100000,-20000,60000),('홍대점',200000,-30000,40000),('수원점',0,0,99999999)]:
                pid=request('POST','/api/projects',json={'name':label})['id']; stores[label]=pid
                csv=f'amount,currency,occurred_at,event_kind\n{prior},KRW,{previous}T12:00:00+09:00,payment\n'
                if current: csv+=f'{current},KRW,{month}T12:00:00+09:00,payment\n{refund},KRW,{month}T13:00:00+09:00,refund\n'
                tables[label]=request('POST',f'/api/projects/{pid}/tables/import',files={'file':('pg-synthetic.csv',csv.encode())},data={'table_name':'결제원장'})
                runtime.wait_indexes(request,f'/api/projects/{pid}')
            pid=stores['강남점']; base=f'/api/projects/{pid}'
            dump(out/'browser-input.json',{'email':email,'password':password,'project_id':pid,'stores':stores,'tables':{k:v['id'] for k,v in tables.items()}})
            built=True; build=start([node,'node_modules/next/dist/bin/next','build'],ROOT/'web','build')
            if build.wait(timeout=240): raise RuntimeError('Web build failed')
            web=start([node,'node_modules/next/dist/bin/next','start','-p',str(web_port),'-H','127.0.0.1'],ROOT/'web','web')
            runtime.wait_http(env['LIVE_UI_URL'],web)
            print('Real browser/model checks: selected stores, common criteria, total, comparison, edit and empty store',flush=True)
            browser=start([node,'store-metrics.cjs'],ROOT/'scripts/ui-eval','browser')
            if browser.wait(timeout=900): raise RuntimeError('Browser acceptance failed')
            report['browser']=json.loads((out/'browser.json').read_text(encoding='utf-8'))
            with psycopg.connect(dsn,row_factory=dict_row) as conn:
                widgets=conn.execute('SELECT * FROM dashboard_widgets WHERE user_id=%s ORDER BY created_at',(uid,)).fetchall()
                report['messages']=conn.execute("SELECT m.content,m.steps,m.usage FROM messages m JOIN conversations c ON c.id=m.conversation_id WHERE c.user_id=%s AND m.role='assistant' ORDER BY m.created_at",(uid,)).fetchall()
            check('Exactly two saved metrics; empty preview not saved',len(widgets),2)
            total=next(w for w in widgets if w['title']=='두 가게 합계')
            chart=next(w for w in widgets if w['title']=='두 지점 비교')
            check('Manual total includes refunds',Decimal(total['widget_data']['value']),Decimal('250000'))
            check('Natural comparison revision',chart['widget_data']['definition_revision'],2)
            check('Previous-month comparison by store',{r['project_id']:r['value'] for r in chart['widget_data']['data']},{stores['강남점']:'60000',stores['홍대점']:'40000'})
            check('Unselected store excluded',set(s['project_id'] for s in chart['widget_data']['metric_definition']['stores'])=={stores['강남점'],stores['홍대점']},True)
            check('Hourly schedule preserved',chart['refresh_interval_seconds'],3600)
            check('Resized layout preserved',chart['layout'],report['browser']['savedLayout']['layout'])
            check('Widget identity preserved',str(chart['id']),report['browser']['savedLayout']['id'])
            check('Stored on current dashboard',str(chart['project_id']),pid)
            # Add a transaction only to the explicitly selected other store.
            with psycopg.connect(dsn) as conn:
                sys.path.insert(0,str(ROOT/'api'))
                with patch.dict(os.environ,env):
                    from app.db import get_user_table_name
                conn.execute(sql.SQL('INSERT INTO {} (amount,currency,occurred_at,event_kind) VALUES (50000,%s,%s,%s)').format(sql.Identifier(get_user_table_name(uid,tables['홍대점']['id']))),('KRW',str(month)+'T14:00:00+09:00','payment'))
            refreshed=request('POST',base+f"/metrics/{total['id']}/refresh")
            check('Refresh sees other selected store transaction',Decimal(refreshed['widget_data']['value']),Decimal('300000'))
            request('DELETE',f"/api/projects/{stores['홍대점']}")
            failed=client.post(base+f"/metrics/{total['id']}/refresh")
            check('Deleted selected store blocks recomputation',failed.status_code,422)
            history=request('GET',base+f"/metrics/{total['id']}/history")['metric']['widget_data']
            check('Last good total preserved after failure',Decimal(history['value']),Decimal('300000'))
            check('Failure visible',bool(history.get('refresh_error')),True)
            report['passed']=True
    finally:
        for process in reversed(processes): runtime.stop(process)
        if created:
            assert name.startswith('dataez_stores_eval_') and len(name)==len('dataez_stores_eval_')+32
            with psycopg.connect(admin,autocommit=True) as conn: conn.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(name)))
            report['temporary_database_removed']=True
        if built:
            with (out/'restore-build.log').open('w',encoding='utf-8') as log:
                result=subprocess.run([node,'node_modules/next/dist/bin/next','build'],cwd=ROOT/'web',env=ordinary,stdout=log,stderr=subprocess.STDOUT,creationflags=runtime.HIDDEN,timeout=240)
            report['ordinary_web_build_restored']=result.returncode==0; report['passed'] &= result.returncode==0
        for log in logs: log.close()
        dump(out/'report.json',report); print('Report: '+str(out/'report.json'),flush=True)
    return 0 if report['passed'] else 1


if __name__=='__main__': raise SystemExit(main())
