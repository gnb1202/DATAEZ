"""Run transaction tests against a disposable local PostgreSQL instance."""
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import time
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]


def main():
    password = secrets.token_hex(24)
    container = None
    def command(args):
        result = subprocess.run(args,capture_output=True,text=True,encoding='utf-8',timeout=120)
        if result.returncode:
            raise RuntimeError(result.stderr.replace(password,'[redacted]')[-1500:])
        return result.stdout.strip()
    try:
        container = command(['docker','run','-d','--name','dataez-guards-'+uuid4().hex[:8],
            '--label','dataez.task=release-guards','--memory','512m','--tmpfs','/var/lib/postgresql/data:rw',
            '-p','127.0.0.1::5432','-e','POSTGRES_PASSWORD='+password,'pgvector/pgvector:pg16'])
        for _ in range(60):
            if subprocess.run(['docker','exec',container,'pg_isready','-U','postgres'],capture_output=True).returncode == 0: break
            time.sleep(.5)
        else: raise RuntimeError('Database did not become ready')
        port = command(['docker','port',container,'5432/tcp']).rsplit(':',1)[1]
        env = {**os.environ,'PYTHONIOENCODING':'utf-8',
               'DATAEZ_TEST_DATABASE_URL':f'postgresql://postgres:{password}@127.0.0.1:{port}/postgres'}
        tests = ['test_file_library.py','test_direct_uploads.py','test_maintenance.py',
                 'test_upload_sources.py','test_serverless_limits.py']
        result = subprocess.run([sys.executable,'-m','pytest',*[str(ROOT/'api/tests'/t) for t in tests],'-q'],
            env=env,cwd=ROOT,capture_output=True,text=True,encoding='utf-8',timeout=180)
        output = result.stdout.replace(password,'[redacted]')
        print(output)
        report = {'exit_code':result.returncode,'output':output,'database':'disposable local PostgreSQL'}
        destination = ROOT/'docs/evaluations/vercel-api/release-guards-local.json'
        destination.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        return result.returncode
    finally:
        if container:
            label = command(['docker','inspect',container,'--format','{{index .Config.Labels "dataez.task"}}'])
            if label != 'release-guards': raise RuntimeError('Not an owned test container')
            command(['docker','rm','-f','-v',container])


if __name__ == '__main__':
    raise SystemExit(main())
