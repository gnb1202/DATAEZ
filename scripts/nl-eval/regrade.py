"""Regrade complete saved evidence without another model call; keep originals."""
import argparse
from datetime import date
import hashlib
import json
from pathlib import Path

from cases import CASES
from grading import grade
from run import ROOT, dump


def regrade(path):
    original = json.loads(path.read_text(encoding='utf-8'))
    report = dict(original, cases=[])
    report['regraded_from'] = {'report_sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
        'benchmark_sha256': original['benchmark_sha256'],
        'reason': 'A correct explicitly requested edit may omit a redundant preview. A profit request with missing cost data must not calculate an arbitrary substitute. Questions and fixtures are unchanged; exact definitions/results remain checked.'}
    report['benchmark_sha256'] = hashlib.sha256(b''.join((ROOT/'scripts/nl-eval'/name).read_bytes() for name in ['cases.py', 'oracle.py', 'grading.py'])).hexdigest()
    ids = json.loads((path.parent/'fixture-ids.json').read_text(encoding='utf-8'))
    rows = json.loads((path.parent/'fixtures.json').read_text(encoding='utf-8'))
    out = path.parent/'regraded'
    out.mkdir(exist_ok=True)
    for old in original['cases']:
        raw = json.loads((path.parent/f"case-{old['id']}.json").read_text(encoding='utf-8'))
        if not raw.get('evidence') or old.get('error'): raise ValueError('Incomplete evidence cannot be regraded')
        spec = next(c for c in CASES if c['id'] == old['id'])
        wanted_question = spec['question'].format(foreign_store=ids['stores']['foreign'], foreign_table=ids['tables']['foreign'])
        if old['question'] != wanted_question: raise ValueError('Question changed; make a fresh model run')
        checks, details = grade(spec, raw['evidence'], raw['widgets_before'], raw['widgets_after'],
            old['checks']['source_state_unchanged'], rows, date.fromisoformat(original['as_of']), ids['tables'], ids['stores'])
        case = dict(old, checks=checks, passed=all(checks.values()))
        dump(out/f"case-{old['id']}.json", dict(raw, case=case, details=details))
        report['cases'].append(case)
    report['automatic_passed'] = sum(c['passed'] for c in report['cases'])
    report['automatic_acceptance'] = all(c['passed'] for c in report['cases']) and original['source_unchanged_during_run']
    dump(out/'report.json', report)
    print(str(out/'report.json'), report['automatic_passed'])


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('reports', nargs='+', type=Path)
    for path in parser.parse_args().reports: regrade(path)
