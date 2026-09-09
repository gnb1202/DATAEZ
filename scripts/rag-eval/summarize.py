"""Derive public F evidence from immutable local runs; no model calls or secrets."""
import json
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[2]
ARTIFACTS = Path(__file__).with_name('artifacts')
RUNS = [
    ('dataez_rag_eval_f008814f380f4a4c98e88801fb542da9', 'Browser navigation interrupted session restoration; no chat turn sent.'),
    ('dataez_rag_eval_dc1e5c6847b0499f84eabb412c390940', 'Harness typed before new-conversation messages finished loading; no chat turn sent.'),
    ('dataez_rag_eval_a459456ea60c45739469485fb4042070', 'Two real chat turns succeeded. Harness required thousands separators; actual widget displayed 1358000. Failed assertion retained.'),
    ('dataez_rag_eval_5160e160c84747c1895b01df5d90c632', 'Browser rerun passed; DB confirms one widget, value 1358000, hourly interval, and embedding usage.'),
]


def main():
    runs = []
    for run_id, note in RUNS:
        folder = ARTIFACTS / run_id
        raw = json.loads((folder / 'report.json').read_text(encoding='utf-8'))
        browser_path = folder / 'browser.json'
        browser = json.loads(browser_path.read_text(encoding='utf-8')) if browser_path.exists() else {}
        runs.append({k: raw.get(k) for k in ['run_id', 'started_at', 'finished_at', 'embedding_model', 'worker_model',
                    'router_model', 'pgvector_version', 'browser_only', 'checks', 'retrieval', 'retrieval_usage',
                    'agent', 'browser_messages', 'passed', 'temporary_database_removed', 'ordinary_web_build_restored']})
        runs[-1].update(note=note, retrieval_count=len(raw['retrieval']),
            hit_at_1=sum(c['hit_at_1'] for c in raw['retrieval']), hit_at_3=sum(c['hit_at_3'] for c in raw['retrieval']),
            agent_automatic_passed=sum(c['automatic_passed'] for c in raw['agent']),
            browser={'passed': browser.get('passed', False), 'completed_turns': len(browser.get('turns', [])),
                     'errors': browser.get('errors', []), 'failure': browser.get('failure')})
    output = {
        'synthetic': True, 'real_openai_embeddings': True, 'real_pgvector': True, 'api_mocks': False,
        'retrieval_corpus': {'current_store_tables': 9, 'current_store_documents': 3, 'other_owners': 1, 'other_populated_stores': 2, 'empty_stores': 1},
        'unique_retrieval_questions': 20, 'retrieval_repetitions': 3,
        'retrieval_hit_at_1': sum(r['hit_at_1'] for r in runs), 'retrieval_attempts': sum(r['retrieval_count'] for r in runs),
        'live_agent_automatic_passed': sum(r['agent_automatic_passed'] for r in runs),
        'live_agent_attempts': sum(len(r['agent']) for r in runs),
        'final_browser_passed': runs[-1]['browser']['passed'],
        'review': 'Codex inspected representative RAG answers and both final streaming answers; automated assertions cover all retrieval rankings, tool use, values and mutation boundaries. No independent merchant reviewer.',
        'limits': ['Small fixed synthetic corpus; hit rate is not a production quality estimate.',
                   'No large-corpus/ANN performance, actual PG compatibility or merchant validation.',
                   'Query/turn usage is recorded; seed indexing embeddings are not included in those totals.',
                   'F disables the scheduler: browser verifies saved interval. Real background execution/restart evidence is in D.',
                   'Long answers, internal terms and unsupported follow-up suggestions still need UX work.'],
        'runs': runs,
    }
    destination = ROOT / 'docs/evaluations/rag-2026-09-08.json'
    destination.write_text(json.dumps(output, ensure_ascii=False, indent=2, default=str) + '\n', encoding='utf-8')
    shutil.copyfile(ARTIFACTS / RUNS[-1][0] / 'dashboard-metric.png', destination.with_name('rag-2026-09-08-dashboard.png'))
    print(json.dumps({k: v for k, v in output.items() if k != 'runs'}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
