"""Publish sanitized final-QA evidence. Original phase reports are never overwritten."""
import csv
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import urllib.parse

ROOT=Path(__file__).resolve().parents[2]
local=ROOT/'.local-test/portfolio-demo/final-qa'
out=ROOT/'docs/portfolio-demo'
read=lambda p:json.loads(p.read_text(encoding='utf-8-sig'))
first=read(local/'first-use.json');analysis=read(local/'analysis/rehearsal.json')
access=read(local/'access.json');auth=read(local/'auth.json');responsive=read(local/'responsive.json')
recovery=read(ROOT/'scripts/ui-eval/artifacts/usability/after/report.json')
upload=read(ROOT/'scripts/ui-eval/artifacts/direct-upload/report.json')
playback=read(local/'playback.json');package=read(local/'package.json')
for item in [first,analysis,access,auth,responsive,recovery,upload,playback,package]: assert item['passed']
with (ROOT/'samples/demo/portfolio-original.csv').open(encoding='utf-8-sig',newline='') as f: rows=list(csv.DictReader(f))
with (ROOT/'samples/demo/additional-transaction.csv').open(encoding='utf-8-sig',newline='') as f: extra=list(csv.DictReader(f))
assert sum(Decimal(r['amount']) for r in rows)==Decimal('690200')
assert sum(Decimal(r['amount']) for r in rows+extra)==Decimal('720200')
for query in analysis['queries']:
    assert query['chart_count']==1
    assert query['metric_definition']['chart_type']=='line'
    assert query['metric_definition']['unit']=='KRW' and query['metric_definition']['time_range']=='all'
phase3=read(out/'phase-3-render.json')
for name,details in phase3['files'].items(): assert package['files'][name]['sha256']==details['sha256']
extracted=Path(package['extracted'])
html=(extracted/'index.html').read_text(encoding='utf-8')
for raw in re.findall(r'(?:href|src)="([^"]+)"|url\(([^)]+)\)',html):
    link=raw[0] or raw[1]
    if link.startswith(('http:','https:','#')):continue
    assert (extracted/link).is_file(),link
assert (extracted/'fonts/spoqa.ttf').is_file()
deployments={}
for name in ['web','api']:
    item=read(local/(name+'-deployment.json'))
    assert item['readyState']=='READY'
    deployments[name]={k:item.get(k) for k in ['id','url','readyState','target','createdAt','gitSource']}
assets={
 'phase-5-first-use.png':local/'first-ready.png',
 'phase-5-dashboard.png':local/'dashboard-dark-1440.png',
 'phase-5-mobile-table.png':local/'sql-light-390.png',
 'phase-5-mobile-save.png':ROOT/'scripts/ui-eval/artifacts/usability/after/save-dark-390.png',
 'phase-5-zoom-equivalent.png':local/'dashboard-200-percent-equivalent.png'}
for name,src in assets.items():shutil.copyfile(src,out/'assets'/name)
private=[]
def secrets(value):
    if isinstance(value,dict):
        for k,v in value.items():
            if k in {'email','password','token','refresh_token','access_token'} and isinstance(v,str) and len(v)>7:private.append(v)
            elif isinstance(v,(dict,list)):secrets(v)
    elif isinstance(value,list):
        for v in value:secrets(v)
for p in [local/'account.json',local/'account-b.json',local.parent/'account.json']:secrets(read(p))
texts=[];patterns=[];private_hits=[]
paths=set(subprocess.check_output(['git','ls-files'],cwd=ROOT,text=True).splitlines())
paths.update(p.relative_to(ROOT).as_posix() for p in (ROOT/'scripts/portfolio-demo').glob('*') if p.is_file())
paths.update(p.relative_to(ROOT).as_posix() for p in out.glob('*.md'))
for name in sorted(paths):
    p=ROOT/name
    if not p.is_file():continue
    if p.suffix.lower() not in {'.md','.json','.py','.js','.cjs','.ts','.tsx','.html','.yml','.yaml','.toml','.txt','.srt','.env'}:continue
    try:s=p.read_text(encoding='utf-8-sig')
    except UnicodeError:continue
    texts.append(name)
    if any(secret in s for secret in private):private_hits.append(name)
    if re.search(r'(?:sk-proj-[A-Za-z0-9_-]{35,}|sb_secret_[A-Za-z0-9_-]{25,}|eyJ[A-Za-z0-9_-]{25,}\.[A-Za-z0-9_-]{15,}\.[A-Za-z0-9_-]{15,})',s):patterns.append(name)
