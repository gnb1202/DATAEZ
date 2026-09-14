"""Backend agent quality pipeline: validate / live / report (offline regrade)."""
import argparse
from datetime import datetime, timezone
import hashlib
import html
import json
import os
from pathlib import Path
import subprocess
import sys
from uuid import uuid4

from catalog import ROOT, DEFAULT, load_catalog, select
from scoring import GRADER_VERSION, evaluate

HIDDEN = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0


def dump(path, value):
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2,default=str)+'\n',encoding='utf-8')


def tool_specs():
    os.environ.setdefault('APP_ENV','development')
    os.environ.setdefault('JWT_SECRET_KEY','quality-offline-validator-secret-not-for-deployment')
    sys.path.insert(0,str(ROOT/'api'))
    # Schema imports validate Settings but do not need a real credential. Do not
    # let the placeholder escape into the child that makes real model calls.
    previous=os.environ.get('OPENAI_API_KEY')
    if not previous: os.environ['OPENAI_API_KEY']='offline-schema-validation-only'
    try:
        from app.agent_tools import TOOL_SPECS
    finally:
        if previous is None: os.environ.pop('OPENAI_API_KEY',None)
        else: os.environ['OPENAI_API_KEY']=previous
    return {s['function']['name']:s['function']['parameters'] for s in TOOL_SPECS}


def preflight(env_file):
    from dotenv import dotenv_values
    import importlib.util
    if not (os.environ.get('OPENAI_API_KEY') or dotenv_values(env_file).get('OPENAI_API_KEY')):
        raise RuntimeError('OPENAI_API_KEY is missing; configure the local env file or CI secret')
    for name in ['psycopg','httpx','jsonschema']:
        if not importlib.util.find_spec(name): raise RuntimeError('Missing Python dependency: '+name)
    try:
        result=subprocess.run(['docker','info','--format','{{.ServerVersion}}'],capture_output=True,timeout=20,creationflags=HIDDEN)
        if result.returncode: raise RuntimeError('Docker engine unavailable; start Docker Desktop before live evaluation')
    except (FileNotFoundError,subprocess.TimeoutExpired):
        raise RuntimeError('Docker engine unavailable; start Docker Desktop before live evaluation') from None
    if not (ROOT/'web/node_modules/echarts').exists():
        raise RuntimeError('Install chart dependencies: npm ci --prefix web')


def apply_reviews(rows, path):
    reviews=json.loads(path.read_text(encoding='utf-8')) if path else []
    if len({r['id'] for r in reviews}) != len(reviews): raise ValueError('Duplicate reviews')
    by_id={r['id']:r for r in reviews}
    if by_id.keys()-{r['id'] for r in rows}: raise ValueError('Review contains unknown cases')
    for row in rows:
        review=by_id.get(row['id'])
        if review:
            if review.get('evidence_sha256')!=row['evidence_sha256']: raise ValueError('Stale review: '+row['id'])
            if type(review.get('passed')) is not bool or not review.get('reason','').strip() or not review.get('reviewer','').strip():
                raise ValueError('Review requires boolean passed, reason and reviewer')
            row['review_status']='passed' if review['passed'] else 'failed'
            row['review']=review


