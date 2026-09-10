"""Two paid-model smoke questions against real API/local PostgreSQL. Explicit --live-llm required."""
import argparse
from decimal import Decimal
import json
import logging
import os
from pathlib import Path
import secrets
import sys
from uuid import uuid4

from dotenv import dotenv_values
import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live-llm', action='store_true')
    args = parser.parse_args()
    if not args.live_llm:
        parser.error('--live-llm explicitly enables configured paid model calls')
    admin = os.environ['DATAEZ_TEST_DATABASE_URL']
    config = conninfo_to_dict(admin)
    if config.get('host') not in {'127.0.0.1','localhost','::1'} or config.get('hostaddr'):
        raise ValueError('Use a loopback test database')
    local = dotenv_values(ROOT/'.env')
    for key in ('OPENAI_API_KEY','OPENAI_MODEL','OPENAI_ORCHESTRATOR_MODEL'):
        if local.get(key) and not os.environ.get(key):
            os.environ[key] = local[key]
    if not os.environ.get('OPENAI_API_KEY'):
        raise ValueError('Configured model key is required')
    name = 'dataez_library_live_' + uuid4().hex
    output = ROOT/'scripts/ui-eval/artifacts/library-live'/name
    output.mkdir(parents=True)
    os.environ.update(DATABASE_URL=make_conninfo(admin,dbname=name), JWT_SECRET_KEY=secrets.token_hex(32),
        APP_ENV='development',RAG_ENABLED='false',INDEX_WORKER_ENABLED='false',STORAGE_BACKEND='local',
        LOCAL_STORAGE_PATH=str(output/'uploads'),METRIC_SCHEDULER_ENABLED='false',IMPORT_CLEANUP_ENABLED='false',
        UPLOAD_RATE_LIMIT_PER_MINUTE='100',QUERY_RATE_LIMIT_PER_MINUTE='100')
    sys.path.insert(0,str(ROOT/'api'))
    from fastapi.testclient import TestClient
    from app.main import app
    from app import db
    from app.config import settings
    logging.basicConfig(filename=output/'api.log',level=logging.INFO,encoding='utf-8')
    for handler in logging.getLogger().handlers[:]:
        logging.getLogger().removeHandler(handler)
    logging.basicConfig(filename=output/"api.log",level=logging.INFO,encoding="utf-8",force=True)
    report = {'passed':False,'real_postgres':True,'real_models':True,'api_transport':'FastAPI TestClient',
              'real_embeddings':False,'browser_evaluated':False,'worker_model':settings.openai_model,'turns':[]}
    created = False
    try:
        with psycopg.connect(admin,autocommit=True) as conn:
            conn.execute(sql.SQL("CREATE DATABASE {} TEMPLATE template0 ENCODING 'UTF8'").format(sql.Identifier(name)))
        created = True
        with psycopg.connect(os.environ['DATABASE_URL']) as conn:
            conn.execute((ROOT/'db/init.sql').read_text(encoding='utf-8'))
        with TestClient(app) as client:
            def request(method,path,**kwargs):
                response = client.request(method,path,**kwargs)
                if response.status_code >= 400:
                    raise AssertionError(f'{method} {path}: {response.status_code}: {response.text[:250]}')
                return response
            auth = request('POST','/api/auth/signup',json={'name':'Library test','email':name+'@example.test','password':secrets.token_urlsafe(25)+'A1!'}).json()
            client.headers['Authorization'] = 'Bearer '+auth['access_token']
            store = request('POST','/api/projects',json={'name':'성수점','description':'합성 파일 검증용'}).json()['id']
            csv = b'paid_at,amount\n2026-09-01,100.01\n2026-09-02,200.02\n'
            stored = request('POST','/api/library/files',data={'project_id':store},files={'file':('카드매출.csv',csv)}).json()
            ready = request('POST',f"/api/library/files/{stored['file_id']}/prepare",json={'project_id':store}).json()
            request('POST',f"/api/projects/{store}/tables/import",data={'table_name':'선택하지 않은 장부'},files={'file':('outside.csv',b'paid_at,amount\n2026-09-01,9000.00\n')})
            conversation = request('POST','/api/conversations',json={'project_id':store}).json()['conversation_id']
            discovery = request('POST',f'/api/conversations/{conversation}/messages',data={'message':'보관함에서 카드매출 파일을 찾아줘. 파일 후보만 알려주고 아직 분석하거나 가져오지 마.'}).json()
            report['turns'].append({'case':'discovery',**discovery})
            candidates = [s for s in discovery['steps'] if s.get('tool_name')=='search_library_files']
            assert candidates and any(f['file_id']==stored['file_id'] for s in candidates for f in s.get('tool_output',{}).get('files',[]))
            assert not any(s.get('tool_name')=='import_file' for s in discovery['steps'])
            pick = [{'file_id':stored['file_id'],'table_id':ready['bindings'][0]['table_id']}]
            response = request('POST',f'/api/conversations/{conversation}/messages/stream',data={
                'message':'선택한 파일에 연결된 장부만 사용해서 2026년 9월의 일별 amount 합계 막대그래프를 미리보기로 보여줘. paid_at 날짜 기준이며 대시보드 저장은 하지 마.',
                'library_selections':json.dumps(pick),'library_scope_confirmed':'true'})
            frames = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith('data: ')]
            result = next(frame['data'] for frame in frames if frame['type']=='done')
            report['turns'].append({'case':'scoped_chart',**result})
            charts = result['charts']
            assert charts, 'Agent produced no chart'
            assert any(sum(Decimal(str(row[c['y_key']])) for row in c['data'])==Decimal('300.03') for c in charts)
            assert result['steps'][0]['tool_output']['files'][0]['file_id'] == stored['file_id']
            history = request('GET',f'/api/conversations/{conversation}/messages').json()['messages']
            assert history[-2]['steps'][0]['tool_output']['files'][0]['file_id'] == stored['file_id']
            assert request('GET',f'/api/projects/{store}/tables').json()['tables'][0]['row_count'] in (1,2)
            assert len(request('GET',f'/api/projects/{store}/tables').json()['tables']) == 2
            second_store = request('POST','/api/projects',json={'name':'연남점'}).json()['id']
            external = request('POST','/api/library/files',data={'project_id':second_store},files={'file':('연남점.csv',b'amount\n123.45\n')}).json()
            external = request('POST',f"/api/library/files/{external['file_id']}/prepare",json={'project_id':second_store}).json()
            external_pick = [{'file_id':external['file_id'],'table_id':external['bindings'][0]['table_id'],'include_other_store':True}]
            external_result = request('POST',f'/api/conversations/{conversation}/messages',data={
                'message':'이번에 선택한 연남점 파일의 amount 전체 합계를 조회해서 표로 보여줘. 다른 장부는 포함하지 마.',
                'library_selections':json.dumps(external_pick),'library_scope_confirmed':'true'}).json()
            report['turns'].append({'case':'external_store_only',**external_result})
            assert any(Decimal(str(value)) == Decimal('123.45') for row in external_result['table_data'] for value in row.values())
            report['passed'] = True
    finally:
        db.close_pool()
        (output/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
        if created:
            assert name.startswith('dataez_library_live_') and len(name)==len('dataez_library_live_')+32
            with psycopg.connect(admin,autocommit=True) as conn:
                conn.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(name)))
        print(json.dumps({'passed':report['passed'],'turns':len(report['turns']),'report':str(output/'report.json')},ensure_ascii=False))


if __name__ == '__main__':
    main()
