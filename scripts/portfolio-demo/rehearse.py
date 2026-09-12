"""Run one real public rehearsal. Use --new-take after a completed/failed take.

Private credentials/checkpoints remain in .local-test. A take is never silently
replayed: uncertain append outcomes require inspection, not automatic retry.
"""
import argparse
import json
import subprocess
from pathlib import Path

import httpx
from prepare import ROOT, STATE, LOCAL, API, login, request, new_take, summarize


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--new-take', action='store_true')
    args = parser.parse_args()
    state = json.loads(STATE.read_text(encoding='utf-8'))
    with httpx.Client(base_url=API, timeout=90) as client:
        login(client, state)
        if args.new_take:
            new_take(client, state)
        take = state['recording']
        out = LOCAL / 'takes' / take['project_id']
        assert not out.exists(), 'Take already attempted; inspect it, then use --new-take'
        ledger = request(client, 'GET', f"/api/projects/{take['project_id']}/tables/{take['table_id']}/data")
        expected = json.loads((ROOT/'samples/demo/expected.json').read_text(encoding='utf-8'))
        assert ledger['total_count'] == 8 and summarize(ledger['rows'])['total'] == expected['original_total']
        assert not request(client, 'GET', '/api/dashboard/widgets', params={'project_id': take['project_id']})['widgets']
        out.mkdir(parents=True)
        payload = {**state, 'token': client.headers['Authorization'][7:], 'out': str(out)}
        run = subprocess.run(['node', str(ROOT/'scripts/portfolio-demo/rehearse.cjs')],
                             input=json.dumps(payload), text=True, encoding='utf-8', cwd=ROOT)
        raise SystemExit(run.returncode)


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print('Rehearsal preparation stopped: '+(str(exc) if isinstance(exc, AssertionError) else type(exc).__name__))
        raise SystemExit(1)
