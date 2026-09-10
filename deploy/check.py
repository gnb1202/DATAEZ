"""Check rendered production Compose config without printing credentials."""
import argparse
import json
import ipaddress
from pathlib import Path
import re
import subprocess
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]


def compose(env_file, project='dataez-public'):
    return ['docker','compose','--project-directory',str(ROOT),
            '--env-file',str(Path(env_file).resolve()),'-p',project,
            '-f',str(ROOT/'docker-compose.yml'),'-f',str(ROOT/'deploy/compose.public.yaml')]


def check(env_file, *, local=False, project='dataez-public'):
    result = subprocess.run(compose(env_file,project)+['config','--format','json'],capture_output=True,text=True,encoding='utf-8')
    if result.returncode:
        # Compose errors may interpolate credentials. Keep raw output private.
        raise ValueError('Compose configuration failed; check required variables and Compose >= 2.24.4')
    config=json.loads(result.stdout); services=config['services']
    api,web,proxy=services['api'],services['web'],services['proxy']
    env=api['environment']; origin=web['build']['args']['NEXT_PUBLIC_API_URL']
    parsed=urlsplit(origin);host=proxy['environment']['PUBLIC_HOST']
    if parsed.scheme!='https' or parsed.hostname!=host or parsed.path or parsed.query or parsed.fragment or parsed.username or parsed.password:
        raise ValueError('PUBLIC_ORIGIN must be an HTTPS origin matching PUBLIC_HOST, without a path')
    if len(host)>253 or not all(re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?',label) for label in host.split('.')):
        raise ValueError('PUBLIC_HOST must be a DNS hostname')
    try:
        ipaddress.ip_address(host);is_ip=True
    except ValueError:
        is_ip=False
    reserved={'localhost','example.com','example.net','example.org'}
    if not local and (is_ip or host in reserved or host.endswith(('.localhost','.test','.invalid','.local','.example','.example.com','.example.net','.example.org')) or '.' not in host or parsed.port not in (None,443)):
        raise ValueError('Choose the real public DNS hostname and standard HTTPS port')
    if env['APP_ENV']!='production' or env['ALLOWED_ORIGINS']!=origin or web['build']['args']['NEXT_PUBLIC_SITE_URL']!=origin:
        raise ValueError('API, CORS and share metadata must use the production origin')
    if any(services[k].get('ports') for k in ('db','api','web')):
        raise ValueError('Only the proxy may publish ports')
    if not local and {str(p['published']) for p in proxy['ports']}!={'80','443'}:
        raise ValueError('Public HTTP/HTTPS ports must be 80/443')
    secret=env['JWT_SECRET_KEY'];password=services['db']['environment']['POSTGRES_PASSWORD']
    if len(secret)<32 or any(s in secret.lower() for s in ('dev','insecure','change-this','your-secret')):
        raise ValueError('Generate a production JWT secret of at least 32 characters')
    if len(password)<24 or not re.fullmatch(r'[A-Za-z0-9_-]+',password):
        raise ValueError('Generate a URL-safe database password of at least 24 characters')
    if env['OPENAI_API_KEY'] in ('','sk-...'):
        raise ValueError('A server-side model key is required')
    if not any(v.get('target')=='/data/uploads' and v['type']=='volume' for v in api['volumes']):
        raise ValueError('Uploads must have a persistent volume')
    return {'origin':origin,'services':list(services),'public_ports':[p['published'] for p in proxy['ports']],
            'app_environment':env['APP_ENV'],'api_public':False,'database_public':False,'persistent_uploads':True}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--env-file',type=Path,default=ROOT/'.env.public')
    parser.add_argument('--local-test',action='store_true')
    args=parser.parse_args()
    print(json.dumps(check(args.env_file,local=args.local_test),ensure_ascii=False,indent=2))
