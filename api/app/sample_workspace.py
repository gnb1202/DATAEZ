"""Repeatable first-use data in a separate, explicitly synthetic store."""
from uuid import uuid4
from datetime import datetime
from zoneinfo import ZoneInfo
from fastapi import HTTPException
from . import db
from .file_library import store_file, prepare_file

CSV = b"paid_at,amount,method\n2026-09-01,126500,card\n2026-09-01,38000,cash\n2026-09-02,214000,card\n2026-09-02,-24000,card\n2026-09-03,97300,card\n2026-09-03,42500,cash\n2026-09-04,168900,card\n2026-09-04,27000,cash\n"


def current_sample(user_id):
    with db._connect() as conn:
        row = _current(conn, user_id)
    return {'project': _public_project(row) if row else None}


def _public_project(project):
    return {k:v for k,v in project.items() if k not in ('deleted_at','user_id')}


def _current(conn, user_id):
    return conn.execute('''SELECT p.* FROM sample_workspaces s JOIN projects p ON p.id=s.project_id
        WHERE s.user_id=%s AND p.user_id=%s AND p.deleted_at IS NULL''', (user_id,user_id)).fetchone()


def _create(conn, user_id, *, restarted=False):
    suffix = datetime.now(ZoneInfo('Asia/Seoul')).strftime(' · %m/%d %H:%M') if restarted else ''
    project = conn.execute('''INSERT INTO projects(id,user_id,name,description) VALUES(%s,%s,%s,%s) RETURNING *''',
        (str(uuid4()),user_id,'샘플 가게 · 모퉁이 카페'+suffix,'DATA:EZ 체험용 가상 거래입니다. 실제 매출이 아닙니다.')).fetchone()
    conn.execute('''INSERT INTO sample_workspaces(user_id,project_id) VALUES(%s,%s)
        ON CONFLICT(user_id) DO UPDATE SET project_id=EXCLUDED.project_id''', (user_id,project['id']))
    return project


def prepare_sample(user_id):
    with db._connect() as conn:
        conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", ('sample-workspace:'+user_id,))
        project = _current(conn, user_id)
        if not project:
            project = _create(conn, user_id)
    return _prepare(user_id, project)


def restart_sample(user_id, expected_project_id, request_id):
    with db._connect() as conn:
        conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", ('sample-workspace:'+user_id,))
        previous = conn.execute('''SELECT * FROM sample_workspace_restarts
            WHERE user_id=%s AND request_id=%s''', (user_id,request_id)).fetchone()
        if previous:
            if str(previous['previous_project_id']) != expected_project_id:
                raise HTTPException(409, '같은 재시작 요청의 대상이 달라졌습니다.')
            project = conn.execute('SELECT * FROM projects WHERE id=%s AND user_id=%s AND deleted_at IS NULL',
                (previous['project_id'],user_id)).fetchone()
            if not project:
                raise HTTPException(410, '이 요청으로 만든 샘플 가게가 삭제되었습니다. 현재 샘플을 다시 확인해주세요.')
        else:
            current = _current(conn, user_id)
            if not current or str(current['id']) != expected_project_id:
                raise HTTPException(409, '현재 샘플 가게가 변경되었습니다. 새로고침 후 다시 확인해주세요.')
            project = _create(conn, user_id, restarted=True)
            conn.execute('''INSERT INTO sample_workspace_restarts(user_id,request_id,previous_project_id,project_id)
                VALUES(%s,%s,%s,%s)''', (user_id,request_id,expected_project_id,project['id']))
    # Mapping and retry key commit together; failed file preparation can resume.
    return _prepare(user_id, project)


def _prepare(user_id, project):
    # Public file services retain originals and make retries after partial setup
    # idempotent. Never clear a user's existing store, ledger or widgets.
    pid = str(project['id'])
    file = store_file(user_id,pid,'샘플_카페_매출.csv',CSV)
    file = prepare_file(user_id,file['file_id'],pid)
    return {'project':_public_project(project),'file':file,
            'notice':'샘플 가게의 가상 거래 8행입니다. 실제 매출과 구분해 사용하세요.'}


def prepare_dashboard(user_id, project_id):
    from .file_snapshots import original_table
    from .dashboard_metrics import CreateMetricRequest, create_saved_metric
    with db._connect() as conn:
        project = _current(conn, user_id)
        if not project or str(project['id']) != project_id:
            raise HTTPException(409, '현재 샘플 가게에서만 예시 지표를 준비할 수 있습니다.')
    sample = _prepare(user_id, project)
    table = original_table(user_id, sample['file']['file_id'], project_id)
    base = {'table_id':str(table['id']), 'column':'amount', 'unit':'KRW', 'time_range':'all'}
    examples = [
        ('total', '샘플 예시 · 전체 결제액', {}),
        ('daily', '샘플 예시 · 일별 결제액', {'group_by':'paid_at', 'date_grain':'day', 'chart_type':'line'}),
        ('method', '샘플 예시 · 결제수단별 비교', {'group_by':'method', 'chart_type':'bar'}),
    ]
    sample['widgets'] = [create_saved_metric(project_id, user_id, CreateMetricRequest(
        title=title, definition={**base, **options}, save_key='sample:v1:'+key)) for key,title,options in examples]
    sample['notice'] = '미리 정의한 예시 지표 3개입니다. LLM이 생성한 결과가 아닙니다. 원본 파일 전체 기간을 수동 재계산합니다.'
    return sample
