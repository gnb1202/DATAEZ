"""Cash drafts confirmed by the user; ledger + provenance commit exactly once."""
import json
from datetime import date, datetime, time
from decimal import Decimal
from typing import Literal
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from psycopg import sql

from . import db, event_review
from .auth import get_current_user
from .config import settings
from .data_import import PreparedImport, write_import
from .exceptions import AppException, ResourceNotFound
from .import_validation import parse_decimal
from .ledger_imports import _store, _source
from .ledger_guards import lock_table_writes
from .payment_imports import PaymentImportMapping, payment_schema
from .rate_limiter import rate_limiter

router=APIRouter(prefix='/api/projects/{project_id}/cash-entries',tags=['cash'])
MAPPING=PaymentImportMapping(amount_column='amount',occurred_at_column='occurred_at',event_id_column='event_id',
    original_event_id_column='original_event_id',event_kind='signed',payment_method_column='payment_method',channel_column='channel')


class CashDraftRequest(BaseModel):
    model_config=ConfigDict(extra='forbid',str_strip_whitespace=True)
    request_key: UUID
    amount: str=Field(min_length=1,max_length=50)
    occurred_on: date | None=None
    kind: Literal['payment','refund']='payment'
    channel: str | None=Field(default=None,max_length=80)
    memo: str=Field(default='',max_length=500)
    original_event_id: str | None=Field(default=None,min_length=1,max_length=120)

    @field_validator('amount')
    @classmethod
    def money(cls,value):
        number=parse_decimal(value)
        if number<=0 or number.as_tuple().exponent < -2 or number.adjusted()>=20:
            raise ValueError('금액은 0보다 큰 숫자이며 소수점 둘째 자리까지 입력할 수 있습니다.')
        return event_review.decimal_text(number)

    @field_validator('channel','memo','original_event_id')
    @classmethod
    def valid_text(cls,value):
        if value and '\x00' in value:
            raise ValueError('널 문자는 저장할 수 없습니다.')
        return value

    @model_validator(mode='after')
    def original_only_for_refund(self):
        if self.kind=='payment' and self.original_event_id:
            raise ValueError('원거래 연결은 취소 기록에서만 사용합니다.')
        return self


class CashCommitRequest(BaseModel):
    model_config=ConfigDict(extra='forbid')
    confirmation_token: UUID
    separate_transaction: bool=False


def _owned(cur,user_id,project_id,entry_id,*,lock=False):
    _store(cur,user_id,project_id)
    cur.execute('SELECT *,expires_at<=clock_timestamp() AS is_expired FROM cash_entries WHERE id=%s AND user_id=%s AND project_id=%s'+(' FOR UPDATE' if lock else ''), (entry_id,user_id,project_id))
    row=cur.fetchone()
    if not row: raise ResourceNotFound('현금 입력 기록')
    return row


def _similar(cur,user_id,project_id,payload):
    args=(user_id,project_id,payload['occurred_on'],payload['amount'],payload['kind'])
    where="WHERE user_id=%s AND project_id=%s AND status='committed' AND payload->>'occurred_on'=%s AND payload->>'amount'=%s AND payload->>'kind'=%s"
    cur.execute('SELECT count(*) AS n FROM cash_entries '+where,args)
    count=cur.fetchone()['n']
    cur.execute('SELECT id,payload,committed_at FROM cash_entries '+where+' ORDER BY committed_at DESC,id LIMIT 5',args)
    return {'count':count,'entries':cur.fetchall()}


def _view(cur,row,*,replayed=False):
    view={k:v for k,v in row.items() if k not in ('user_id','request_key','request_hash')}
    payload=row['payload']
    view['signed_amount']=('-' if payload['kind']=='refund' else '')+payload['amount']
    view['event_id']='CASH-'+str(row['id']).replace('-','')
    view['review_url']=f"/dashboard?project={row['project_id']}&section=tables&cash_draft={row['id']}"
    view['replayed']=replayed
    view['similar']=_similar(cur,row['user_id'],row['project_id'],payload) if row['status']=='draft' else {'count':0,'entries':[]}
    return view


def draft(user_id,project_id,body:CashDraftRequest):
    raw=body.model_dump(mode='json',exclude={'request_key'})
    fingerprint=event_review.digest(raw)
    with db._connect() as conn,conn.cursor() as cur:
        _store(cur,user_id,project_id)
        payload={**raw,'occurred_on':raw['occurred_on'] or datetime.now(ZoneInfo('Asia/Seoul')).date().isoformat(),
                 'channel':raw['channel'] or None}
        cur.execute('''INSERT INTO cash_entries(id,user_id,project_id,request_key,request_hash,payload,confirmation_token)
            VALUES(%s,%s,%s,%s,%s,%s::jsonb,%s) ON CONFLICT(user_id,project_id,request_key)
            DO UPDATE SET request_key=EXCLUDED.request_key RETURNING *,expires_at<=clock_timestamp() AS is_expired''',
            (str(uuid4()),user_id,project_id,str(body.request_key),fingerprint,json.dumps(payload,ensure_ascii=False),str(uuid4())))
        row=cur.fetchone()
        if row['request_hash']!=fingerprint:
            raise AppException(409,'cash_request_changed','같은 요청에 다른 입력이 전달되었습니다. 새 입력 초안을 만들어 주세요.')
        return _view(cur,row)


