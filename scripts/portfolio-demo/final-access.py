"""Read-only ownership probes after creating one isolated synthetic account B."""
import json
from pathlib import Path
import secrets
from uuid import uuid4
import httpx

ROOT = Path(__file__).resolve().parents[2]
local = ROOT / '.local-test/portfolio-demo/final-qa'
state = json.loads((local/'account.json').read_text(encoding='utf-8'))
take = state['recording']
bp = local/'account-b.json'
if bp.exists():
    other = json.loads(bp.read_text(encoding='utf-8'))
else:
    other = {'email':'portfolio-qa-b-'+uuid4().hex+'@example.invalid', 'password':secrets.token_urlsafe(24)+'!aA7'}
    bp.write_text(json.dumps(other),encoding='utf-8')
checks=[]
with httpx.Client(base_url=state['api'],timeout=60) as client:
    if not other.get('token'):
        res=client.post('/api/auth/login',json=other)
        if res.status_code==401: res=client.post('/api/auth/signup',json={**other,'name':'최종 QA 접근 격리'})
        assert res.is_success, f'Account B setup: {res.status_code}'
        other['token']=res.json()['access_token'];bp.write_text(json.dumps(other),encoding='utf-8')
    routes=[('GET',f"/api/library/files/{take['file_id']}"),
            ('GET',f"/api/library/files/{take['file_id']}/preview"),
            ('GET',f"/api/library/files/{take['file_id']}/download"),
            ('POST',f"/api/library/files/{take['file_id']}/download-url"),
            ('GET',f"/api/projects/{take['project_id']}/tables/{take['table_id']}/data"),
            ('GET',f"/api/projects/{take['project_id']}/metrics")]
    for method,route in routes:
        owner=client.request(method,route,headers={'Authorization':'Bearer '+state['token']})
        assert owner.is_success, f'Owner control: {owner.status_code}'
        for label,headers in [('anonymous',{}),('foreign_account',{'Authorization':'Bearer '+other['token']})]:
            res=client.request(method,route,headers=headers)
            assert res.status_code in (401,403,404), f'{label}: HTTP {res.status_code}'
            body=res.text
            assert all(value not in body for value in [state['email'],state['password'],state['token'],take['filename'],'690200'])
            assert 'https://' not in body and 'storage_key' not in body
            checks.append({'actor':label,'method':method,'resource':route.replace(take['file_id'],'<file>').replace(take['project_id'],'<store>').replace(take['table_id'],'<table>'),'status':res.status_code,'data_or_url_exposed':False})
    for route,expected in [('/health',200),('/ready',200),('/api/internal/maintenance/status',401)]:
        res=client.get(route);assert res.status_code==expected
        checks.append({'resource':route,'status':res.status_code})
    widgets=client.get('/api/dashboard/widgets',params={'project_id':take['project_id']},headers={'Authorization':'Bearer '+state['token']}).json()['widgets']
    rehearsal=json.loads((local/'analysis/rehearsal.json').read_text(encoding='utf-8'))
    layouts=[{'id':w['id'],'layout':w['layout']} for w in widgets]
    assert sorted(layouts,key=lambda w:w['id'])==sorted(rehearsal['layouts'],key=lambda w:w['id'])
    assert len(widgets)==2
    assert all(w['widget_data']['metric_definition']['time_range']=='all' and w['widget_data']['unit']=='KRW' and w['refresh_interval_seconds']==0 for w in widgets)
report={'passed':True,'api_mocks':False,'scope':'Owned-resource positive controls, anonymous and synthetic account B read/download denial; not a penetration test','checks':checks,'after_responsive_audit':{'widget_count':2,'layouts_match_rehearsal':True,'all_period_KRW_manual_settings_preserved':True}}
(local/'access.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
print(json.dumps({'passed':True,'checks':len(checks)}))
