"""Persistent local demo. Python 3.10+ stdlib and Docker Compose v2 only.

start/status/stop/restart never remove containers, volumes, or user data.
Secrets remain in ignored local settings and Docker's private configuration.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import time
from urllib.error import URLError
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[2]
STATE = ROOT / '.local-test' / 'demo'
OWNER = ROOT.as_posix()
PROJECT = 'dataez-demo-' + hashlib.sha256(OWNER.lower().encode()).hexdigest()[:8]
LABEL = 'dataez.demo.workspace'


def docker(*args, env=None, quiet=False, timeout=60):
    try:
        result = subprocess.run(['docker', *args], cwd=ROOT, env=env, text=True,
                                encoding='utf-8', errors='replace', capture_output=True, timeout=timeout)
    except FileNotFoundError:
        raise RuntimeError('Docker Desktop and Docker Compose v2 are required.') from None
    except subprocess.TimeoutExpired:
        raise RuntimeError('Docker did not respond in time. Check Docker Desktop and run status.') from None
    if result.returncode:
        # Compose config errors can include interpolated secrets. Do not echo them.
        if quiet and 'config' in args and 'OPENAI_API_KEY' in result.stderr:
            raise RuntimeError('Set OPENAI_API_KEY in the root .env or process environment before starting.')
        message = 'Docker command failed. Check Docker Desktop.' if quiet else result.stderr.strip()
        raise RuntimeError(message)
    return result.stdout.strip()


def resources(kind):
    args = ['ps', '-aq'] if kind == 'container' else ['volume', 'ls', '-q']
    ids = docker(*args, '--filter', f'label=com.docker.compose.project={PROJECT}').splitlines()
    if not ids:
        return []
    rows = json.loads(docker(kind, 'inspect', *ids, quiet=True))
    for row in rows:
        labels = row.get('Config', {}).get('Labels') if kind == 'container' else row.get('Labels')
        if (labels or {}).get(LABEL) != OWNER:
            raise RuntimeError(f'{PROJECT}: unrecognized {kind}; refusing to manage it.')
    return rows


def settings(args):
    path = STATE / 'settings.json'
    if path.exists():
        result = json.loads(path.read_text(encoding='utf-8'))
    else:
        STATE.mkdir(parents=True, exist_ok=True)
        result = {'web_port': args.web_port or 3000, 'api_port': args.api_port or 8000,
                  'postgres_password': secrets.token_hex(24), 'jwt_secret': secrets.token_hex(32)}
        # Exclusive creation: never regenerate a password for an existing volume.
        with path.open('x', encoding='utf-8') as stream:
            json.dump(result, stream, indent=2)
        path.chmod(0o600)
    for key in ('web_port', 'api_port'):
        supplied = getattr(args, key)
        if supplied and supplied != result[key]:
            raise RuntimeError(f'{key} is already fixed in {path}. Stop the demo before editing it.')
    if result['web_port'] == result['api_port']:
        raise RuntimeError('Web and API ports must differ. Update the local settings file.')
    return result


def compose_env(config):
    values = {
        'POSTGRES_USER': 'dataez', 'POSTGRES_DB': 'dataez',
        'POSTGRES_PASSWORD': config['postgres_password'], 'JWT_SECRET_KEY': config['jwt_secret'],
        'APP_ENV': 'development', 'STORAGE_BACKEND': 'local', 'LOCAL_STORAGE_PATH': '/data/uploads',
        'WEB_BIND': '127.0.0.1', 'API_BIND': '127.0.0.1',
        'WEB_PORT': str(config['web_port']), 'API_PORT': str(config['api_port']),
        'NEXT_PUBLIC_API_URL': f"http://localhost:{config['api_port']}",
        'ALLOWED_ORIGINS': f"http://localhost:{config['web_port']}",
        'DATAEZ_DEMO_WORKSPACE': OWNER,
    }
    # Explicit env overrides root .env settings for this isolated local stack.
    return {**os.environ, **values}


def compose_args():
    args = ['compose', '--project-name', PROJECT]
    if (ROOT / '.env').exists():
        args += ['--env-file', str(ROOT / '.env')]
    else:
        args += ['--env-file', str(ROOT / '.env.example')]
    return [*args, '-f', str(ROOT / 'docker-compose.yml'), '-f', str(ROOT / 'scripts/demo/compose.yaml')]


def preflight(config, env, containers):
    model = json.loads(docker(*compose_args(), 'config', '--format', 'json', env=env, quiet=True))
    key = model['services']['api']['environment'].get('OPENAI_API_KEY', '')
    if not key or key.lower().startswith(('your-', 'sk-...', 'sk-your', 'sk-xxx')):
        raise RuntimeError('Set OPENAI_API_KEY in the root .env or process environment before starting.')
    owned_ports = {int(port['HostPort']) for row in containers if row['State']['Running']
                   for bindings in row['NetworkSettings'].get('Ports', {}).values() if bindings for port in bindings}
    for port in (config['web_port'], config['api_port']):
        if port in owned_ports:
            continue
        with socket.socket() as probe:
            try:
                probe.bind(('127.0.0.1', port))
            except OSError:
                raise RuntimeError(f'Port {port} is in use. Stop its owner or choose demo ports in {STATE / "settings.json"}.') from None


def request_ok(url, *, database=False):
    try:
        with urlopen(url, timeout=3) as response:
            return response.status == 200 and (not database or json.load(response).get('checks', {}).get('database') == 'ok')
    except (URLError, OSError, ValueError):
        return False


def wait_ready(config):
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        if request_ok(f"http://localhost:{config['api_port']}/ready", database=True) and request_ok(f"http://localhost:{config['web_port']}"):
            print(f"Ready: http://localhost:{config['web_port']} (create an account or log in)")
            print(f"API/DB readiness: http://localhost:{config['api_port']}/ready")
            return
        time.sleep(2)
    raise RuntimeError('Web/API/DB did not become ready within 180s. Run status and inspect this demo in Docker Desktop. Data is retained.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['start', 'status', 'stop', 'restart'])
    parser.add_argument('--web-port', type=int, choices=range(1024, 65536), metavar='PORT')
    parser.add_argument('--api-port', type=int, choices=range(1024, 65536), metavar='PORT')
    parser.add_argument('--no-build', action='store_true', help='Use existing images for start/restart')
    args = parser.parse_args()
    docker('info', '--format', '{{.ServerVersion}}', quiet=True)
    containers = resources('container')
    volumes = resources('volume')
    print(f'Demo: {PROJECT}', flush=True)
    if args.action == 'status':
        for row in containers:
            print(row['Name'].lstrip('/'), row['State']['Status'], row['State'].get('Health', {}).get('Status', ''))
        print(f'{len(containers)} containers; {len(volumes)} persistent volumes. Settings: {STATE / "settings.json"}')
        if (STATE / 'settings.json').exists():
            config = json.loads((STATE / 'settings.json').read_text(encoding='utf-8'))
            web_url = f"http://localhost:{config['web_port']}"
            print(f"Web: {web_url} ({'ready' if request_ok(web_url) else 'unavailable'})")
            print('API/DB:', 'ready' if request_ok(f"http://localhost:{config['api_port']}/ready", database=True) else 'unavailable')
        return
    if args.action == 'stop':
        ids = [row['Id'] for row in containers if row['State']['Running']]
        if ids:
            docker('stop', *ids, timeout=90)
        print('Stopped. Database and original files are retained.')
        return
    if volumes and not (STATE / 'settings.json').exists():
        raise RuntimeError('Existing demo volumes require their original settings.json. Restore it before starting.')
    config = settings(args)
    env = compose_env(config)
    preflight(config, env, containers)
    if args.action == 'restart':
        ids = [row['Id'] for row in containers if row['State']['Running']]
        if ids:
            docker('stop', *ids, timeout=90)
    command = ['docker', *compose_args(), 'up', '-d']
    if not args.no_build:
        command.append('--build')
    print('Starting web, API, PostgreSQL. The first image build may take several minutes.', flush=True)
    # Normal build logs do not include model keys or resolved Compose settings.
    result = subprocess.run(command, cwd=ROOT, env=env)
    if result.returncode:
        raise RuntimeError('Demo startup failed. Existing data is retained; fix the error and run start again.')
    wait_ready(config)


if __name__ == '__main__':
    try:
        main()
    except (RuntimeError, ValueError, KeyError) as error:
        print(f'Demo error: {error}', file=sys.stderr)
        sys.exit(1)
