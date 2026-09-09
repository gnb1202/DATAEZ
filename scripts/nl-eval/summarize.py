"""Publish a credential-free report after explicit review of all 50 responses."""
import argparse
import hashlib
import json
import math
from pathlib import Path

from cases import CASES

CRITICAL = {'source_state_unchanged', 'no_raw_write_tool', 'foreign_value_not_exposed',
            'only_requested_widget_write_tools', 'other_dashboards_unchanged',
            'widgets_unchanged', 'metric_sources_match_request', 'no_save'}


def percentile(values, q):
    values = sorted(values)
    return values[max(0, math.ceil(len(values)*q)-1)] if values else None


def stage(check):
    if check in CRITICAL: return 'scope_or_mutation'
    if 'definition' in check or 'revision' in check: return 'definition'
    if 'result' in check or 'undefined' in check or 'number' in check: return 'calculation'
    if 'chart' in check: return 'chart'
    if 'explanation' in check or 'answer' in check: return 'explanation'
    if check == 'runtime_error': return 'runtime'
    if 'tool' in check or 'preview' in check: return 'routing_or_tool'
    return 'persistence'


def summarize(paths, reviews, expected_ids=None):
    all_ids = {c['id'] for c in CASES}
    expected_ids = all_ids if expected_ids is None else set(expected_ids)
    if not expected_ids or expected_ids-all_ids: raise ValueError('Invalid expected coverage')
    full_suite = expected_ids == all_ids
    reports = [json.loads(path.read_text(encoding='utf-8')) for path in paths]
    if len({r['benchmark_sha256'] for r in reports}) != 1: raise ValueError('Benchmark fingerprints differ')
    if len({r['source_sha256'] for r in reports}) != 1: raise ValueError('Application source fingerprints differ; report separate runs')
    if len({(r['worker_model'], r['router_model'], r['embedding_model'], r['as_of']) for r in reports}) != 1:
        raise ValueError('Models or relative-date fixtures differ')
    seen, cases = set(), []
    for path, report in zip(paths, reports):
        if not report.get('real_models') or not report.get('source_unchanged_during_run') or not report.get('temporary_database_removed'):
            raise ValueError('Incomplete/non-live/unclean run')
        if not all(c['passed'] for c in report['fixture_checks']): raise ValueError('Fixture preparation failed')
        for case in report['cases']:
            cid = case['id']
            if cid in seen: raise ValueError('Duplicate case: '+cid)
            seen.add(cid)
            raw = path.parent/f'case-{cid}.json'
            digest = hashlib.sha256(raw.read_bytes()).hexdigest()
            saved = json.loads(raw.read_text(encoding='utf-8'))['case']
            if any(saved.get(k) != case.get(k) for k in ['id', 'question', 'answer', 'checks', 'passed']):
                raise ValueError('Report differs from case evidence: '+cid)
            required_checks = {'source_state_unchanged', 'no_raw_write_tool', 'foreign_value_not_exposed',
                               'only_requested_widget_write_tools', 'other_dashboards_unchanged'}
            if not required_checks <= set(case.get('checks', {})): raise ValueError('Required behavior checks missing: '+cid)
            key = report['run_id']+'/'+cid
            review = reviews.get(key)
            if not review or review.get('evidence_sha256') != digest or not isinstance(review.get('passed'), bool) or not review.get('notes'):
                raise ValueError('Missing or stale explicit semantic review: '+key)
            failed = [key for key, value in case.get('checks', {}).items() if not value]
            if case.get('error'): failed.append('runtime_error')
            cases.append(dict(id=cid, run_id=report['run_id'], question=case['question'], answer=case.get('answer'),
                automatic_passed=case['passed'], semantic_passed=review['passed'], passed=case['passed'] and review['passed'],
                checks=case.get('checks', {}), failed_stages=sorted({stage(key) for key in failed} | ({'explanation'} if not review['passed'] else set())),
                review=review['notes'], seconds=case['seconds'], usage=case.get('usage', {}), tools=case.get('tools', []),
                evidence_sha256=digest))
    if seen != expected_ids: raise ValueError('Exactly the declared question coverage is required')
    cases.sort(key=lambda c: c['id'])
    passed = sum(c['passed'] for c in cases)
    critical_failures = [{'id': c['id'], 'check': k} for c in cases for k,v in c['checks'].items() if k in CRITICAL and not v]
    usage = {k: round(sum(c['usage'].get(k, 0) or 0 for c in cases), 6) for k in ['calls', 'prompt_tokens', 'completion_tokens', 'total_tokens', 'cost_usd']}
    times = [c['seconds'] for c in cases]
    output = {k: reports[0][k] for k in ['benchmark_version', 'benchmark_sha256', 'source_sha256', 'as_of', 'worker_model', 'router_model', 'embedding_model', 'cost_note']}
    output.update(synthetic=True, real_models=True, real_embeddings=True, real_postgres=True, real_http_imports=True,
        agent_path='production synchronous run_agent', browser_evaluated=False, streaming_evaluated=False,
        suite_kind='full' if full_suite else 'regression', full_suite_coverage=full_suite,
        sample_size=len(cases), automatic_passed=sum(c['automatic_passed'] for c in cases), semantic_passed=sum(c['semantic_passed'] for c in cases),
        passed_cases=passed, pass_rate=passed/len(cases), critical_failures=critical_failures,
        acceptance_target_met=(passed >= 45 and not critical_failures) if full_suite else None, all_cases_passed=passed == len(cases),
        temporary_databases_removed=True, usage=usage,
        latency_seconds={'p50': percentile(times, .5), 'p95': percentile(times, .95), 'max': max(times), 'method': f'nearest rank; {len(paths)} isolated suite shard(s)'},
        estimated_cost_per_passed_case_usd=round(usage['cost_usd']/passed, 6) if passed else None,
        retrieval_checks=[dict(run_id=r['run_id'], queries=r['retrieval'], usage=r['retrieval_usage']) for r in reports],
        cases=cases,
        limitations=['Small synthetic fixtures, not production load or a representative merchant sample.',
                    'Semantic review performed by the coding assistant from full responses and execution evidence, not an independent merchant panel.',
                    'Three auxiliary RAG queries repeated per shard; not 50-question retrieval recall.',
                    'Per-question cost excludes fixture indexing; uses the repository estimate rather than billing.'])
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('reports', nargs='+', type=Path)
    parser.add_argument('--reviews', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--cases', help='Explicit regression subset (same syntax as run.py); never reported as a full-suite pass')
    args = parser.parse_args()
    from run import selection
    expected_ids = {c['id'] for c in selection(args.cases)} if args.cases else None
    result = summarize(args.reports, json.loads(args.reviews.read_text(encoding='utf-8')), expected_ids)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps({key: result[key] for key in ['passed_cases', 'acceptance_target_met', 'latency_seconds', 'usage']}, ensure_ascii=False))


if __name__ == '__main__': main()
