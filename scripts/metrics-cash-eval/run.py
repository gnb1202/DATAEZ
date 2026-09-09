"""K/L acceptance using a fresh loopback DB, real API, models, and browser."""
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
    name='dataez_kl_eval_'+uuid4().hex
    out=ROOT/'scripts/metrics-cash-eval/artifacts'/name; out.mkdir(parents=True)
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
            month=datetime.now(ZoneInfo('Asia/Seoul')).date().replace(day=1); previous=(month-timedelta(days=1)).replace(day=1)
            csv='amount,fee,payment_method,occurred_at,event_kind\n'+f'100000,3000,카드,{previous}T12:00:00+09:00,payment\n100000,3000,카드,{month}T12:00:00+09:00,payment\n200000,6000,계좌이체,{month}T12:00:00+09:00,payment\n-20000,-600,카드,{month}T12:00:00+09:00,refund\n'
            table=request('POST',base+'/tables/import',files={'file':('pg-synthetic.csv',csv.encode())},data={'table_name':'검증 결제원장'})
            runtime.wait_indexes(request,base)
            dump(out/'browser-input.json',{'email':email,'password':password,'project_id':pid,'table_id':table['id']})
            built=True; build=start([node,'node_modules/next/dist/bin/next','build'],ROOT/'web','build')
            if build.wait(timeout=240): raise RuntimeError('Web build failed')
            web=start([node,'node_modules/next/dist/bin/next','start','-p',str(web_port),'-H','127.0.0.1'],ROOT/'web','web')
            runtime.wait_http(env['LIVE_UI_URL'],web)
            print('Real browser/model checks: formula save, edit, restore, cash draft and confirmation',flush=True)
            browser=start([node,'metrics-cash.cjs'],ROOT/'scripts/ui-eval','browser')
            if browser.wait(timeout=900): raise RuntimeError('Browser acceptance failed')
            report['browser']=json.loads((out/'browser.json').read_text(encoding='utf-8'))
            with psycopg.connect(dsn,row_factory=dict_row) as conn:
                widgets=conn.execute('SELECT * FROM dashboard_widgets WHERE user_id=%s',(uid,)).fetchall()
                source=conn.execute("SELECT * FROM ledger_sources WHERE project_id=%s AND input_mode='cash'",(pid,)).fetchone()
                report['messages']=conn.execute("SELECT m.content,m.steps,m.usage FROM messages m JOIN conversations c ON c.id=m.conversation_id WHERE c.user_id=%s AND m.role='assistant' ORDER BY m.created_at",(uid,)).fetchall()
                cash_total=conn.execute(sql.SQL('SELECT count(*) n,sum(amount) value FROM {}').format(sql.Identifier(source['physical_table_name']))).fetchone()
            check('One formula widget after edits/restoration',len(widgets),1)
            widget=widgets[0]; check('Restored definition revision',widget['widget_data']['definition_revision'],3)
            check('Restored fee difference',Decimal(widget['widget_data']['value']),Decimal('368600'))
            check('Cash entries exactly once including explicit similar transaction',cash_total,{'n':3,'value':Decimal('110000')})
            check('Cash ledger source revision',source['data_revision'],3)
            metric=request('POST',base+'/metrics',json={'title':'현금 순결제','definition':{'table_id':str(source['table_id']),'column':'amount'}})
            refund=request('POST',base+'/cash-entries/drafts',json={'request_key':str(uuid4()),'amount':'5000','kind':'refund','memo':'검증 취소'})
            request('POST',base+f"/cash-entries/{refund['id']}/commit",json={'confirmation_token':refund['confirmation_token']})
            refreshed=request('POST',base+f"/metrics/{metric['id']}/refresh")
            check('Cash metric refresh after new refund',Decimal(refreshed['widget_data']['value']),Decimal('105000'))
            runtime.wait_indexes(request,base)
            # Real conversational ratio and period-change requests exercise the
            # same production route, while SQL tests independently cover math.
            conv=request('POST','/api/conversations',json={'project_id':pid})['conversation_id']
            for question,expected in [
                ('검증 결제원장의 이번 달 취소 금액 절댓값을 이번 달 승인 금액으로 나눈 금액 취소율을 재사용 가능한 지표로 미리보기만 해줘. 대시보드에 저장하지 마.',Decimal('6.6667')),
                ('검증 결제원장의 이번 달 순결제액을 지난달 순결제액과 비교한 증감률을 재사용 가능한 지표로 미리보기만 해줘. 대시보드에 저장하지 마.',Decimal('180'))]:
                response=request('POST',f'/api/conversations/{conv}/messages',data={'message':question})
                report.setdefault('extra_chat',[]).append(response)
                outputs=[s['tool_output'] for s in response.get('steps',[]) if s.get('tool_name')=='preview_metric' and s.get('tool_output',{}).get('value') is not None]
                # Endpoint may nest the agent result under message; use stored
                # steps as the production persistence oracle in that case.
                if not outputs:
                    with psycopg.connect(dsn,row_factory=dict_row) as conn:
                        message=conn.execute("SELECT steps FROM messages WHERE conversation_id=%s AND role='assistant' ORDER BY created_at DESC LIMIT 1",(conv,)).fetchone()
                    outputs=[s['tool_output'] for s in message['steps'] if s.get('tool_name')=='preview_metric' and s.get('tool_output',{}).get('value') is not None]
                check('Natural-language preview '+str(expected),Decimal(outputs[-1]['value']) if outputs else None,expected)
                print('PASS: natural-language preview '+str(expected),flush=True)
            report['passed']=True
    finally:
        for process in reversed(processes): runtime.stop(process)
        if created:
            assert name.startswith('dataez_kl_eval_') and len(name)==len('dataez_kl_eval_')+32
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
