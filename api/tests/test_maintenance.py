from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from uuid import uuid4
import subprocess

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from .test_file_library import live  # noqa: F401
from app import maintenance as runner
from app.config import settings, Settings
from app.maintenance_schema import DDL


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(settings, 'maintenance_enabled', True)
    monkeypatch.setattr(settings, 'maintenance_secret', 'a'*40)
    app=FastAPI(); app.include_router(runner.router)
    return TestClient(app)


def test_authentication_precedes_work(client, monkeypatch):
    monkeypatch.setattr(runner, 'claim', lambda kind: pytest.fail('Unauthorized work attempted'))
    for headers in ({}, {'Authorization':'Bearer user-jwt'}, {'Authorization':'Bearer '}):
        assert client.post('/api/internal/maintenance/index',headers=headers).status_code==401
        assert client.get('/api/internal/maintenance/status',headers=headers).status_code==401
    monkeypatch.setattr(settings,'maintenance_enabled',False)
    assert client.post('/api/internal/maintenance/index').status_code==503


def test_disabled_by_default_and_key_required():
    assert not Settings().maintenance_enabled
    with pytest.raises(ValueError):
        Settings(maintenance_enabled=True,maintenance_secret='short')


@pytest.mark.parametrize('failure,code,state',[(subprocess.TimeoutExpired('worker',120),504,'timeout'),(RuntimeError('secret must not escape'),503,'failed')])
def test_failure_redacted_and_lease_finished(client,monkeypatch,failure,code,state):
    token=uuid4(); finished=[]
    monkeypatch.setattr(runner,'claim',lambda kind:token)
    def fail(kind):raise failure
    monkeypatch.setattr(runner,'run_child',fail)
    monkeypatch.setattr(runner,'finish',lambda *args:finished.append(args))
    response=client.post('/api/internal/maintenance/index',headers={'Authorization':'Bearer '+'a'*40})
    assert response.status_code==code and response.json()['status']==state
    assert 'secret' not in response.text and finished==[('index',token,state,0)]


def test_busy_does_not_spawn(client,monkeypatch):
    monkeypatch.setattr(runner,'claim',lambda kind:None)
    monkeypatch.setattr(runner,'run_child',lambda kind:pytest.fail('duplicate work'))
    response=client.post('/api/internal/maintenance/index',headers={'Authorization':'Bearer '+'a'*40})
    assert response.json()['status']=='busy'


def test_child_configuration_and_invalid_output(monkeypatch):
    seen=[]
    def child(command,**kwargs):
        seen.append((command,kwargs))
        return SimpleNamespace(returncode=0,stdout=b'{"processed":3}')
    monkeypatch.setattr(subprocess,'run',child)
    assert runner.run_child('index')==3
    command,options=seen[0]
    assert command[-2:]==['app.maintenance_worker','index']
    assert options['timeout']==120 and options['env']['DB_POOL_MAX_SIZE']=='1'
    assert settings.openai_api_key not in command and options['stderr']==subprocess.DEVNULL
    monkeypatch.setattr(subprocess,'run',lambda *a,**kw:SimpleNamespace(returncode=0,stdout=b'{"processed":true}'))
    with pytest.raises(RuntimeError):runner.run_child('index')


def test_real_database_lease_claim_and_stale_finish(live):
    with live.connect() as conn:conn.execute(DDL)
    with ThreadPoolExecutor(max_workers=4) as pool:
        claims=list(pool.map(lambda _:runner.claim('index'),range(4)))
    tokens=[t for t in claims if t]
    assert len(tokens)==1
    first=tokens[0]
    with live.connect() as conn:
        conn.execute("UPDATE maintenance_runs SET lease_until=now()-interval '1 second' WHERE kind='index'")
    second=runner.claim('index');assert second and second!=first
    runner.finish('index',first,'succeeded',9)
    with live.connect() as conn:
        row=conn.execute("SELECT * FROM maintenance_runs WHERE kind='index'").fetchone()
        assert row['lease_token']==second and row['status']=='running'
    runner.finish('index',second,'succeeded',1)
    assert runner.claim('index') is None  # cooldown absorbs duplicate cron delivery
    assert runner.claim('metrics') is not None
