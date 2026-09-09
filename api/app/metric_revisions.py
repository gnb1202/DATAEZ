"""Optimistic definition edits and immutable history, serialized with refresh."""
import hashlib
import json
from uuid import UUID
from zoneinfo import ZoneInfo

import psycopg
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from . import db
from .auth import get_current_user
from .dashboard_metrics import calculate, resolve_definition, has_groups
from .metric_definitions import DashboardMetricDefinition, parse_metric_definition

router = APIRouter(prefix='/api/projects/{project_id}/metrics', tags=['dashboard'])


class EditMetricRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    title: str = Field(min_length=1, max_length=120)
    definition: DashboardMetricDefinition
    expected_revision: int = Field(ge=1)
    request_key: UUID


class RestoreMetricRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    revision: int = Field(ge=1)
    expected_revision: int = Field(ge=1)
    request_key: UUID


def ensure_metric_revisions():
    from .metric_revision_schema import DDL
    with db._connect() as conn:
        conn.execute(DDL)


def _widget(cur, user_id, project_id, metric_id, *, lock=False):
    cur.execute('''SELECT w.* FROM dashboard_widgets w JOIN projects p ON p.id=w.project_id AND p.user_id=w.user_id
        WHERE w.id=%s AND w.user_id=%s AND w.project_id=%s AND p.deleted_at IS NULL
          AND w.widget_data ? 'metric_definition' '''+('FOR UPDATE OF w FOR SHARE OF p' if lock else 'FOR SHARE OF w,p'), (metric_id,user_id,project_id))
    row = cur.fetchone()
    if not row:
        raise HTTPException(404, '저장된 지표를 찾을 수 없습니다.')
    return row


def _created_at(row):
    # Existing metric creation runs after SET LOCAL TimeZone=Asia/Seoul; the
    # legacy widget column is timestamp without time zone. History uses tz.
    value = row['created_at']
    return value.replace(tzinfo=ZoneInfo('Asia/Seoul')) if value.tzinfo is None else value


def _revision(row):
    return row['widget_data'].get('definition_revision', 1)


def _view(row, *, replayed=False, applied_revision=None):
    return {'id':str(row['id']), 'title':row['title'],'widget_type':row['widget_type'],
        'widget_data':row['widget_data'], 'definition_revision':_revision(row),
        'refresh_interval_seconds':row['refresh_interval_seconds'], 'next_refresh_at':row['next_refresh_at'],
        'replayed':replayed, 'applied_revision':applied_revision or _revision(row)}


def edit_metric(user_id, project_id, metric_id, body: EditMetricRequest | RestoreMetricRequest):
    try:
        with db._connect() as conn, conn.cursor() as cur:
            row = _widget(cur, user_id, project_id, metric_id, lock=True)
            digest = hashlib.sha256(json.dumps(body.model_dump(mode='json'),sort_keys=True,ensure_ascii=False).encode()).hexdigest()
            cur.execute('SELECT revision,request_hash FROM metric_definition_revisions WHERE metric_id=%s AND request_key=%s', (metric_id,str(body.request_key)))
            previous = cur.fetchone()
            if previous:
                if previous['request_hash'] != digest:
                    raise HTTPException(409, '같은 저장 요청에 다른 내용이 전달되었습니다. 변경 내용을 다시 확인해 주세요.')
                return _view(row, replayed=True, applied_revision=previous['revision'])
            current_revision = _revision(row)
            if body.expected_revision != current_revision:
                raise HTTPException(409, '다른 곳에서 지표가 수정되었습니다. 최신 지표를 다시 불러온 뒤 변경해 주세요.')
            cur.execute('''INSERT INTO metric_definition_revisions(metric_id,revision,title,definition,created_at)
                VALUES(%s,%s,%s,%s::jsonb,%s) ON CONFLICT(metric_id,revision) DO NOTHING''',
                (metric_id,current_revision,row['title'],json.dumps(row['widget_data']['metric_definition'],ensure_ascii=False),_created_at(row)))
            restored_from = None
            if isinstance(body, RestoreMetricRequest):
                cur.execute('SELECT title,definition FROM metric_definition_revisions WHERE metric_id=%s AND revision=%s', (metric_id,body.revision))
                old = cur.fetchone()
                if not old:
                    raise HTTPException(404, '해당 지표 변경 이력을 찾을 수 없습니다.')
                title, definition, restored_from = old['title'], parse_metric_definition(old['definition']), body.revision
            else:
                title, definition = body.title, body.definition
            meta = resolve_definition(project_id,user_id,definition,cur=cur)
            result = calculate(cur,user_id,definition,meta)
            result['definition_revision'] = current_revision+1
            cur.execute('''INSERT INTO metric_definition_revisions(metric_id,revision,title,definition,request_key,request_hash,restored_from_revision)
                VALUES(%s,%s,%s,%s::jsonb,%s,%s,%s)''', (metric_id,current_revision+1,title,
                json.dumps(definition.model_dump(mode='json'),ensure_ascii=False),str(body.request_key),digest,restored_from))
            cur.execute('''UPDATE dashboard_widgets SET title=%s,widget_type=%s,widget_data=%s::jsonb,refresh_failures=0,
                next_refresh_at=CASE WHEN refresh_interval_seconds>0 THEN clock_timestamp()+refresh_interval_seconds*interval '1 second' ELSE NULL END
                WHERE id=%s RETURNING *''', (title,'chart' if has_groups(definition) else 'kpi',json.dumps(result,ensure_ascii=False),metric_id))
            return _view(cur.fetchone())
    except psycopg.Error:
        raise HTTPException(422,'지표 변경을 계산하지 못했습니다. 기존 지표는 유지됩니다. 장부와 필터를 확인해 주세요.') from None


def history(user_id,project_id,metric_id,limit=20,offset=0):
    with db._connect() as conn, conn.cursor() as cur:
        row = _widget(cur,user_id,project_id,metric_id)
        cur.execute('SELECT count(*) AS n FROM metric_definition_revisions WHERE metric_id=%s',(metric_id,))
        total = cur.fetchone()['n']
        cur.execute('''SELECT revision,title,definition,restored_from_revision,created_at FROM metric_definition_revisions
            WHERE metric_id=%s ORDER BY revision DESC LIMIT %s OFFSET %s''',(metric_id,limit,offset))
        revisions = cur.fetchall()
        if not total:
            total = 1
            revisions = [{'revision':_revision(row),'title':row['title'],'definition':row['widget_data']['metric_definition'],
                          'created_at':_created_at(row),'restored_from_revision':None}] if offset==0 else []
    return {'metric':_view(row), 'revisions':revisions,'total':total,'limit':limit,'offset':offset}


@router.put('/{metric_id}')
def edit_route(project_id: UUID,metric_id: UUID,body: EditMetricRequest,user=Depends(get_current_user)):
    return edit_metric(user['id'],str(project_id),str(metric_id),body)


@router.get('/{metric_id}/history')
def history_route(project_id: UUID,metric_id: UUID,limit: int=Query(20,ge=1,le=100),offset: int=Query(0,ge=0),user=Depends(get_current_user)):
    return history(user['id'],str(project_id),str(metric_id),limit,offset)


@router.post('/{metric_id}/restore')
def restore_route(project_id: UUID,metric_id: UUID,body: RestoreMetricRequest,user=Depends(get_current_user)):
    return edit_metric(user['id'],str(project_id),str(metric_id),body)
