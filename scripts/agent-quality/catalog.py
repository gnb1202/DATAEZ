"""Versioned question contracts. No application imports or model calls."""
import importlib.util
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT = ROOT / 'samples/agent-quality-v1/questions.json'
spec = importlib.util.spec_from_file_location('quality_fixture_oracle', ROOT / 'scripts/unseen-eval/fixtures.py')
oracle = importlib.util.module_from_spec(spec)
spec.loader.exec_module(oracle)


def load_catalog(path=DEFAULT):
    catalog = json.loads(Path(path).read_text(encoding='utf-8'))
    if catalog.get('version') != 'agent-quality-v1':
        raise ValueError('Unsupported question-set version')
    cases = catalog['cases']
    seen = set()
    allowed = {'id','question','file','scope','mode','category','group','grain','chart',
               'operation','column','filters','review','selections','required_tool',
               'expected','tags','depends','streaming'}
    for case in cases:
        if set(case) - allowed:
            raise ValueError(f"Unknown fields: {case['id']}")
        if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]{0,63}',case['id']) or case['id'] in seen or not case['question'].strip():
            raise ValueError('Empty or duplicate case')
        if case.get('depends') and case['depends'] not in seen:
            raise ValueError('Dependencies must precede their follow-up')
        seen.add(case['id'])
        if case['file'] not in oracle.FILES or case['file'] == 'holdout':
            raise ValueError('Unsupported fixture; old holdout must stay separate')
        if case['scope'] not in {'original_file','linked_ledger'}:
            raise ValueError('Invalid source scope')
        if case['mode'] not in {'metric','clarify'}:
            raise ValueError('Only read-only preview / clarification cases supported')
        if case.get('chart') not in {None,'line','bar','pie'}:
            raise ValueError('Unsupported chart type')
        for key in case.get('selections',[case['file']]):
            if key not in oracle.FILES and key != 'document':
                raise ValueError('Unknown selected fixture')
        if case['mode'] == 'metric':
            if case['expected'] != oracle.expected(case):
                raise ValueError(f"Frozen Decimal oracle mismatch: {case['id']}")
            if case.get('chart') and not case.get('group'):
                raise ValueError('Chart contract needs a dimension')
        elif case.get('expected') is not None or not case.get('review'):
            raise ValueError('Clarifications need review criteria, not numerical answers')
    if not cases or not set(catalog['smoke']).issubset(seen):
        raise ValueError('Invalid smoke subset')
    return catalog


def select(catalog, suite='smoke', ids=None):
    wanted = set(ids.split(',')) if ids else set(catalog['smoke'] if suite == 'smoke' else [c['id'] for c in catalog['cases']])
    known = {c['id']: c for c in catalog['cases']}
    if not wanted or wanted - known.keys():
        raise ValueError('Unknown / empty case selection')
    while True:
        deps = {known[k]['depends'] for k in wanted if known[k].get('depends')}
        if deps.issubset(wanted):
            return [c for c in catalog['cases'] if c['id'] in wanted]
        wanted |= deps
