"""First-use acceptance using a fresh loopback DB, real API, models, and browser."""
from datetime import datetime, timedelta
import importlib.util
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import sys
from uuid import uuid4
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
    name='dataez_onboarding_eval_'+uuid4().hex
    out=ROOT/'scripts/onboarding-eval/artifacts'/name; out.mkdir(parents=True)
    ordinary=os.environ.copy(); env=ordinary.copy(); local=dotenv_values(ROOT/'.env')
    env['OPENAI_API_KEY']=env.get('OPENAI_API_KEY') or local.get('OPENAI_API_KEY','')
    if not env['OPENAI_API_KEY']: raise ValueError('Real model API key required')
    api_port,web_port=runtime.free_port(),runtime.free_port()
    dsn=make_conninfo(admin,dbname=name)
    env.update(DATABASE_URL=dsn,JWT_SECRET_KEY=secrets.token_hex(32),APP_ENV='development',RAG_ENABLED='true',
        INDEX_WORKER_ENABLED='true',STORAGE_BACKEND='local',LOCAL_STORAGE_PATH=str(out/'uploads'),
        METRIC_SCHEDULER_ENABLED='false',IMPORT_CLEANUP_ENABLED='false',
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
            owner=request('POST','/api/auth/signup',json={'email':email,'password':password,'name':'첫 대시보드 검증'})
            uid=owner['user_id']; client.headers['Authorization']='Bearer '+owner['access_token']
            month=datetime.now(ZoneInfo('Asia/Seoul')).date().replace(day=1)
            csv='이벤트ID,결제금액,취소금액,결제일시,통화,결제수단,판매채널,PG수수료\n'
            csv+=f'0001,100000,0,{month}T12:00:00+09:00,KRW,카드,매장,3000\n'
            csv+=f'0002,-20000,20000,{month+timedelta(days=1)}T12:00:00+09:00,KRW,카드,매장,-600\n'
            csv+=f'0003,50000,0,{month+timedelta(days=2)}T12:00:00+09:00,KRW,현금,매장,0\n'
            csv+=f'0003,50000,0,{month+timedelta(days=2)}T12:00:00+09:00,KRW,현금,매장,0\n'
            fixture=out/'first-payments.csv';fixture.write_text(csv,encoding='utf-8-sig')
            dump(out/'browser-input.json',{'email':email,'password':password,'file':str(fixture)})
            built=True; build=start([node,'node_modules/next/dist/bin/next','build'],ROOT/'web','build')
            if build.wait(timeout=240): raise RuntimeError('Web build failed')
            web=start([node,'node_modules/next/dist/bin/next','start','-p',str(web_port),'-H','127.0.0.1'],ROOT/'web','web')
            runtime.wait_http(env['LIVE_UI_URL'],web)
            print('Real first-use checks: empty account, mapping, review, resume, first metric and chat',flush=True)
            browser=start([node,'onboarding.cjs'],ROOT/'scripts/ui-eval','browser')
            if browser.wait(timeout=900): raise RuntimeError('Browser acceptance failed')
            report['browser']=json.loads((out/'browser.json').read_text(encoding='utf-8'))
            with psycopg.connect(dsn,row_factory=dict_row) as conn:
                widgets=conn.execute('SELECT * FROM dashboard_widgets WHERE user_id=%s ORDER BY created_at',(uid,)).fetchall()
                report['messages']=conn.execute("SELECT m.content,m.steps,m.usage FROM messages m JOIN conversations c ON c.id=m.conversation_id WHERE c.user_id=%s AND m.role='assistant' ORDER BY m.created_at",(uid,)).fetchall()
            pid=report['browser']['project_id'];base=f'/api/projects/{pid}'
            check('Exactly one reusable first metric',len(widgets),1)
            widget=widgets[0]
            check('First metric store',str(widget['project_id']),pid)
            check('Hourly schedule',widget['refresh_interval_seconds'],3600)
            check('Daily period definition',widget['widget_data']['metric_definition']['date_grain'],'day')
            check('Three deduplicated days',[r['value'] for r in widget['widget_data']['data']],['100000','-20000','50000'])
            sources=request('GET',base+'/ledger-sources')['sources']
            check('One source after reload and retries',len(sources),1)
            check('Three committed events',sources[0]['row_count'],3)
            history=request('GET',base+'/imports',params={'source_id':sources[0]['id']})['batches']
            check('One durable upload',len(history),1)
            check('Duplicate excluded',history[0]['result']['duplicates_skipped'],1)
            check('Exact committed total',history[0]['result']['amount'],'130000')
            check('Natural preview does not create a second metric',len(widgets),1)
            check('Other store has no ledgers',request('GET',f"/api/projects/{report['browser']['other_project_id']}/ledger-sources")['sources'],[])
            runtime.wait_indexes(request,base)
            report['passed']=True
    finally:
        for process in reversed(processes): runtime.stop(process)
        if created:
            assert name.startswith('dataez_onboarding_eval_') and len(name)==len('dataez_onboarding_eval_')+32
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
