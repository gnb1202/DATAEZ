"""Reject common deployment mistakes using the actual Compose merge."""
import json
from pathlib import Path
import subprocess

import pytest
from check import check,compose


def settings(tmp_path,**overrides):
    data={'PUBLIC_HOST':'demo.dataez-check.net','PUBLIC_ORIGIN':'https://demo.dataez-check.net',
          'POSTGRES_PASSWORD':'a'*64,'JWT_SECRET_KEY':'b'*64,'OPENAI_API_KEY':'test-not-a-real-key'}
    data.update(overrides);path=tmp_path/'settings.env'
    path.write_text('\n'.join(k+'='+v for k,v in data.items())+'\n',encoding='utf-8')
    return path


def test_public_merge_does_not_leave_local_ports_or_development_settings(tmp_path):
    path=settings(tmp_path,APP_ENV='development',API_BIND='0.0.0.0',API_PORT='9000',NEXT_PUBLIC_API_URL='http://localhost:8000',ALLOWED_ORIGINS='*')
    result=check(path)
    assert result['public_ports']==['80','443'] and result['app_environment']=='production'
    rendered=json.loads(subprocess.check_output(compose(path)+['config','--format','json'],text=True,encoding='utf-8'))
    assert not any(rendered['services'][name].get('ports') for name in ('api','db','web'))
    assert rendered['services']['web']['build']['args']['NEXT_PUBLIC_API_URL']==result['origin']
    assert rendered['services']['api']['environment']['ALLOWED_ORIGINS']==result['origin']


@pytest.mark.parametrize('overrides',[
    {'PUBLIC_ORIGIN':'http://demo.dataez-check.net'},
    {'PUBLIC_ORIGIN':'https://somewhere-else.net'},
    {'PUBLIC_ORIGIN':'https://demo.dataez-check.net/api'},
    {'PUBLIC_HOST':'203.0.113.10','PUBLIC_ORIGIN':'https://203.0.113.10'},
    {'PUBLIC_HOST':'localhost','PUBLIC_ORIGIN':'https://localhost'},
    {'PUBLIC_HOST':'demo.example.com','PUBLIC_ORIGIN':'https://demo.example.com'},
    {'PUBLIC_HOST':'bad..net','PUBLIC_ORIGIN':'https://bad..net'},
    {'PUBLIC_HOST':'demo.invalid','PUBLIC_ORIGIN':'https://demo.invalid'},
    {'JWT_SECRET_KEY':'dev-insecure-local-jwt-secret-do-not-deploy'},
    {'POSTGRES_PASSWORD':'unsafe@password:contains/slashes'},
    {'PUBLIC_HTTPS_PORT':'8443'},
])
def test_invalid_public_configuration_fails_closed(tmp_path,overrides):
    with pytest.raises(ValueError):check(settings(tmp_path,**overrides))
