"""Grouped-formula acceptance using a fresh loopback DB, real API, models, and browser."""
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
    name='dataez_charts_eval_'+uuid4().hex
    out=ROOT/'scripts/formula-charts-eval/artifacts'/name; out.mkdir(parents=True)
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
            pid=request('POST','/api/projects',json={'name':'지표·현금 검증점'})['id']; base=f'/api/projects/{pid}'
            csv='amount,fee,channel,occurred_at,event_kind\n100000,3000,매장,2026-08-03T12:00:00+09:00,payment\n200000,6000,배달,2026-08-04T12:00:00+09:00,payment\n-20000,-600,매장,2026-08-04T13:00:00+09:00,refund\n50000,1500,매장,2026-08-10T12:00:00+09:00,payment\n300000,9000,배달,2026-09-01T12:00:00+09:00,payment\n-10000,-300,매장,2026-09-02T12:00:00+09:00,refund\n'
            table=request('POST',base+'/tables/import',files={'file':('pg-synthetic.csv',csv.encode())},data={'table_name':'검증 결제원장'})
            runtime.wait_indexes(request,base)
            dump(out/'browser-input.json',{'email':email,'password':password,'project_id':pid,'table_id':table['id']})
            built=True; build=start([node,'node_modules/next/dist/bin/next','build'],ROOT/'web','build')
            if build.wait(timeout=240): raise RuntimeError('Web build failed')
            web=start([node,'node_modules/next/dist/bin/next','start','-p',str(web_port),'-H','127.0.0.1'],ROOT/'web','web')
            runtime.wait_http(env['LIVE_UI_URL'],web)
            print('Real browser/model checks: grouped formula save, resize, edit, preview pin and SQL details',flush=True)
            browser=start([node,'formula-charts.cjs'],ROOT/'scripts/ui-eval','browser')
            if browser.wait(timeout=900): raise RuntimeError('Browser acceptance failed')
            report['browser']=json.loads((out/'browser.json').read_text(encoding='utf-8'))
            with psycopg.connect(dsn,row_factory=dict_row) as conn:
                widgets=conn.execute('SELECT * FROM dashboard_widgets WHERE user_id=%s ORDER BY created_at',(uid,)).fetchall()
                report['messages']=conn.execute("SELECT m.content,m.steps,m.usage FROM messages m JOIN conversations c ON c.id=m.conversation_id WHERE c.user_id=%s AND m.role='assistant' ORDER BY m.created_at",(uid,)).fetchall()
            check('Two reusable charts, including pinned preview',len(widgets),2)
            widget=next(w for w in widgets if w['title']=='주별 수수료 차감액')
            check('Monthly edit revision',widget['widget_data']['definition_revision'],2)
            check('Monthly grouped definition',widget['widget_data']['metric_definition']['version'],4)
            check('Monthly formula values',[Decimal(r['value']) for r in widget['widget_data']['data']],[Decimal('320100'),Decimal('281300')])
            check('Hourly schedule preserved',widget['refresh_interval_seconds'],3600)
            check('Edited widget identity preserved',str(widget['id']),report['browser']['savedLayout']['id'])
            check('Resized layout preserved',widget['layout'],report['browser']['savedLayout']['layout'])
            # Append a synthetic transaction in this isolated fixture DB and
            # execute the production refresh endpoint, without another LLM call.
            with psycopg.connect(dsn) as conn:
                # Use the application's established name function.
                sys.path.insert(0,str(ROOT/'api'))
                with patch.dict(os.environ,env):
                    from app.db import get_user_table_name
                conn.execute(sql.SQL('INSERT INTO {} (amount,fee,channel,occurred_at,event_kind) VALUES (10000,300,%s,%s,%s)').format(sql.Identifier(get_user_table_name(uid,table['id']))),('매장','2026-09-03T12:00:00+09:00','payment'))
            refreshed=request('POST',base+f"/metrics/{widget['id']}/refresh")
            check('Refresh sees new transaction',[Decimal(r['value']) for r in refreshed['widget_data']['data']],[Decimal('320100'),Decimal('291000')])
            check('Refresh preserves revision',refreshed['widget_data']['definition_revision'],2)
            runtime.wait_indexes(request,base)
            report['passed']=True
    finally:
        for process in reversed(processes): runtime.stop(process)
        if created:
            assert name.startswith('dataez_charts_eval_') and len(name)==len('dataez_charts_eval_')+32
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
