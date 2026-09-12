"""Prepare a persistent synthetic portfolio account through the public API only.

prepare: reuse/create the example dashboard and a clean recording sample.
check: verify saved state without changing business data.
new-take: create a fresh sample while retaining every earlier take.
browser: verify real public login/store switching and capture baseline screens.
"""
import argparse
import csv
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import io
import json
from pathlib import Path
import secrets
import subprocess
import sys
from uuid import uuid4

import httpx

ROOT = Path(__file__).resolve().parents[2]
LOCAL = ROOT / '.local-test/portfolio-demo'
STATE = LOCAL / 'account.json'
OUT = ROOT / 'docs/portfolio-demo'
API = 'https://dataez-api.vercel.app'
SITE = 'https://dataez.vercel.app'
SAMPLE = '/api/library/files/sample-workspace'


def save(state):
    LOCAL.mkdir(parents=True, exist_ok=True)
    temporary = STATE.with_suffix('.tmp')
    temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    temporary.replace(STATE)


def request(client, method, route, **kwargs):
    response = client.request(method, route, **kwargs)
    if not response.is_success:
        raise RuntimeError(f'{method} {route}: HTTP {response.status_code}; no automatic mutation retry')
    return response.json()


def login(client, state, create=False):
    body = {k: state[k] for k in ('email', 'password')}
    if create and not state.get('user_id'):
        # Credentials were saved before signup: a lost response is recovered by login.
        response = client.post('/api/auth/login', json=body)
        if response.status_code == 401:
            data = request(client, 'POST', '/api/auth/signup', json={**body, 'name': '포트폴리오 데모'})
        elif response.is_success:
            data = response.json()
        else:
            raise RuntimeError(f'Account recovery HTTP {response.status_code}')
    else:
        data = request(client, 'POST', '/api/auth/login', json=body)
    client.headers['Authorization'] = 'Bearer '+data['access_token']
    me = request(client, 'GET', '/api/auth/me')
    assert me['email'] == state['email'], 'Unexpected account'
    assert not state.get('user_id') or state['user_id'] == me['user_id'], 'Account identity changed'
    state['user_id'] = me['user_id']
    save(state)


def compact(sample):
    return {'project_id': sample['project']['id'], 'name': sample['project']['name'],
            'file_id': sample['file']['file_id'], 'table_id': sample['file']['bindings'][0]['table_id']}


def new_take(client, state):
    if not state.get('pending_restart'):
        current = request(client, 'GET', SAMPLE)['project']['id']
        known = {state['showcase']['project_id'], *[t['project_id'] for t in state.get('takes', [])]}
        assert current in known, 'Current sample is not a recorded portfolio take'
        state['pending_restart'] = {'expected_project_id': current, 'request_id': str(uuid4())}
        save(state)
    sample = request(client, 'POST', SAMPLE+'/restart', json=state['pending_restart'])
    take = compact(sample)
    # Replaying the same request must yield the same new project without losing the previous one.
    replay = request(client, 'POST', SAMPLE+'/restart', json=state['pending_restart'])
    assert compact(replay) == take, 'Restart replay changed sample identity'
    state.setdefault('takes', []).append(take)
    state['recording'] = take
    state.pop('pending_restart')
    save(state)


def summarize(rows):
    daily, method = {}, {}
    for row in rows:
        amount = Decimal(str(row['amount']))
        day = str(row['paid_at'])[:10]
        daily[day] = daily.get(day, Decimal(0))+amount
        method[row['method']] = method.get(row['method'], Decimal(0))+amount
    return {'rows': len(rows), 'total': str(sum(daily.values(), Decimal(0))),
            'daily': {k:str(v) for k,v in sorted(daily.items())},
            'method': {k:str(v) for k,v in sorted(method.items())}}


