"""Isolated HTTP/PG/LLM acceptance; never connects to the persistent demo DB."""
import argparse
import csv
from datetime import datetime,timezone
from decimal import Decimal
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import time
from uuid import uuid4

from dotenv import dotenv_values
import httpx
import psycopg
from psycopg import sql
from psycopg.rows import dict_row
from cases import CASES,HOLDOUT,manifest
from fixtures import ROOT,DATA,FILES,APPEND,AS_OF,VERSION,records,expected
from grading import grade,CRITICAL

spec=importlib.util.spec_from_file_location('runtime',ROOT/'scripts/ui-eval/live-run.py')
runtime=importlib.util.module_from_spec(spec);spec.loader.exec_module(runtime)
def dump(path,obj):path.write_text(json.dumps(obj,ensure_ascii=False,indent=2,default=str)+'\n',encoding='utf-8')
def hash_files(paths):return {p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(paths)}
def docker(*args):return subprocess.check_output(['docker',*args],text=True,encoding='utf-8',creationflags=runtime.HIDDEN).strip()

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live-llm',action='store_true')
    parser.add_argument('--suite',choices=['main','holdout'],default='main')
    parser.add_argument('--cases',help='Comma-separated IDs for regression only; state chain is included')
    parser.add_argument('--env-file',type=Path,default=ROOT/'.env')
    args=parser.parse_args()
    all_cases=CASES if args.suite=='main' else HOLDOUT
    selected=all_cases
    if args.cases:
        wanted=set(args.cases.split(','));known={c['id'] for c in all_cases}
        if wanted-known:raise ValueError('Unknown case IDs')
        if any(c.get('state') for c in all_cases if c['id'] in wanted):wanted|={c['id'] for c in all_cases if c.get('state')}
        selected=[c for c in all_cases if c['id'] in wanted]
    assert json.loads((DATA/'manifest.json').read_text(encoding='utf-8'))==manifest(),'Do not run an unfrozen/edited manifest'
    local=dotenv_values(args.env_file)
    env=os.environ.copy()
    for key in ['OPENAI_API_KEY','OPENAI_MODEL','OPENAI_ORCHESTRATOR_MODEL','OPENAI_EMBEDDING_MODEL']:
        if local.get(key) and not env.get(key):env[key]=local[key]
    if not env.get('OPENAI_API_KEY'):raise ValueError('Configured model key required, including for setup embeddings')
    run_id='unseen_'+args.suite+'_'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'_'+uuid4().hex[:8]
    out=ROOT/'.local-test/unseen-eval'/run_id;out.mkdir(parents=True)
    container='dataez-'+run_id.replace('_','-');dbname='eval_'+uuid4().hex
    dbport,apiport=runtime.free_port(),runtime.free_port()
    admin=f'postgresql://postgres@127.0.0.1:{dbport}/postgres'
    dsn=f'postgresql://postgres@127.0.0.1:{dbport}/{dbname}'
    env.update(DATABASE_URL=dsn,JWT_SECRET_KEY=secrets.token_hex(32),APP_ENV='development',RAG_ENABLED='true',
        INDEX_WORKER_ENABLED='true',STORAGE_BACKEND='local',LOCAL_STORAGE_PATH=str(out/'uploads'),
        METRIC_SCHEDULER_ENABLED='false',IMPORT_CLEANUP_ENABLED='false',DB_POOL_MIN_SIZE='1',DB_POOL_MAX_SIZE='5',
        UPLOAD_RATE_LIMIT_PER_MINUTE='300',QUERY_RATE_LIMIT_PER_MINUTE='300',PYTHONIOENCODING='utf-8')
    # Read effective defaults as the API does, without printing any credentials.
    model_settings=json.loads(subprocess.check_output([sys.executable,'-c',
        'import json; from app.config import settings; print(json.dumps({k:getattr(settings,k.lower()) for k in ("OPENAI_MODEL","OPENAI_ORCHESTRATOR_MODEL","OPENAI_EMBEDDING_MODEL")}))'],
        cwd=ROOT/'api',env=env,text=True,encoding='utf-8',creationflags=runtime.HIDDEN))
    env.update(model_settings)
    sources=list((ROOT/'api/app').rglob('*.py'))
    fixture_paths=[p for p in DATA.rglob('*') if p.is_file() and not p.name.endswith('.ndjson')]
    report=dict(run_id=run_id,suite='regression' if args.cases else args.suite,as_of=AS_OF,version=VERSION,
        checked_at=datetime.now(timezone.utc).isoformat(),source_commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
        source_sha256=hash_files(sources),fixture_sha256=hash_files(fixture_paths),benchmark_sha256=hash_files(list(Path(__file__).parent.glob('*.py'))),
        real_api=True,api_mocks=False,real_postgres=True,real_embeddings=True,real_llm=args.live_llm,browser_evaluated=False,grader_version=2,
        worker_model=env.get('OPENAI_MODEL'),router_model=env.get('OPENAI_ORCHESTRATOR_MODEL'),embedding_model=env.get('OPENAI_EMBEDDING_MODEL'),
        cost_note='Repository price-table estimate, not current billing. Setup indexing counters are separate from question usage.',
        fixture_checks=[],cases=[],semantic_review='pending',passed=False,automatic_question_retries=0)
    api=None;created=False;log=(out/'api.log').open('w',encoding='utf-8')
    def check(name,actual,wanted):
        ok=actual==wanted;report['fixture_checks'].append(dict(name=name,actual=actual,expected=wanted,passed=ok))
        if not ok:raise AssertionError(f'{name}: {actual!r} != {wanted!r}')
    try:
        docker('run','--detach','--rm','--name',container,'--label','dataez.unseen.run='+run_id,
               '-e','POSTGRES_HOST_AUTH_METHOD=trust','-p',f'127.0.0.1:{dbport}:5432','pgvector/pgvector:pg16')
        created=True
        deadline=time.monotonic()+60
        while True:
            try:
                with psycopg.connect(admin,autocommit=True,connect_timeout=2) as conn:
                    conn.execute(sql.SQL("CREATE DATABASE {} TEMPLATE template0 ENCODING 'UTF8'").format(sql.Identifier(dbname)))
                break
            except psycopg.OperationalError:
                if time.monotonic()>deadline:raise
                time.sleep(.5)
        with psycopg.connect(dsn) as conn:conn.execute((ROOT/'db/init.sql').read_text(encoding='utf-8'))
        api=subprocess.Popen([sys.executable,'-m','uvicorn','app.main:app','--host','127.0.0.1','--port',str(apiport)],cwd=ROOT/'api',env=env,stdout=log,stderr=subprocess.STDOUT,creationflags=runtime.HIDDEN)
        runtime.wait_http(f'http://127.0.0.1:{apiport}/health',api)
        print('Run: '+str(out),flush=True)
        with httpx.Client(base_url=f'http://127.0.0.1:{apiport}',timeout=240) as client:
            def request(method,path,**kw):
                response=client.request(method,path,**kw)
                if response.is_error:raise RuntimeError(f'{method} {path}: {response.status_code}: {response.text[:350]}')
                return response.json()
            owner=request('POST','/api/auth/signup',json=dict(name='새 파일 평가',email=run_id+'@example.test',password=secrets.token_urlsafe(24)+'Aa1!'))
            foreign=request('POST','/api/auth/signup',json=dict(name='별도 계정',email='foreign-'+run_id+'@example.test',password=secrets.token_urlsafe(24)+'Aa1!'))
            client.headers['Authorization']='Bearer '+owner['access_token']
            auth=lambda k:{'Authorization':'Bearer '+(foreign if k=='foreign' else owner)['access_token']}
            stores={k:request('POST','/api/projects',headers=auth(k),json={'name':name})['id'] for k,name in [('main','중앙 매장'),('other','강변 매장'),('foreign','외부 계정 매장')]}
            pid=stores['main'];ids={};setup_start=time.monotonic()
            file_keys=[k for k in FILES if k!='holdout' or args.suite=='holdout']
            for key in file_keys:
                f=FILES[key];content=(DATA/key/f['filename']).read_bytes();headers=auth(f['store']);store=stores[f['store']]
                uploaded=request('POST','/api/library/files',headers=headers,data={'project_id':store},files={'file':(f['filename'],content)})
                prepared=request('POST',f"/api/library/files/{uploaded['file_id']}/prepare",headers=headers,json={'project_id':store})
                tid=prepared['bindings'][0]['table_id']
                ids[key]={'file_id':uploaded['file_id'],'project_id':store,'binding_table_id':tid}
                for scope in ['original_file','linked_ledger']:
                    sel={'file_id':uploaded['file_id'],'table_id':tid,'scope':scope}
                    resolved=request('POST','/api/library/files/resolve',headers=headers,json={'project_id':store,'selections':[sel],'confirmed':True})['files'][0]
                    ids[key][scope]=resolved;ids[key][scope+'_selection']=sel
                preview=request('GET',f"/api/library/files/{uploaded['file_id']}/preview",headers=headers)
                check(key+' imported rows',preview['row_count'],len(f['rows']))
            # Append only to a connected ledger, never its original snapshot.
            stream=io.StringIO(newline='');writer=csv.writer(stream);writer.writerow(FILES['a']['columns']);writer.writerow(APPEND)
            request('POST',f"/api/projects/{pid}/tables/{ids['a']['binding_table_id']}/append",files={'file':('追加.csv',stream.getvalue().encode('utf-8'))})
            doc=request('POST','/api/library/files',data={'project_id':pid},files={'file':('업무메모.md',(DATA/'document/업무메모.md').read_bytes())})
            request('POST',f"/api/library/files/{doc['file_id']}/prepare",json={'project_id':pid})
            for key in stores:
                runtime.wait_indexes(lambda method,path:request(method,path,headers=auth(key)),f'/api/projects/{stores[key]}',timeout=180)
            docref=request('POST','/api/library/files/resolve',json={'project_id':pid,'selections':[{'file_id':doc['file_id'],'scope':'document'}],'confirmed':True})['files'][0]
            ids['document']={'file_id':doc['file_id'],'document':docref,'document_selection':{'file_id':doc['file_id'],'scope':'document'}}
            # All numerical fixture controls use the public SQL metric service,
            # compared with independent Decimal calculations over raw inputs.
            for key in file_keys:
                for scope in ['original_file','linked_ledger']:
                    f=FILES[key]
                    definition=dict(table_id=ids[key][scope]['table_id'],operation='sum',column=f['amount'],unit='KRW' if key!='usd' else 'number')
                    result=request('POST',f"/api/projects/{stores[f['store']]}/metrics/preview",headers=auth(f['store']),json={'definition':definition})
                    wanted=expected(dict(file=key,scope=scope))['__NULL__']
                    check(key+' '+scope+' exact SQL sum',Decimal(result['value']),Decimal(wanted))
            # Header aliases and complete signed-file validation; no source writes.
            mapping_content=(DATA/'a'/FILES['a']['filename']).read_bytes()
            inspected=request('POST',f'/api/projects/{pid}/import-mapping/inspect',files={'file':(FILES['a']['filename'],mapping_content)})
            check('Korean header amount mapping candidate',inspected['suggested_mapping']['amount_column'],'승인금액')
            check('Large textual identifier preserved',inspected['sample'][0]['values'][0],FILES['a']['rows'][0][0])
            mapping={'amount_column':'승인금액','occurred_at_column':'거래일시','event_id_column':'주문번호','payment_method_column':'결제수단','event_kind':'signed'}
            validated=request('POST',f'/api/projects/{pid}/import-mapping/validate',data={'mapping':json.dumps(mapping)},files={'file':(FILES['a']['filename'],mapping_content)})
            check('Signed mapping validates every row',validated['row_count'],12)
            check('Signed mapping exact total',Decimal(validated['amount']),Decimal('64002.10'))
            wrong={**mapping,'event_kind':'payment'}
            rejected=client.post(f'/api/projects/{pid}/import-mapping/validate',data={'mapping':json.dumps(wrong)},files={'file':(FILES['a']['filename'],mapping_content)})
            check('Payment-only mapping rejects negative cancellation rows',rejected.status_code,422)
            check('Foreign file download denied',client.get(f"/api/library/files/{ids['foreign']['file_id']}/download").status_code,404)
            check('Foreign selected file denied',client.post('/api/library/files/resolve',json={'project_id':pid,'confirmed':True,'selections':[ids['foreign']['original_file_selection']]}).status_code,404)
            protected=request('POST',f'/api/projects/{pid}/metrics',json={'title':'기존 지표 보존 확인','definition':{'table_id':ids['a']['binding_table_id'],'column':'승인금액','unit':'KRW'},'refresh_interval_seconds':0})
            report['fixture_ids']=ids;report['setup_seconds']=round(time.monotonic()-setup_start,3)
            metric_lines=client.get('/metrics').text.splitlines()
            report['setup_usage_metrics']=[line for line in metric_lines if line.startswith(('dataez_llm_calls_total','dataez_llm_tokens_total','dataez_llm_cost_usd_total'))]
            def widgets():
                with psycopg.connect(dsn,row_factory=dict_row) as conn:return conn.execute('SELECT id,project_id,title,widget_data,layout,refresh_interval_seconds FROM dashboard_widgets ORDER BY id').fetchall()
            def snapshot():
                with psycopg.connect(dsn,row_factory=dict_row) as conn:
                    physical=conn.execute("SELECT tablename FROM pg_tables WHERE schemaname='public' AND tablename ~ '^ut_[0-9a-f]+_[0-9a-f]+$' ORDER BY tablename").fetchall()
                    state=[]
                    for table in [r['tablename'] for r in physical]+['projects','table_meta','files','ledger_sources','import_batches','import_rows','cash_entries']:
                        state.append(conn.execute(sql.SQL('SELECT to_jsonb(t) AS row FROM {} t ORDER BY to_jsonb(t)::text').format(sql.Identifier(table))).fetchall())
                return hashlib.sha256(json.dumps(state,default=str,sort_keys=True).encode()).hexdigest()
            baseline_files={key:hashlib.sha256(client.get(f"/api/library/files/{ids[key]['file_id']}/download",headers=auth(FILES[key]['store'])).content).hexdigest() for key in file_keys}
            report['original_download_hashes']=baseline_files
            state_conversation=None
            if args.live_llm:
                for case in selected:
                    if case.get('state') and state_conversation:cid=state_conversation
                    else:cid=request('POST','/api/conversations',json={'project_id':pid})['conversation_id']
                    if case.get('state'):state_conversation=cid
                    selections=[ids[key][('document' if key=='document' else case.get('scope','original_file'))+'_selection'] for key in case.get('selections',[case['file']])]
                    question=case['question'].format(foreign_store=stores['foreign'],foreign_file=ids['foreign']['file_id'])
                    before=widgets();raw_before=snapshot();start=time.monotonic()
                    record=dict(id=case['id'],category=case['category'],question=question,attempt=1,semantic_review='pending',passed=False)
                    evidence={};details={};streaming=case['id'] in {'N04','B29','H03'}
                    record['transport']='streaming HTTP' if streaming else 'synchronous HTTP'
                    print('Case '+case['id']+' starting',flush=True)
                    try:
                        payload={'message':question,'library_selections':json.dumps(selections),'library_scope_confirmed':'true'}
                        endpoint=f'/api/conversations/{cid}/messages'
                        if streaming:
                            with client.stream('POST',endpoint+'/stream',data=payload) as response:
                                response.raise_for_status()
                                for line in response.iter_lines():
                                    if line.startswith('data:'):
                                        frame=json.loads(line[5:])
                                        if frame['type']=='error':raise RuntimeError(str(frame['data']))
                                        if frame['type']=='done':evidence=frame['data']
                            if not evidence:raise RuntimeError('Stream ended before done')
                        else:evidence=request('POST',endpoint,data=payload)
                        # Persisted evidence provides the identical step/usage shape
                        # for both public transports, including the finished SSE path.
                        history=request('GET',endpoint)['messages']
                        record['assistant_persisted']=bool(history and history[-1]['role']=='assistant')
                        after=widgets()
                        checks,details=grade(case,evidence,before,after,raw_before==snapshot(),ids)
                        checks['assistant_persisted']=record['assistant_persisted']
                        record.update(checks=checks,automatic_passed=all(checks.values()),answer=evidence.get('content',''),usage=evidence.get('usage',{}))
                    except Exception as exc:
                        after=widgets();record.update(error=type(exc).__name__+': '+str(exc),automatic_passed=False)
                        record['checks']={'raw_state_unchanged':raw_before==snapshot(),'widgets_unchanged_on_error':before==after}
                    record['seconds']=round(time.monotonic()-start,3)
                    record['critical_failures']=[key for key in CRITICAL if record.get('checks',{}).get(key) is False]
                    dump(out/f"case-{case['id']}.json",dict(case=record,evidence=evidence,details=details,widgets_before=before,widgets_after=after))
                    report['cases'].append(record);dump(out/'report.json',report)
                    print(f"  {'PASS' if record['automatic_passed'] else 'FAIL'} {record['seconds']}s {[k for k,v in record.get('checks',{}).items() if not v]} {record.get('error','')}",flush=True)
            check('Original bytes unchanged by all questions',{key:hashlib.sha256(client.get(f"/api/library/files/{ids[key]['file_id']}/download",headers=auth(FILES[key]['store'])).content).hexdigest() for key in file_keys},baseline_files)
            report['source_unchanged_during_run']=hash_files(sources)==report['source_sha256']
            report['automatic_passed']=sum(c.get('automatic_passed',False) for c in report['cases'])
            report['usage']={key:sum(c.get('usage',{}).get(key,0) or 0 for c in report['cases']) for key in ['calls','prompt_tokens','completion_tokens','total_tokens','cost_usd']}
            report['critical_failures']=[{'id':c['id'],'failures':c['critical_failures']} for c in report['cases'] if c.get('critical_failures')]
            report['automatic_acceptance']=report['automatic_passed']>=len(selected)-(1 if args.suite=='holdout' else 3) and not report['critical_failures'] and report['source_unchanged_during_run'] if args.live_llm else None
    except Exception as exc:
        report['harness_error']=type(exc).__name__+': '+str(exc)
        raise
    finally:
        runtime.stop(api)
        if created:
            label=docker('inspect','--format','{{ index .Config.Labels "dataez.unseen.run" }}',container)
            if label!=run_id:raise RuntimeError('Refusing to stop an unowned test container')
            docker('stop',container);report['temporary_database_removed']=True
        log.close();report['finished_at']=datetime.now(timezone.utc).isoformat();dump(out/'report.json',report)
        print('Report: '+str(out/'report.json'),flush=True)
    return 0 if not report.get('harness_error') else 1

if __name__=='__main__':raise SystemExit(main())