def _cash_source(cur,user_id,project_id):
    # One source per store, created in the same transaction as the first entry.
    cur.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",('cash-source:'+project_id,))
    cur.execute("SELECT id FROM ledger_sources WHERE project_id=%s AND user_id=%s AND input_mode='cash'",(project_id,user_id))
    existing=cur.fetchone()
    if existing: return _source(cur,user_id,project_id,str(existing['id']))
    source_id,table_id=str(uuid4()),str(uuid4())
    table_name=db.get_user_table_name(user_id,table_id)
    schema=payment_schema(MAPPING)
    cur.execute('SELECT name FROM table_meta WHERE user_id=%s AND project_id=%s AND deleted_at IS NULL',(user_id,project_id))
    names={row['name'] for row in cur.fetchall()}
    name='현금 직접입력'; n=1
    while name in names:
        n+=1; name=f'현금 직접입력 ({n})'
    write_import(cur,table_name,PreparedImport(schema,[],[]),create=True)
    cur.execute('''INSERT INTO table_meta(id,project_id,user_id,name,description,columns_schema,row_count)
        VALUES(%s,%s,%s,%s,%s,%s::jsonb,0)''',(table_id,project_id,user_id,name,'현금 수납·취소 직접 입력. 거래 일자 기준이며 시각은 수집하지 않습니다. 메모는 현금 입력 이력에서 확인합니다.',json.dumps(schema)))
    cur.execute('''INSERT INTO ledger_sources(id,project_id,user_id,name,provider,account,feed,table_id,physical_table_name,mapping,event_index_version,storage_mode,input_mode)
        VALUES(%s,%s,%s,%s,'DATA:EZ',%s,'현금 직접입력',%s,%s,%s::jsonb,%s,'canonical','cash')''',
        (source_id,project_id,user_id,name,source_id,table_id,table_name,json.dumps(MAPPING.model_dump()),event_review.VERSION))
    return _source(cur,user_id,project_id,source_id)


def commit(user_id,project_id,entry_id,body:CashCommitRequest):
    with db._connect() as conn,conn.cursor() as cur:
        cur.execute("SELECT set_config('statement_timeout',%s,true)",(str(settings.query_timeout_ms),))
        _store(cur,user_id,project_id)
        # All cash writes: store -> cash-source lock -> source -> draft -> table.
        source=_cash_source(cur,user_id,project_id)
        row=_owned(cur,user_id,project_id,entry_id,lock=True)
        if str(row['confirmation_token'])!=str(body.confirmation_token):
            raise AppException(409,'cash_confirmation_changed','확인한 초안이 일치하지 않습니다. 입력 내용을 다시 확인해 주세요.')
        if row['status']=='committed': return _view(cur,row,replayed=True)
        if row['status']!='draft' or row['is_expired']:
            raise AppException(409,'cash_draft_inactive','취소되었거나 24시간이 지난 초안입니다. 새 입력을 만들어 주세요.')
        payload=row['payload']
        if _similar(cur,user_id,project_id,payload)['count'] and not body.separate_transaction:
            raise AppException(409,'cash_similar_exists','같은 날짜·종류·금액의 현금 기록이 있습니다. 기존 기록을 확인하고 별도 거래일 때만 반영해 주세요.')
        if payload['original_event_id']:
            cur.execute("SELECT 1 FROM source_events WHERE source_id=%s AND event_id=%s AND event_kind='payment'",(source['id'],payload['original_event_id']))
            if not cur.fetchone(): raise AppException(422,'cash_original_missing','이 가게 현금 장부의 원거래를 찾을 수 없습니다.')
        schema=payment_schema(MAPPING)
        if source['target_schema']!=schema or source['mapping']!=MAPPING.model_dump():
            raise AppException(409,'cash_schema_changed','현금 장부의 구조가 변경되었습니다. 장부 설정을 확인해 주세요.')
        event_id='CASH-'+str(row['id']).replace('-','')
        amount=Decimal(payload['amount']); amount=amount.copy_negate() if payload['kind']=='refund' else amount
        occurred_at=datetime.combine(date.fromisoformat(payload['occurred_on']),time.min,ZoneInfo('Asia/Seoul'))
        values=(event_id,payload['original_event_id'],payload['kind'],amount,occurred_at.isoformat(),'KRW','현금',payload['channel'])
        normalized=event_review.normalize(values,schema)
        lock_table_writes(cur,source['physical_table_name'])
        cur.execute('SELECT id FROM table_meta WHERE id=%s AND deleted_at IS NULL FOR UPDATE',(source['table_id'],))
        if not cur.fetchone(): raise ResourceNotFound('현금 장부')
        cur.execute(sql.SQL('INSERT INTO {} ({}) VALUES ({}) RETURNING _row_id').format(sql.Identifier(source['physical_table_name']),
            sql.SQL(',').join(sql.Identifier(c['name']) for c in schema),sql.SQL(',').join(sql.Placeholder() for _ in values)),values)
        target=cur.fetchone()['_row_id']
        cur.execute('''INSERT INTO source_events(source_id,target_row_id,event_kind,event_id,event_key_hash,normalized,content_hash,candidate_hash,first_row_number)
            VALUES(%s,%s,%s,%s,%s,%s::jsonb,%s,%s,1)''',(source['id'],target,payload['kind'],event_id,event_review.digest(event_review.event_key(normalized)),
            json.dumps(normalized,ensure_ascii=False),event_review.digest(normalized),event_review.signature(normalized)))
        cur.execute('UPDATE table_meta SET row_count=row_count+1,updated_at=clock_timestamp() WHERE id=%s',(source['table_id'],))
        cur.execute('UPDATE ledger_sources SET data_revision=data_revision+1,last_manual_entry_at=clock_timestamp() WHERE id=%s',(source['id'],))
        cur.execute("UPDATE cash_entries SET status='committed',source_id=%s,target_row_id=%s,committed_at=clock_timestamp() WHERE id=%s RETURNING *,false AS is_expired",(source['id'],target,entry_id))
        return _view(cur,cur.fetchone())