def verify(client, state):
    expected = json.loads((ROOT/'samples/demo/expected.json').read_text(encoding='utf-8'))
    report = {'verified_at':datetime.now(timezone.utc).isoformat(), 'site':SITE, 'api':API,
              'source_commit': subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
              'synthetic':True, 'chat_llm_calls':0,
              'indexing_note':'Sample preparation may enqueue embeddings; no chat analysis was requested.',
              'checks':[], 'workspaces':{}}
    for endpoint in ('/health','/ready'):
        assert request(client,'GET',endpoint)['status']=='ok'
    report['checks'].append('Public API health and database ready')
    projects = request(client,'GET','/api/projects')['projects']
    report['account_project_count']=len(projects)
    assert all(t['project_id'] in {p['id'] for p in projects} for t in [state['showcase'],state['recording']])
    assert request(client,'GET',SAMPLE)['project']['id']==state['recording']['project_id']
    for role in ('showcase','recording'):
        item = state[role]
        response = client.get('/api/library/files/'+item['file_id']+'/download')
        assert response.status_code==200, 'Original download failed'
        source = response.content
        original = summarize(list(csv.DictReader(io.StringIO(source.decode('utf-8-sig')))))
        assert original['rows']==expected['original_rows']
        assert original['total']==expected['original_total']
        assert original['daily']==expected['daily'] and original['method']==expected['method']
        ledger = request(client,'GET',f"/api/projects/{item['project_id']}/tables/{item['table_id']}/data")
        assert ledger['total_count']==8
        assert summarize(ledger['rows'])==original, 'Recording baseline has already changed; create a new take'
        widgets = request(client,'GET','/api/dashboard/widgets',params={'project_id':item['project_id']})['widgets']
        assert len(widgets)==(3 if role=='showcase' else 0), 'Unexpected dashboard state'
        if role=='showcase':
            for widget in widgets:
                assert widget['refresh_interval_seconds']==0
                chart=widget['widget_data']
                values=([Decimal(str(chart['value']))] if widget['widget_type']=='kpi'
                        else [Decimal(str(row[chart['y_key']])) for row in chart['data']])
                assert sum(values)==Decimal(expected['original_total'])
                if widget['widget_type']!='kpi':
                    group=chart['metric_definition']['group_by']
                    actual={str(row[chart['x_key']])[:10] if group=='paid_at' else str(row[chart['x_key']]):
                            Decimal(str(row[chart['y_key']])) for row in chart['data']}
                    assert actual=={k:Decimal(v) for k,v in expected['daily' if group=='paid_at' else 'method'].items()}
                assert widget['title'].startswith('샘플 예시'), 'Example not labelled'
        report['workspaces'][role]={**item,'original':original,'ledger_rows':ledger['total_count'],
            'widget_count':len(widgets),'file_sha256':hashlib.sha256(source).hexdigest(),
            'widget_titles':[w['title'] for w in widgets]}
        index=request(client,'GET',f"/api/projects/{item['project_id']}/search-index")
        report['workspaces'][role]['search_index_statuses']=[job['status'] for job in index['jobs']]
        report['checks'].append(role+': original and ledger match independent expected values; widget baseline correct')
        if role=='recording':
            (LOCAL/'recording-original.csv').write_bytes(source)
    extra=list(csv.DictReader((ROOT/'samples/demo/additional-transaction.csv').read_text(encoding='utf-8-sig').splitlines()))
    assert Decimal(expected['original_total'])+sum(Decimal(r['amount']) for r in extra)==Decimal(expected['after_one_additional_transaction']['ledger_total'])
    report['checks'].append('Additional transaction fixture independently totals 720200; NOT appended to recording baseline')
    report['restart']={'strategy':'create a new sample, retain previous workspaces','recorded_takes':len(state['takes']),
                       'same_request_replay_verified':True}
    OUT.mkdir(parents=True,exist_ok=True)
    serialized = json.dumps(report,ensure_ascii=False,indent=2)+'\n'
    (LOCAL/'baseline-latest.json').write_text(serialized,encoding='utf-8')
    # Later takes must not rewrite the evidence for the original Phase 0 run.
    if not (OUT/'phase-0-baseline.json').exists():
        (OUT/'phase-0-baseline.json').write_text(serialized,encoding='utf-8')
    print(json.dumps({'checks':report['checks'],'workspace_count':len(projects),'recording_rows':8,'recording_widgets':0},ensure_ascii=False))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=['prepare','check','new-take','browser'])
    args=parser.parse_args()
    if STATE.exists():
        state=json.loads(STATE.read_text(encoding='utf-8'))
    else:
        assert args.command=='prepare','Run prepare first'
        state={'api':API,'site':SITE,'email':'portfolio-demo-'+uuid4().hex+'@example.invalid',
               'password':'Aa1!'+secrets.token_urlsafe(28)}
        save(state)
    assert state['api']==API and state['site']==SITE
    assert state['email'].startswith('portfolio-demo-') and state['email'].endswith('@example.invalid')
    with httpx.Client(base_url=API,timeout=90,follow_redirects=False) as client:
        login(client,state,create=args.command=='prepare')
        if args.command=='prepare':
            if not state.get('showcase'):
                state['showcase']=compact(request(client,'POST',SAMPLE));save(state)
            if not state.get('showcase_ready'):
                request(client,'POST',SAMPLE+'/dashboard',json={'project_id':state['showcase']['project_id']})
                state['showcase_ready']=True;save(state)
            if not state.get('recording'):new_take(client,state)
        if args.command=='new-take':new_take(client,state)
        verify(client,state)
    if args.command=='browser':
        run=subprocess.run(['node',str(ROOT/'scripts/portfolio-demo/baseline.cjs')],
            input=json.dumps(state),capture_output=True,text=True,encoding='utf-8',cwd=ROOT,timeout=150)
        if run.returncode:raise RuntimeError('Browser baseline failed; inspect sanitized report, credentials were not logged')
        print(run.stdout)


if __name__=='__main__':
    try:main()
    except Exception as exc:
        # Exception bodies may contain request URLs; never dump tokens or credentials.
        import traceback
        location=traceback.extract_tb(exc.__traceback__)[-1]
        print(f'Portfolio preparation stopped at {Path(location.filename).name}:{location.lineno}: '+(str(exc) if isinstance(exc,(AssertionError,RuntimeError,KeyError)) else type(exc).__name__))
        raise SystemExit(1)
