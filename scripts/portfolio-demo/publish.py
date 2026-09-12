"""Publish sanitized evidence only after two consecutive successful rehearsals."""
import hashlib
import json
from pathlib import Path
import shutil

from prepare import ROOT, LOCAL, OUT, STATE


def main():
    paths = sorted((LOCAL/'takes').glob('*/rehearsal.json'), key=lambda p: json.loads(p.read_text(encoding='utf-8'))['started_at'])
    reports = [json.loads(p.read_text(encoding='utf-8')) for p in paths]
    latest = reports[-2:]
    assert len(latest) == 2 and all(r['passed'] for r in latest), 'Two consecutive complete takes are required'
    assert len({r['source_commit'] for r in latest}) == 1, 'Rehearse twice on the same implementation'
    public = {'status':'passed', 'api_mocks':False, 'consecutive_successes':2,
              'source_commit':latest[-1]['source_commit'], 'synthetic':True,
              'attempt_count':len(reports), 'real_queries_total':sum(len(r['queries']) for r in reports),
              'prior_attempts':[{'project_id':r['project_id'], 'passed':r['passed'], 'stage':r['stage'],
                 'failure_name':r.get('failure',{}).get('name')} for r in reports[:-2]],
              'takes':latest, 'assets':{},
              'privacy':'Private account label masked during screenshot capture; results and charts unchanged.',
              'token_usage':'Persisted message API did not expose token usage; null is unavailable, not zero.'}
    for name in ('dashboard-dark','dashboard-light','Q1-library','Q1-analysis','Q1-sql','Q2-sql'):
        source = paths[-1].parent/(name+'.png')
        target = OUT/'assets'/('phase-2-'+name+'.png')
        shutil.copyfile(source,target)
        public['assets'][name]={'path':'assets/'+target.name,'sha256':hashlib.sha256(target.read_bytes()).hexdigest()}
    text = json.dumps(public,ensure_ascii=False,indent=2)+'\n'
    state = json.loads(STATE.read_text(encoding='utf-8'))
    for key in ('email','password'):
        assert state[key] not in text, 'Private credential in report'
    (OUT/'phase-2-rehearsal.json').write_text(text,encoding='utf-8')
    print('Published two successful takes and six screenshots; private credentials excluded')


if __name__ == '__main__':
    main()