def write_html(out, summary):
    esc=lambda v:html.escape(str(v))
    cards=[]
    for row in summary['cases']:
        images=''.join(f'<img loading="lazy" width="900" height="420" style="height:auto" src="{esc(r["file"])}" alt="{esc(row["id"])} ECharts 렌더링">' for r in row.get('renders',[]) if r.get('passed'))
        checklist=''.join(f'<li class="{"pass" if value else "fail"}">{"PASS" if value else "FAIL"} · {esc(key)}</li>' for key,value in row['checks'].items())
        review_note=f'<p>검토 근거: {esc(row["review"]["reason"])}</p>' if row.get('review') else ''
        cards.append(f'<article id="{row["id"]}"><h2>{row["id"]} · 자동 {"PASS" if row["automatic_passed"] else "FAIL"} <small>설명 검토: {esc(row["review_status"])}</small></h2><p>{esc(row["question"])}</p><p>도구: {esc(" → ".join(row["details"]["tools"]))}</p>{review_note}{images}<details><summary>단계별 판정 · 기대값과 실제값</summary><ul>{checklist}</ul><pre>{esc(json.dumps(row["details"],ensure_ascii=False,indent=2,default=str))}</pre></details></article>')
    doc='''<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>DATA:EZ Agent Quality</title><style>body{font:15px/1.7 system-ui,sans-serif;background:#161b23;color:#e4ebf5;max-width:1120px;margin:40px auto;padding:0 22px}h1{font-size:32px}h2{font-size:21px}small{font-size:12px;color:#9bacc3}article{border:1px solid #3b485c;border-radius:12px;padding:24px;margin:22px 0}img{width:100%;background:white;border-radius:8px}pre{overflow:auto;font-size:12px}.pass{color:#8ed2b0}.fail{color:#ffaaaa}a{color:#91b5ff}summary{cursor:pointer}.notice{border-left:3px solid #719be0;padding:12px 20px;background:#212b3a}</style>'''
    doc+=f'<h1>DATA:EZ · 에이전트 품질 평가</h1><p>{esc(summary["run_id"])} · {esc(summary["status"])}</p><div class="notice">자동 계약 {summary["automatic_passed"]}/{summary["total"]} · 최종 {summary["accepted"]}/{summary["total"]} · 설명 검토 대기 {summary["review_pending"]} / 실패 {summary["review_failed"]} · 실제 모델 / 실제 HTTP / 격리 PostgreSQL<br>그래프 이미지는 실제 응답을 ECharts SVG SSR로 렌더링한 것입니다. React 화면·상호작용·미적 품질 통과를 뜻하지 않습니다.</div><p>프롬프트·도구·입력·모델 지문과 문항별 사용량은 <a href="summary.json">JSON 보고서</a>에 있습니다. 모델 판단이나 문장 속 숫자를 수치 정답으로 사용하지 않습니다.</p>'
    doc+=''.join(cards)+'</html>'
    (out/'report.html').write_text(doc,encoding='utf-8')


