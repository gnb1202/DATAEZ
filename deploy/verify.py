"""Exercise the public Compose candidate on loopback HTTPS, then remove only it."""
import argparse
from datetime import datetime,timezone
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import secrets
import socket
import ssl
import subprocess
import time
from uuid import uuid4

import httpx
from dotenv import dotenv_values
from check import ROOT,check,compose


def free_port():
    with socket.socket() as s:
        s.bind(('127.0.0.1',0));return s.getsockname()[1]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--env-file',type=Path,required=True)
    parser.add_argument('--live-llm',action='store_true')
    args=parser.parse_args()
    key=os.environ.get('OPENAI_API_KEY') or dotenv_values(args.env_file).get('OPENAI_API_KEY')
    if not key:raise ValueError('Provide a server key for actual sample indexing')
    run_id='public-check-'+datetime.now(timezone.utc).strftime('%Y%m%dt%H%M%Sz')+'-'+uuid4().hex[:8]
    project='dataez-'+run_id
    out=ROOT/'.local-test/public-deploy'/run_id;out.mkdir(parents=True)
    http_port,https_port=free_port(),free_port();origin=f'https://localhost:{https_port}'
    env_file=out/'settings.env'
    settings={'PUBLIC_HOST':'localhost','PUBLIC_ORIGIN':origin,'PUBLIC_BIND':'127.0.0.1','PUBLIC_HTTP_PORT':str(http_port),
              'PUBLIC_HTTPS_PORT':str(https_port),'POSTGRES_USER':'dataez','POSTGRES_DB':'dataez',
              'POSTGRES_PASSWORD':secrets.token_hex(32),'JWT_SECRET_KEY':secrets.token_hex(32),
              'OPENAI_API_KEY':key,'AUTH_RATE_LIMIT_PER_MINUTE':'2'}
    configured=dotenv_values(args.env_file)
    for name in ('OPENAI_MODEL','OPENAI_ORCHESTRATOR_MODEL','OPENAI_EMBEDDING_MODEL'):
        if os.environ.get(name) or configured.get(name):settings[name]=os.environ.get(name) or configured[name]
    env_file.write_text('\n'.join(k+'='+v for k,v in settings.items())+'\n',encoding='utf-8')
    cmd=compose(env_file,project)
    report={'run_id':run_id,'passed':False,'checks':[],'public_cloud_deployed':False,'tls':'local Caddy CA; explicitly trusted only by this test client',
            'browser_evaluated':False,'live_llm_questions':0,'api_mocks':False,'source_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()}
    files=['docker-compose.yml','deploy/compose.public.yaml','deploy/Caddyfile','deploy/check.py','deploy/verify.py','web/Dockerfile',
           'web/package.json','web/package-lock.json','web/next.config.js','web/app/layout.tsx','web/components/brand/dataez-logo.tsx','api/app/library_agent.py']
    report['source_sha256']={name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in files}
    locked=json.loads((ROOT/'web/package-lock.json').read_text(encoding='utf-8'))['packages']
    report['web_packages']={name:locked['node_modules/'+name]['version'] for name in ('next','react','react-dom')}
    def record(name,ok):
        report['checks'].append({'name':name,'passed':bool(ok)})
        if not ok:raise AssertionError(name)
        print('PASS '+name,flush=True)
    log=(out/'compose.log').open('w',encoding='utf-8')
    def run(*args):
        result=subprocess.run(cmd+list(args),cwd=ROOT,stdout=log,stderr=subprocess.STDOUT)
        if result.returncode:raise RuntimeError('Compose failed; see private compose.log')
    created=False
    try:
        report['configuration']=check(env_file,local=True,project=project)
        rendered=json.loads(subprocess.check_output(cmd+['config','--format','json'],text=True,encoding='utf-8'))
        report['models']={k:rendered['services']['api']['environment'][k] for k in ('OPENAI_MODEL','OPENAI_ORCHESTRATOR_MODEL','OPENAI_EMBEDDING_MODEL')}
        print('Evidence: '+str(out),flush=True)
        print('Building and starting isolated production services',flush=True)
        created=True
        run('up','--build','-d','--wait','--wait-timeout','240')
        print('Services ready; obtaining the local test CA',flush=True)
        ca=out/'local-ca.crt';deadline=time.monotonic()+30
        while True:
            copied=subprocess.run(cmd+['cp','proxy:/data/caddy/pki/authorities/local/root.crt',str(ca)],stdout=log,stderr=subprocess.STDOUT)
            if copied.returncode==0:break
            if time.monotonic()>deadline:raise RuntimeError('Local TLS CA was not generated')
            time.sleep(.5)
        context=ssl.create_default_context(cafile=str(ca))
        with httpx.Client(base_url=origin,verify=context,timeout=180,trust_env=False) as client:
            def request(method,path,**kwargs):
                response=client.request(method,path,**kwargs);response.raise_for_status();return response.json()
            response=client.get('/');record('HTTPS login page',response.status_code==200 and 'DATA' in response.text)
            record('Public share image',client.get('/og-dataez.png').headers.get('content-type','').startswith('image/png'))
            record('Share metadata uses HTTPS origin',origin+'/og-dataez.png' in response.text)
            record('API readiness through HTTPS proxy',client.get('/ready').status_code==200)
            record('Telemetry hidden from public proxy',client.get('/metrics').status_code==404)
            preflight=client.options('/api/auth/login',headers={'Origin':origin,'Access-Control-Request-Method':'POST'})
            record('CORS matches public origin',preflight.headers.get('access-control-allow-origin')==origin)
            bad=client.options('/api/auth/login',headers={'Origin':'https://unrelated.example.test','Access-Control-Request-Method':'POST'})
            record('Unrelated CORS origin rejected','access-control-allow-origin' not in bad.headers)
            redirect=httpx.get(f'http://localhost:{http_port}/',follow_redirects=False,trust_env=False)
            record('HTTP redirects to HTTPS',redirect.status_code==308 and redirect.headers['location'].startswith('https://localhost'))
            email=run_id+'@example.test';password=secrets.token_urlsafe(24)+'Aa1!'
            owner=request('POST','/api/auth/signup',json={'email':email,'password':password,'name':'배포 검사'})
            foreign=request('POST','/api/auth/signup',json={'email':'other-'+email,'password':secrets.token_urlsafe(24)+'Aa1!','name':'다른 계정'})
            client.headers['Authorization']='Bearer '+owner['access_token']
            sample=request('POST','/api/library/files/sample-workspace');pid=sample['project']['id'];fid=sample['file']['file_id']
            data=client.get(f'/api/library/files/{fid}/download').content;data_hash=hashlib.sha256(data).hexdigest()
            record('Sample source bytes downloadable',b'126500' in data and b'amount' in data)
            foreign_response=client.get(f'/api/library/files/{fid}/download',headers={'Authorization':'Bearer '+foreign['access_token']})
            record('Cross-account file access denied',foreign_response.status_code==404)
            dashboard=request('POST','/api/library/files/sample-workspace/dashboard',json={'project_id':pid})
            widgets=dashboard['widgets'];record('Three saved sample metrics',len(widgets)==3)
            kpi=next(w for w in widgets if not w['widget_data']['metric_definition'].get('group_by'))
            record('Exact sample KPI',Decimal(str(kpi['widget_data']['value']))==Decimal('690200'))
            if args.live_llm:
                print('Checking one real streaming model turn through HTTPS',flush=True)
                cid=request('POST','/api/conversations',json={'project_id':pid})['conversation_id']
                selection={'file_id':fid,'table_id':sample['file']['bindings'][0]['table_id'],'scope':'original_file'}
                started=time.monotonic();frames=[];done=None;first=None
                with client.stream('POST',f'/api/conversations/{cid}/messages/stream',data={
                    'message':'선택한 샘플 원본의 amount 전체 합계를 원화로 알려줘. 취소 부호를 유지하고 재계산 가능한 지표로 미리보기만 해줘. 저장하지 마.',
                    'library_selections':json.dumps([selection]),'library_scope_confirmed':'true'}) as response:
                    response.raise_for_status();record('SSE content type',response.headers.get('content-type','').startswith('text/event-stream'))
                    for line in response.iter_lines():
                        if line.startswith('data:'):
                            frame=json.loads(line[5:]);frames.append(frame['type'])
                            if first is None:first=time.monotonic()-started
                            if frame['type']=='error':raise RuntimeError('Model stream returned an error')
                            if frame['type']=='done':done=frame['data']
                elapsed=time.monotonic()-started
                record('SSE frames arrive before completion',done is not None and first is not None and first<elapsed and len(frames)>2)
                values=[s['tool_output'].get('value') for s in done.get('steps',[]) if s.get('tool_name')=='preview_metric' and s.get('type')=='tool_call']
                record('Streaming metric equals independent sample sum',bool(values) and Decimal(str(values[-1]))==Decimal('690200'))
                history=request('GET',f'/api/conversations/{cid}/messages')['messages']
                record('Streaming reply persisted',history[-1]['role']=='assistant')
                report.update(live_llm_questions=1,stream={'first_frame_seconds':round(first,3),'total_seconds':round(elapsed,3),'frame_types':frames},usage=done.get('usage'),answer=done.get('content'))
            statuses=[client.post('/api/auth/login',json={'email':'missing@example.test','password':'wrong'},headers={'X-Forwarded-For':f'198.51.100.{i}'}).status_code for i in range(3)]
            record('Spoofed forwarded IP cannot bypass login limit',statuses==[401,401,429])
            print('Recreating containers while preserving volumes',flush=True)
            run('down');run('up','-d','--wait','--wait-timeout','240')
            owner=request('POST','/api/auth/login',json={'email':email,'password':password})
            client.headers['Authorization']='Bearer '+owner['access_token']
            record('Account survives container recreation',bool(owner['access_token']))
            record('Original upload survives container recreation',hashlib.sha256(client.get(f'/api/library/files/{fid}/download').content).hexdigest()==data_hash)
            restored=request('POST','/api/library/files/sample-workspace/dashboard',json={'project_id':pid})['widgets']
            record('Saved widgets retained without duplicates',sorted(w['id'] for w in restored)==sorted(w['id'] for w in widgets))
            record('KPI retained after recreation',Decimal(str(next(w for w in restored if w['id']==kpi['id'])['widget_data']['value']))==Decimal('690200'))
        record('Verified source files unchanged during run',all(hashlib.sha256((ROOT/name).read_bytes()).hexdigest()==value for name,value in report['source_sha256'].items()))
        report['passed']=True
    finally:
        if created:
            # Generated project name plus exact Compose labels prevent accidental
            # cleanup of a developer's other project or the persistent demo.
            containers=subprocess.check_output(cmd+['ps','-a','-q'],text=True).split()
            for container in containers:
                labels=json.loads(subprocess.check_output(['docker','inspect',container],text=True))[0]['Config']['Labels']
                if labels.get('com.docker.compose.project')!=project:raise RuntimeError('Refusing foreign cleanup')
            if not project.startswith('dataez-public-check-'):raise RuntimeError('Invalid test project')
            run('down','--volumes','--remove-orphans');report['temporary_resources_removed']=True
        log.close();report['finished_at']=datetime.now(timezone.utc).isoformat()
        (out/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        print('Report: '+str(out/'report.json'),flush=True)


if __name__=='__main__':main()
