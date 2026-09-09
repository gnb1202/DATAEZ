"""Read-only discovery for explicitly requested, owned stores."""
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field
from fastapi import HTTPException
from psycopg import sql
from . import db
from .dashboard_metrics import json_value


class StorePage(BaseModel):
    model_config = ConfigDict(extra='forbid')
    offset: int = Field(default=0,ge=0)


class StoreTablesPage(StorePage):
    project_id: UUID


class StoreTableRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    project_id: UUID
    table_id: UUID


def list_stores(user_id,args):
    page=StorePage.model_validate(args)
    with db._connect() as conn:
        rows=conn.execute('SELECT id,name,description FROM projects WHERE user_id=%s AND deleted_at IS NULL ORDER BY name,id LIMIT 21 OFFSET %s',(user_id,page.offset)).fetchall()
    return {'stores':[dict(r,id=str(r['id'])) for r in rows[:20]],'offset':page.offset,'next_offset':page.offset+20 if len(rows)>20 else None}


def list_store_tables(user_id,args):
    page=StoreTablesPage.model_validate(args)
    with db._connect() as conn:
        project=conn.execute('SELECT id,name FROM projects WHERE id=%s AND user_id=%s AND deleted_at IS NULL FOR SHARE',(page.project_id,user_id)).fetchone()
        if not project: raise HTTPException(404,'가게를 찾을 수 없습니다.')
        rows=conn.execute("SELECT id,name,description,row_count FROM table_meta WHERE project_id=%s AND user_id=%s AND deleted_at IS NULL AND to_jsonb(table_meta)->>'original_file_id' IS NULL ORDER BY name,id LIMIT 11 OFFSET %s",(page.project_id,user_id,page.offset)).fetchall()
    return {'project_id':str(page.project_id),'project_name':project['name'],'tables':[dict(r,id=str(r['id'])) for r in rows[:10]],'offset':page.offset,'next_offset':page.offset+10 if len(rows)>10 else None}


def inspect_store_table(user_id,args):
    request=StoreTableRequest.model_validate(args)
    with db._connect() as conn,conn.cursor() as cur:
        cur.execute('SELECT id,name FROM projects WHERE id=%s AND user_id=%s AND deleted_at IS NULL FOR SHARE',(request.project_id,user_id))
        project=cur.fetchone()
        if not project: raise HTTPException(404,'가게를 찾을 수 없습니다.')
        cur.execute('SELECT id,name,columns_schema,description,row_count FROM table_meta WHERE id=%s AND project_id=%s AND user_id=%s AND deleted_at IS NULL FOR SHARE',(request.table_id,request.project_id,user_id))
        table=cur.fetchone()
        if not table: raise HTTPException(404,'해당 가게의 장부를 찾을 수 없습니다.')
        cur.execute(sql.SQL('SELECT * FROM {} LIMIT 3').format(sql.Identifier(db.get_user_table_name(user_id,str(request.table_id)))))
        samples=[{k:json_value(v) if not isinstance(v,str) else v[:160] for k,v in r.items()} for r in cur.fetchall()]
        cur.execute('SELECT name,mapping FROM ledger_sources WHERE table_id=%s AND project_id=%s AND user_id=%s',(request.table_id,request.project_id,user_id))
        managed=cur.fetchone()
    return {'project_id':str(request.project_id),'project_name':project['name'],'table_id':str(table['id']),'table_name':table['name'],
            'description':table['description'],'columns':table['columns_schema'],'row_count':table['row_count'],'sample_rows':samples,'samples_are_partial':True,'managed_source':managed}
