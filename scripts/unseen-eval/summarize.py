"""Publish a single run only after all explanations have a hash-bound review."""
import argparse
import hashlib
import json
from pathlib import Path
from grading import CRITICAL

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run',type=Path)
    parser.add_argument('--reviews',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();run=args.run.resolve()
    report=json.loads((run/'report.json').read_text(encoding='utf-8'))
    review=json.loads(args.reviews.read_text(encoding='utf-8'))
    assert review['run_id']==report['run_id']
    assert report.get('temporary_database_removed') and report.get('source_unchanged_during_run')
    assert not report.get('harness_error') and report['real_llm']
    assert all(c['passed'] for c in report['fixture_checks'])
    cases=report['cases'];ids={c['id'] for c in cases}
    assert len(ids)==len(cases)==len(review['cases'])
    assert ids=={r['id'] for r in review['cases']}
    reviews={r['id']:r for r in review['cases']}
    for case in cases:
        r=reviews[case['id']];path=run/f"case-{case['id']}.json"
        assert r['evidence_sha256']==hashlib.sha256(path.read_bytes()).hexdigest(),case['id']
        assert isinstance(r['passed'],bool) and r['reason'].strip()
        assert case.get('assistant_persisted') is True,case['id']
        evidence=json.loads(path.read_text(encoding='utf-8'))
        case['tool_calls']=[s for s in evidence['evidence'].get('steps',[]) if s.get('type')=='tool_call']
        case['expected_vs_actual']=evidence.get('details',{})
        case['critical_failures']=sorted(k for k in CRITICAL if case.get('checks',{}).get(k) is False)
        case['semantic_review']=r
        case['passed']=case['automatic_passed'] and r['passed']
    report['critical_failures']=[{'id':c['id'],'failures':c['critical_failures']} for c in cases if c['critical_failures']]
    report['semantic_review']={'reviewer':review['reviewer'],'reviewed_at':review['reviewed_at']}
    report['final_passed']=sum(c['passed'] for c in cases)
    target={'main':27,'holdout':9}.get(report['suite'])
    expected_count={'main':30,'holdout':10}.get(report['suite'])
    if expected_count:assert len(cases)==expected_count
    report['target']=target
    report['passed']=report['final_passed']>=target and not report['critical_failures'] if target is not None else None
    report['raw_report_sha256']=hashlib.sha256((run/'report.json').read_bytes()).hexdigest()
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(f"{report['suite']}: {report['final_passed']}/{len(cases)}; acceptance={report['passed']}")

if __name__=='__main__':main()
