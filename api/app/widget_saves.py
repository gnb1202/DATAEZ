"""Idempotent dashboard saves, scoped to one owner/store/source result."""
import hashlib
import json
from fastapi import HTTPException

DDL = """
ALTER TABLE dashboard_widgets ADD COLUMN IF NOT EXISTS save_key TEXT;
ALTER TABLE dashboard_widgets ADD COLUMN IF NOT EXISTS save_fingerprint CHAR(64);
CREATE UNIQUE INDEX IF NOT EXISTS uq_widget_save_key ON dashboard_widgets(user_id,project_id,save_key)
    WHERE save_key IS NOT NULL;
"""


def ensure_widget_saves():
    from .db import _connect
    with _connect() as conn:
        conn.execute("SELECT pg_advisory_xact_lock(hashtext('dataez-widget-saves'))")
        conn.execute(DDL)


def fingerprint(payload):
    # Adding an optional v1 unit must not invalidate keys issued before that
    # field existed. All other definition fields retain their prior encoding.
    def compatible(node):
        if isinstance(node,list): return [compatible(item) for item in node]
        if isinstance(node,dict):
            single = node.get('version',1) == 1 and 'table_id' in node and 'operation' in node
            return {key:compatible(value) for key,value in node.items() if not (single and key=='unit' and value is None)}
        return node
    payload = compatible(payload)
    return hashlib.sha256(json.dumps(payload,sort_keys=True,ensure_ascii=False,default=str,separators=(',',':')).encode()).hexdigest()


def replay(cur,user_id,project_id,key,digest):
    if not key:
        return None
    if not project_id:
        raise HTTPException(422,'저장할 가게를 선택해주세요.')
    cur.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))',(f'widget-save:{user_id}:{project_id}:{key}',))
    cur.execute('''SELECT id,widget_type,title,widget_data,layout,refresh_interval_seconds,save_key,save_fingerprint
        FROM dashboard_widgets WHERE user_id=%s AND project_id=%s AND save_key=%s''',(user_id,project_id,key))
    row=cur.fetchone()
    if row and row['save_fingerprint']!=digest:
        raise HTTPException(409,'같은 분석 결과의 저장 내용이 달라졌습니다. 대시보드에서 저장된 지표를 확인해주세요.')
    return row


def record(cur,widget_id,key,digest):
    if key:
        cur.execute('UPDATE dashboard_widgets SET save_key=%s,save_fingerprint=%s WHERE id=%s',(key,digest,widget_id))