def get_entry(user_id,project_id,entry_id):
    with db._connect() as conn,conn.cursor() as cur:
        return _view(cur,_owned(cur,user_id,project_id,entry_id))


def list_entries(user_id,project_id,limit=20,offset=0):
    with db._connect() as conn,conn.cursor() as cur:
        _store(cur,user_id,project_id)
        cur.execute('SELECT count(*) AS n FROM cash_entries WHERE user_id=%s AND project_id=%s',(user_id,project_id)); total=cur.fetchone()['n']
        cur.execute('''SELECT id,payload,status,source_id,target_row_id,created_at,committed_at,expires_at,expires_at<=clock_timestamp() AS is_expired
            FROM cash_entries WHERE user_id=%s AND project_id=%s ORDER BY created_at DESC,id DESC LIMIT %s OFFSET %s''',(user_id,project_id,limit,offset))
        rows=cur.fetchall()
    return {'entries':rows,'total':total,'limit':limit,'offset':offset,'today':datetime.now(ZoneInfo('Asia/Seoul')).date().isoformat()}


def cancel(user_id,project_id,entry_id):
    with db._connect() as conn,conn.cursor() as cur:
        row=_owned(cur,user_id,project_id,entry_id,lock=True)
        if row['status']=='committed': raise AppException(409,'cash_already_committed','이미 반영한 거래는 초안 취소로 지울 수 없습니다.')
        cur.execute("UPDATE cash_entries SET status='cancelled' WHERE id=%s",(entry_id,))
    return {'id':entry_id,'status':'cancelled'}


@router.post('/drafts')
def draft_route(project_id:UUID,body:CashDraftRequest,user=Depends(get_current_user)):
    rate_limiter.check(f"cash-draft:{user['id']}",settings.upload_rate_limit_per_minute,60)
    return draft(user['id'],str(project_id),body)


@router.post('/{entry_id}/commit')
def commit_route(project_id:UUID,entry_id:UUID,body:CashCommitRequest,user=Depends(get_current_user)):
    rate_limiter.check(f"cash-commit:{user['id']}",settings.upload_rate_limit_per_minute,60)
    return commit(user['id'],str(project_id),str(entry_id),body)


@router.get('')
def list_route(project_id:UUID,limit:int=Query(20,ge=1,le=100),offset:int=Query(0,ge=0),user=Depends(get_current_user)):
    return list_entries(user['id'],str(project_id),limit,offset)


@router.get('/{entry_id}')
def get_route(project_id:UUID,entry_id:UUID,user=Depends(get_current_user)):
    return get_entry(user['id'],str(project_id),str(entry_id))


@router.delete('/{entry_id}')
def cancel_route(project_id:UUID,entry_id:UUID,user=Depends(get_current_user)):
    return cancel(user['id'],str(project_id),str(entry_id))
