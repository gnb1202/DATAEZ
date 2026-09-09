"""Merge immutable live traces with explicit reviewer decisions; no model calls."""
import json
from pathlib import Path
import re
import statistics

from oracle import ROOT, expected


def load(path):
    return json.loads(path.read_text(encoding='utf-8'))


def values(node):
    if isinstance(node, dict):
        for k, v in node.items():
            if k in {'value', 'result'} and isinstance(v, (str, int, float)):
                yield str(v)
            yield from values(v)
    elif isinstance(node, list):
        for item in node:
            yield from values(item)


def main():
    review = load(Path(__file__).with_name('reviews') / '2026-09-08.json')
    oracle = expected()
    runs, final = [], {}
    for run in review['runs']:
        folder = Path(__file__).with_name('artifacts') / run['id']
        raw = load(folder / 'report.json')
        cases = []
        for recorded in raw['cases']:
            evidence = load(folder / ('case-' + recorded['id'] + '.json'))
            case = dict(recorded)
            checks = dict(case['checks'])
            steps = evidence.get('evidence', {}).get('steps', [])
            outputs = [s['tool_output'] for s in steps if s.get('tool_output')]
            # Correct the initial grader's event-type assumption using recorded
            # tool outputs, without changing or regenerating any model answer.
            if 'amount_from_executed_tool' in checks:
                wanted = {'net': oracle['gangnam_pg']['net'], 'refund_net': oracle['gangnam_pg']['net'],
                          'month_save': oracle['gangnam_pg']['monthly']['2026-09'],
                          'last_month': oracle['gangnam_pg']['monthly']['2026-08'],
                          'combined': oracle['gangnam_combined']['monthly']['2026-09']}[case['kind']]
                checks['amount_from_executed_tool'] = wanted in set(values(outputs))
            if case['kind'] == 'freshness':
                checks.pop('history_tool_used', None)
                checks['freshness_source_used'] = 'list_ledger_sources' in case['tools']
            if case['kind'] == 'overlap':
                answer = re.sub(r'[,\s*`]', '', case['answer'])
                checks['new_and_skipped_counts'] = bool(re.search(r'(?<!\d)14건', answer)) and bool(re.search(r'(?<!\d)12건', answer))
                ids = {str(b['id']) for out in outputs for b in out.get('batches', []) if b.get('filename') == '03_gangnam_pg_overlap.csv'}
                checks['requested_batch_reviewed'] = any(s.get('tool_name') == 'inspect_import_review' and str(s.get('tool_input', {}).get('batch_id')) in ids for s in steps)
            if case['kind'] == 'ambiguous':
                checks['no_assumed_metric_calculation'] = 'preview_metric' not in case['tools']
            failed = case['id'] in run['failed']
            case.update(checks=checks, automated_passed=all(checks.values()), semantic_review='fail' if failed else 'pass',
                        review_note=run['failed'].get(case['id']) or run['notes'].get(case['id'], ''),
                        evidence_path=str((folder / ('case-' + case['id'] + '.json')).relative_to(ROOT)).replace('\\', '/'))
            case['passed'] = case['automated_passed'] and not failed
            cases.append(case)
            final[case['id']] = {**case, 'run_id': run['id']}
        runs.append({'run_id': run['id'], 'label': run['label'], 'cases': cases,
                     'data_checks_passed': sum(c['passed'] for c in raw['data_checks']),
                     'automated_passed': sum(c['automated_passed'] for c in cases),
                     'reviewed_passed': sum(c['passed'] for c in cases), 'usage': raw.get('usage', {}),
                     'database_removed': raw['database_removed']})
    elapsed = [c['seconds'] for r in runs for c in r['cases']]
    output = {'synthetic': True, 'rag_evaluated': False, 'reviewer': review['reviewer'], 'scope': review['scope'],
              'runs': runs, 'resolved_examples': sum(c['passed'] for c in final.values()), 'unique_cases': len(final),
              'live_turns': len(elapsed), 'latency_seconds': {'median': statistics.median(elapsed), 'min': min(elapsed), 'max': max(elapsed)},
              'usage': {k: sum(r['usage'].get(k, 0) or 0 for r in runs) for k in ['calls', 'prompt_tokens', 'completion_tokens', 'total_tokens', 'cost_usd']},
              'cost_note': 'Repository price estimate only, not verified billing.',
              'grader_corrections': ['AgentStep stores results on tool_call, not separate tool_result steps.',
                                      'Freshness is directly available from list_ledger_sources; history is not required.',
                                      'Count matching now checks numbers followed by 건 instead of matching digits inside UUIDs or timestamps.',
                                      'Ambiguous requests require no assumed preview as well as no save.'],
              'final_cases': [final[k] for k in sorted(final)], 'remaining_limits': review['remaining_limits']}
    destination = ROOT / 'docs/evaluations/pg-2026-09-08.json'
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(output, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({k: v for k, v in output.items() if k not in {'runs', 'final_cases'}}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