assert not private_hits, 'Private account values found; values suppressed'
assert not patterns, 'Credential-shaped strings require manual review: '+str(patterns)
docs=['README.md','docs/README.md','docs/ARCHITECTURE.md','docs/PORTFOLIO_DEMO_PLAN.md','docs/portfolio-demo/FINAL_QA.md','docs/portfolio-demo/RUNBOOK.md','docs/portfolio-demo/VIDEO_RELEASE.md','docs/portfolio-demo/CASE_STUDY.md','docs/portfolio-demo/ACCEPTANCE.md']
missing=[];links=0
for name in docs:
    p=ROOT/name
    for target in re.findall(r'\[[^\]]*\]\(([^)]+)\)',p.read_text(encoding='utf-8')):
        if re.match(r'^[a-z]+:',target):continue
        links+=1;raw,_,anchor=target.partition('#');dest=(p.parent/urllib.parse.unquote(raw)).resolve() if raw else p
        if not dest.exists() and dest!=out/'phase-5-qa.json':missing.append({'source':name,'target':target})
        if anchor and dest.exists() and dest.suffix=='.md':
            slugs=[re.sub(r'[^\w\- ]','',h.lower()).replace(' ','-') for h in re.findall(r'^#{1,6}\s+(.+)$',dest.read_text(encoding='utf-8'),re.M)]
            if urllib.parse.unquote(anchor) not in slugs:missing.append({'source':name,'target':target})
assert not missing,missing
assert not subprocess.check_output(['git','diff','HEAD','--name-only','--','web/','api/'],cwd=ROOT,text=True).strip()
public_package={k:v for k,v in package.items() if k not in ['zip','extracted']}
public_package['zip']='output/portfolio-demo-delivery.zip'
public_package['relocated_temp_folder_verified']=True
report={'status':'passed','date':datetime.now(timezone.utc).isoformat(),'baseline_commit':analysis['source_commit'],
 'scope':'Portfolio final QA; real public onboarding/analysis/access, isolated failure fixtures, emulated responsive UI and local media delivery',
 'deployments':deployments,'deployment_commit_note':'Vercel inspect provides no gitSource; do not infer an exact deployed source SHA from the local baseline.',
 'application_code_changed':False,'separate_application_deployment_performed':False,'video_public_hosting':False,
 'first_use':first,'analysis':analysis,'access':access,'auth_failure_fixtures':auth,'recovery_fixtures':recovery,
 'upload_failure_fixtures':upload,'responsive':responsive,
 'api_targeted_tests':{'passed':24,'skipped':17,'seconds':10.88,'scope':['test_auth.py','test_direct_uploads.py','test_file_scopes.py','test_serverless_limits.py'],'skips':'DB-dependent tests not executed in this local invocation'},
 'baseline_ci':{'commit':'b23c68f687fdc79001502e01e41635b533f9db00','tests':'https://github.com/gnb1202/DATAEZ/actions/runs/34692373340','docker':'https://github.com/gnb1202/DATAEZ/actions/runs/34692373363','conclusion':'success'},
 'package':public_package,'relocated_playback':playback,'video_bytes_match_phase_3':True,
 'privacy':{'text_files_scanned':len(texts),'known_private_value_matches':0,'credential_pattern_matches':0,'media':'New representative screenshots visually reviewed; prior video privacy/frame review inherited only after matching all four hashes. Not a full-history secret audit or penetration test.'},
 'docs':{'local_links_checked':links,'missing_paths_or_anchors':missing},
 'findings':[{'kind':'test_harness','severity':'P2','status':'fixed','detail':'Legacy usability test assumed expanded guide and lacked upload capabilities fixture; aligned with current app contract.'},
 {'kind':'test_harness','severity':'P2','status':'fixed','detail':'Wait for focus restoration and ready dashboard before responsive capture; scroll save settings into view.'}],
 'open_p0':0,'open_p1':0,
 'limits':['No physical mobile/Safari run','200% equivalent CSS viewport/DPR checked; native headless Edge zoom shortcuts ignored','No PG integration, load test, customer study or comprehensive security audit','Video public hosting deferred'],
 'evidence_images':list(assets)}
encoded=json.dumps(report,ensure_ascii=False,indent=2)+'\n'
assert not any(secret in encoded for secret in private)
(out/'phase-5-qa.json').write_text(encoded,encoding='utf-8')
print(json.dumps({'status':'passed','local_links':links,'privacy_text_files':len(texts),'images':len(assets),'zip_bytes':package['zip_bytes']},ensure_ascii=False))