def report_run(run, reviews=None, compare=None):
    catalog=load_catalog(run/'questions.json')
    manifest=json.loads((run/'manifest.json').read_text(encoding='utf-8'))
    # Regrading against changed questions would rewrite the experiment.
    if hashlib.sha256((run/'questions.json').read_bytes()).hexdigest()!=manifest['question_sha256']:
        raise ValueError('Run question snapshot was modified')
    raw_dir=run/'backend'
    backend=json.loads((raw_dir/'report.json').read_text(encoding='utf-8'))
    specs=tool_specs()
    selected=select(catalog,'full',','.join(manifest['case_ids']))
    output=run/('assessment-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid4().hex[:6])
    output.mkdir(exist_ok=False)
    rows=[];render_input=[]
    for case in selected:
        evidence_path=raw_dir/f'case-{case["id"]}.json'
        if not evidence_path.exists(): raise ValueError('Missing actual execution: '+case['id'])
        raw=json.loads(evidence_path.read_text(encoding='utf-8'))
        rows.append(evaluate(case,raw,backend['fixture_ids'],specs))
        render_input.append({'id':case['id'],'charts':raw['evidence'].get('charts',[])})
    dump(output/'render-input.json',render_input)
    result=subprocess.run(['node',str(Path(__file__).with_name('render.cjs')),str(output)],cwd=ROOT,creationflags=HIDDEN)
    renders=json.loads((output/'render-results.json').read_text(encoding='utf-8')) if (output/'render-results.json').exists() else []
    for row in rows:
        row['renders']=[r for r in renders if r['id']==row['id']]
        needed=next(x for x in render_input if x['id']==row['id'])['charts']
        if needed:
            row['checks']['engine_render']=len(row['renders'])==len(needed) and all(r['passed'] for r in row['renders']) and result.returncode in {0,1}
        row['failed_checks']=[k for k,v in row['checks'].items() if v is not True]
        row['automatic_passed']=not row['failed_checks']
    apply_reviews(rows,reviews)
    fixture_ok=bool(backend.get('fixture_checks')) and all(c['passed'] for c in backend['fixture_checks'])
    execution_ok=not backend.get('harness_error') and backend.get('temporary_database_removed') is True and backend.get('source_unchanged_during_run') is True and fixture_ok
    pending=sum(r['review_status']=='pending' for r in rows)
    automatic=all(r['automatic_passed'] for r in rows) and execution_ok
    passed=automatic and not pending and not any(r['review_status']=='failed' for r in rows)
    summary={**manifest,'grader_version':GRADER_VERSION,'grader_sha256':hashlib.sha256(Path(__file__).with_name('scoring.py').read_bytes()).hexdigest(),
             'worker_model':backend['worker_model'],'router_model':backend['router_model'],
             'source_sha256':backend['source_sha256'],'fixture_sha256':backend['fixture_sha256'],
             'prompt_sha256':{k:v for k,v in backend['source_sha256'].items() if k in {'api/app/prompts.py','api/app/library_agent.py','api/app/router.py'}},
             'tool_schema_sha256':hashlib.sha256(json.dumps(specs,sort_keys=True,ensure_ascii=False).encode()).hexdigest(),
             'real_llm':backend['real_llm'],'real_http':True,'real_postgres':True,'react_ui_tested':False,
             'usage':backend.get('usage'),'setup_usage_metrics':backend.get('setup_usage_metrics'),
             'agent_limits':backend.get('agent_limits'),'automatic_question_retries':0,
             'total':len(rows),'automatic_passed':sum(r['automatic_passed'] for r in rows),'automatic_gate_passed':automatic,
             'execution_integrity':execution_ok,'review_pending':pending,'passed':passed,
             'review_failed':sum(r['review_status']=='failed' for r in rows),
             'accepted':sum(r['automatic_passed'] and r['review_status'] in {'passed','not_required_for_contract'} for r in rows),
             'status':'passed' if passed else 'needs_review' if automatic and pending else 'failed','cases':rows}
    groups={'function_calling':['function_arguments_schema','preview_tool_succeeded','no_write_tool_attempt'],
            'natural_language_contract':['semantic_definition','tool_input_semantics','definition_matches'],
            'exact_calculation':['exact_cells','parameterized_sql'],
            'chart_contract':['exactly_one_chart','chart_type','chart_definition','chart_exact_cells','chart_unit','chronological_axis'],
            'render_engine':['engine_render']}
    summary['dimensions']={name:{'passed':sum(all(row['checks'].get(k,True) for k in keys) for row in rows if any(k in row['checks'] for k in keys)),
        'applicable':sum(any(k in row['checks'] for k in keys) for row in rows)} for name,keys in groups.items()}
    if compare:
        previous=json.loads(compare.read_text(encoding='utf-8'))
        if previous['question_sha256']!=summary['question_sha256'] or previous['case_ids']!=summary['case_ids']:
            raise ValueError('Comparison requires identical questions and selected cases')
        if previous['fixture_sha256']!=summary['fixture_sha256']:
            raise ValueError('Comparison requires identical fixtures')
        old={r['id']:r['automatic_passed'] for r in previous['cases']}
        summary['comparison']={'baseline_sha256':hashlib.sha256(compare.read_bytes()).hexdigest(),
            'new_failures':[r['id'] for r in rows if old[r['id']] and not r['automatic_passed']],
            'fixed':[r['id'] for r in rows if not old[r['id']] and r['automatic_passed']],
            'models_unchanged':all(previous[k]==summary[k] for k in ['worker_model','router_model'])}
        old_reviews={r['id']:r['review_status'] for r in previous['cases']}
        summary['comparison']['review_fixed']=[r['id'] for r in rows if old_reviews[r['id']]=='failed' and r['review_status']=='passed']
        summary['comparison']['review_regressed']=[r['id'] for r in rows if old_reviews[r['id']]=='passed' and r['review_status']=='failed']
    dump(output/'summary.json',summary)
    dump(output/'review-template.json',[{'id':r['id'],'evidence_sha256':r['evidence_sha256'],'passed':None,'reviewer':'','reason':''} for r in rows if r['review_status']=='pending'])
    write_html(output,summary)
    dump(run/'latest.json',{'assessment':output.name,'status':summary['status']})
    print(f"Automatic {summary['automatic_passed']}/{summary['total']}; review pending {pending}; {summary['status']}",flush=True)
    print('Report: '+str(output/'report.html'),flush=True)
    return summary


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('mode',choices=['validate','live','report'])
    p.add_argument('--suite',choices=['smoke','full'],default='smoke')
    p.add_argument('--cases',help='Comma separated IDs; dependencies automatically included')
    p.add_argument('--questions',type=Path,default=DEFAULT)
    p.add_argument('--env-file',type=Path,default=ROOT/'.env')
    p.add_argument('--run',type=Path,help='Existing run for offline regrading')
    p.add_argument('--reviews',type=Path)
    p.add_argument('--compare',type=Path,help='Prior summary.json with identical question subset')
    p.add_argument('--automatic-only',action='store_true',help='Gate only machine contracts; semantic review may remain pending')
    args=p.parse_args()
    if args.mode=='report':
        if not args.run: p.error('--run required')
        summary=report_run(args.run.resolve(),args.reviews,args.compare)
    else:
        catalog=load_catalog(args.questions);selected=select(catalog,args.suite,args.cases)
        tool_specs()
        print(f"Question set valid: {len(catalog['cases'])} cases; selected {len(selected)}. No model calls during validate.",flush=True)
        if args.mode=='validate': return 0
        preflight(args.env_file)
        run=ROOT/'.local-test/agent-quality'/('run-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid4().hex[:8])
        run.mkdir(parents=True)
        question_bytes=args.questions.read_bytes();(run/'questions.json').write_bytes(question_bytes)
        manifest={'run_id':run.name,'question_sha256':hashlib.sha256(question_bytes).hexdigest(),'case_ids':[c['id'] for c in selected],
                  'suite':'subset' if args.cases else args.suite,'started_at':datetime.now(timezone.utc).isoformat(),
                  'source_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()}
        dump(run/'manifest.json',manifest)
        env={**os.environ,'PYTHONIOENCODING':'utf-8','AGENT_MAX_ITERATIONS':'8','AGENT_MAX_TOKEN_BUDGET':'24000','AGENT_TIMEOUT_SECONDS':'200'}
        print('Run: '+str(run),flush=True)
        command=[sys.executable,str(ROOT/'scripts/unseen-eval/run.py'),'--live-llm','--question-set',str(run/'questions.json'),
                 '--cases',','.join(manifest['case_ids']),'--output-dir',str(run/'backend'),'--env-file',str(args.env_file.resolve())]
        result=subprocess.run(command,cwd=ROOT,env=env,creationflags=HIDDEN)
        if result.returncode:
            dump(run/'pipeline-error.json',{'stage':'backend','exit_code':result.returncode,'passed':False})
            print('Backend stopped; inspect preserved local evidence. No automatic retry.',flush=True)
            return 1
        summary=report_run(run,args.reviews,args.compare)
    return 0 if (summary['automatic_gate_passed'] if args.automatic_only else summary['passed']) else 2


if __name__=='__main__':
    try: raise SystemExit(main())
    except (RuntimeError,ValueError) as exc:
        print('Pipeline stopped: '+str(exc),file=sys.stderr)
        raise SystemExit(1)
