"""Run real demo acceptance, keeping its synthetic account and data for inspection."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import run


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live-llm', action='store_true', help='Authorize a real model question and indexing costs')
    parser.add_argument('--resume', type=Path, help='Retry the restart/browser checks of a completed initial phase, without another model question')
    args = parser.parse_args()
    if not args.live_llm:
        parser.error('Use --live-llm; this check calls the configured model and restarts only the isolated demo.')
    run.resources('container')
    config = json.loads((run.STATE / 'settings.json').read_text(encoding='utf-8'))
    run.wait_ready(config)
    out = args.resume.resolve() if args.resume else run.STATE / ('acceptance-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'))
    if args.resume:
        if not out.is_relative_to(run.STATE.resolve()) or not json.loads((out/'report-initial.json').read_text(encoding='utf-8'))['passed']:
            raise RuntimeError('Resume requires a passed initial phase in this demo evidence directory.')
    else:
        out.mkdir()
    node = shutil.which('node')
    if not node:
        raise RuntimeError('Install Node.js and run npm ci in scripts/ui-eval for Playwright.')
    command = [node, str(Path(__file__).with_suffix('.cjs'))]
    urls = [f"http://localhost:{config['web_port']}", f"http://localhost:{config['api_port']}"]
    env = {**os.environ, 'PYTHONUTF8':'1'}
    report_path = out / 'report.json'
    report_path.write_text(json.dumps({'passed':False, 'status':'running'}), encoding='utf-8')
    try:
        for phase in (('resumed',) if args.resume else ('initial','resumed')):
            if phase == 'resumed':
                subprocess.run([sys.executable, str(Path(run.__file__)), 'stop'], check=True, env=env)
                subprocess.run([sys.executable, str(Path(run.__file__)), 'start','--no-build'], check=True, env=env)
            subprocess.run([*command, phase, str(out), *urls], check=True, env=env)
    except subprocess.CalledProcessError:
        report_path.write_text(json.dumps({'passed':False, 'status':'failed', 'phase':phase}), encoding='utf-8')
        raise
    reports = [json.loads((out / f'report-{phase}.json').read_text(encoding='utf-8')) for phase in ('initial','resumed')]
    model = json.loads(run.docker(*run.compose_args(), 'config','--format','json',env=run.compose_env(config),quiet=True))['services']['api']['environment']
    sources = ['api/app/sample_workspace.py','api/app/library_routes.py','api/app/library_schema.py',
        'web/components/dashboard/sample-workspace-actions.tsx','web/components/dashboard/sections/dashboard-section.tsx',
        'web/components/dashboard/getting-started.tsx','web/components/dashboard/file-library.tsx',
        'web/components/dashboard/chat-dock.tsx','web/app/components/chat-panel.tsx','web/app/hooks/use-workspace-analysis.ts',
        'web/app/dashboard/page.tsx','web/Dockerfile','docker-compose.yml','scripts/demo/run.py','scripts/demo/verify.cjs']
    evidence = {'passed':all(r['passed'] for r in reports), 'status':'passed', 'run_id':out.name,
        'checked_at':datetime.now(timezone.utc).isoformat(), 'live_llm_questions':1,
        'api_mocks':False, 'models':{key:model[key] for key in ('OPENAI_MODEL','OPENAI_ORCHESTRATOR_MODEL','OPENAI_EMBEDDING_MODEL')},
        'services_stopped_and_started':True, 'checks':[c for r in reports for c in r['checks']],
        'source_sha256':{name:hashlib.sha256((run.ROOT/name).read_bytes()).hexdigest() for name in sources}}
    report_path.write_text(json.dumps(evidence, indent=2), encoding='utf-8')
    print(f'Acceptance passed. Private evidence and demo login: {out}')


if __name__ == '__main__':
    main()
