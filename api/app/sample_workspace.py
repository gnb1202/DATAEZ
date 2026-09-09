"""Repeatable first-use data in a separate, explicitly synthetic store."""
from uuid import uuid4
from . import db
from .file_library import store_file, prepare_file

CSV = b"paid_at,amount,method\n2026-09-01,126500,card\n2026-09-01,38000,cash\n2026-09-02,214000,card\n2026-09-02,-24000,card\n2026-09-03,97300,card\n2026-09-03,42500,cash\n2026-09-04,168900,card\n2026-09-04,27000,cash\n"


def prepare_sample(user_id):
    with db._connect() as conn:
        conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", ('sample-workspace:'+user_id,))
        project = conn.execute('''SELECT p.* FROM sample_workspaces s JOIN projects p ON p.id=s.project_id
            WHERE s.user_id=%s AND p.user_id=%s AND p.deleted_at IS NULL''', (user_id,user_id)).fetchone()
        if not project:
            project = conn.execute('''INSERT INTO projects(id,user_id,name,description) VALUES(%s,%s,%s,%s) RETURNING *''',
                (str(uuid4()),user_id,'샘플 가게 · 모퉁이 카페','DATA:EZ 체험용 가상 거래입니다. 실제 매출이 아닙니다.')).fetchone()
            conn.execute('''INSERT INTO sample_workspaces(user_id,project_id) VALUES(%s,%s)
                ON CONFLICT(user_id) DO UPDATE SET project_id=EXCLUDED.project_id''', (user_id,project['id']))
    # Public file services retain originals and make retries after partial setup
    # idempotent. Never clear a user's existing store, ledger or widgets.
    pid = str(project['id'])
    file = store_file(user_id,pid,'샘플_카페_매출.csv',CSV)
    file = prepare_file(user_id,file['file_id'],pid)
    return {'project':{k:v for k,v in project.items() if k not in ('deleted_at','user_id')},'file':file,
            'notice':'샘플 가게의 가상 거래 8행입니다. 실제 매출과 구분해 사용하세요.'}
