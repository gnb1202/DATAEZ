"""Owned file catalog and explicit, idempotent reuse of existing ledgers."""
import hashlib
import json
from pathlib import PurePath
from uuid import UUID, uuid4

from fastapi import HTTPException
from . import db
from .config import settings
from .storage import StorageService

TABULAR = ('.csv', '.xlsx', '.xls')
DOCUMENTS = ('.pdf', '.md', '.txt')

# Existing table imports, committed payment imports and indexed documents all
# participate. Pending import staging never enters files and still expires.
CATALOG = """
WITH catalog AS (
 SELECT f.*,e.content_hash,e.deleted_at,e.project_id AS assigned_project_id,
        assigned.name AS assigned_project_name,
        COALESCE(b.bindings,'[]'::jsonb) AS bindings
 FROM files f LEFT JOIN library_entries e ON e.file_id=f.id AND e.user_id=f.user_id
 LEFT JOIN projects assigned ON assigned.id=e.project_id AND assigned.user_id=f.user_id AND assigned.deleted_at IS NULL
 LEFT JOIN LATERAL (
   SELECT jsonb_agg(DISTINCT binding) AS bindings FROM (
     SELECT jsonb_build_object('kind','ledger','project_id',p.id,'project_name',p.name,
       'table_id',t.id,'table_name',t.name,'row_count',t.row_count) AS binding
     FROM table_meta t JOIN projects p ON p.id=t.project_id AND p.user_id=f.user_id AND p.deleted_at IS NULL
     WHERE t.user_id=f.user_id AND t.deleted_at IS NULL AND (t.source_file_id=f.id OR EXISTS (
       SELECT 1 FROM import_batches ib JOIN ledger_sources ls ON ls.id=ib.source_id
       WHERE ib.file_id=f.id AND ib.status='committed' AND ls.table_id=t.id AND ls.user_id=f.user_id))
     UNION ALL
     SELECT jsonb_build_object('kind','document','project_id',p.id,'project_name',p.name,'index_status',j.status,'job_id',j.id)
     FROM search_index_jobs j JOIN projects p ON p.id=j.project_id AND p.user_id=f.user_id AND p.deleted_at IS NULL
     WHERE j.file_id=f.id AND j.user_id=f.user_id
   ) refs
 ) b ON TRUE
 WHERE f.user_id=%(uid)s AND (e.project_id IS NULL OR assigned.id IS NOT NULL)
)
"""


def uid(value):
    try:
        return str(UUID(str(value)))
    except (ValueError, TypeError, AttributeError):
        raise HTTPException(422, '잘못된 파일 또는 가게 ID입니다.')


def own_project(cur, user_id, project_id):
    row = cur.execute('SELECT id,name FROM projects WHERE id=%s AND user_id=%s AND deleted_at IS NULL FOR SHARE', (uid(project_id), user_id)).fetchone()
    if not row:
        raise HTTPException(404, '가게를 찾을 수 없습니다.')
    return row


def public(row):
    bindings = row['bindings'] or []
    status = 'linked' if any(b['kind'] == 'ledger' for b in bindings) else 'stored'
    if row['deleted_at']:
        status = 'removed'
    elif any(b['kind'] == 'document' for b in bindings):
        status = 'document_ready' if all(b.get('index_status') == 'succeeded' for b in bindings if b['kind'] == 'document') else 'index_failed' if any(b.get('index_status') in ('failed','cancelled') for b in bindings) else 'index_pending'
    return {'file_id': str(row['id']), 'filename': row['filename'], 'size_bytes': row['size_bytes'],
            'created_at': row['created_at'], 'content_hash': row['content_hash'], 'status': status,
            'project_id': str(row['assigned_project_id']) if row['assigned_project_id'] else None,
            'project_name': row['assigned_project_name'], 'bindings': bindings,
            'kind': 'table' if row['filename'].lower().endswith(TABULAR) else 'document'}


def get_record(user_id, file_id, *, include_removed=False):
    with db._connect() as conn:
        row = conn.execute(CATALOG + 'SELECT * FROM catalog WHERE id=%(fid)s', {'uid': user_id, 'fid': uid(file_id)}).fetchone()
    if not row or (row['deleted_at'] and not include_removed):
        raise HTTPException(404, '파일을 찾을 수 없거나 보관함에서 제거되었습니다.')
    return row


def list_library(user_id, *, project_id=None, search='', kind='', offset=0, limit=30):
    if not isinstance(offset, int) or offset < 0:
        raise HTTPException(422, 'offset은 0 이상의 정수여야 합니다.')
    if project_id:
        with db._connect() as conn:
            own_project(conn, user_id, project_id)
    query = search.strip()[:160].replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
    params = {'uid': user_id, 'pid': uid(project_id) if project_id else None, 'search': '%'+query+'%', 'kind': kind,
              'offset': offset, 'limit': min(max(limit, 1), 100)}
    where = """ WHERE deleted_at IS NULL AND filename ILIKE %(search)s
      AND (%(pid)s::uuid IS NULL OR assigned_project_id=%(pid)s::uuid OR EXISTS
           (SELECT 1 FROM jsonb_array_elements(bindings) b WHERE b->>'project_id'=%(pid)s::text))
      AND (%(kind)s='' OR (%(kind)s='table' AND lower(filename) ~ '\\.(csv|xlsx|xls)$')
           OR (%(kind)s='document' AND lower(filename) ~ '\\.(pdf|md|txt)$'))"""
    with db._connect() as conn:
        total = conn.execute(CATALOG+'SELECT count(*) AS n FROM catalog'+where, params).fetchone()['n']
        rows = conn.execute(CATALOG+'SELECT * FROM catalog'+where+' ORDER BY created_at DESC,id LIMIT %(limit)s OFFSET %(offset)s', params).fetchall()
    return {'files': [public(row) for row in rows], 'total': total, 'offset': offset, 'limit': params['limit']}


def store_file(user_id, project_id, filename, content, storage=None):
    filename = PurePath(filename.replace('\\', '/')).name[:220]
    if not filename.lower().endswith(TABULAR+DOCUMENTS):
        raise HTTPException(422, 'CSV·XLSX·XLS·PDF·MD·TXT 파일을 지원합니다.')
    if not content or len(content) > settings.max_upload_size_mb * 1024 * 1024:
        raise HTTPException(422, f'비어 있지 않은 {settings.max_upload_size_mb}MB 이하 파일을 선택해주세요.')
    project_id = uid(project_id) if project_id else None
    digest = hashlib.sha256(content).hexdigest()
    storage = storage or StorageService()
    with db._connect() as conn:
        if project_id:
            own_project(conn, user_id, project_id)
        conn.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))', (f'library:{user_id}:{project_id}:{digest}',))
        found = conn.execute('SELECT file_id FROM library_entries WHERE user_id=%s AND project_id IS NOT DISTINCT FROM %s::uuid AND content_hash=%s AND deleted_at IS NULL', (user_id, project_id, digest)).fetchone()
        replayed = bool(found)
        if found:
            file_id = str(found['file_id'])
        else:
            file_id = str(uuid4())
            key = storage.upload_bytes(content, filename)
            conn.execute('INSERT INTO files(id,user_id,filename,storage_key,size_bytes) VALUES(%s,%s,%s,%s,%s)', (file_id,user_id,filename,key,len(content)))
            conn.execute('INSERT INTO library_entries(file_id,user_id,project_id,content_hash) VALUES(%s,%s,%s,%s)', (file_id,user_id,project_id,digest))
    return {**public(get_record(user_id,file_id)), 'replayed': replayed}


def preview_file(user_id, file_id, storage=None):
    row = get_record(user_id, file_id)
    content = (storage or StorageService()).read_bytes(row['storage_key'])
    if row['filename'].lower().endswith(TABULAR):
        from .data_import import prepare_import
        prepared = prepare_import(content,row['filename'])
        from .dashboard_metrics import json_value
        return {'file': public(row), 'columns': prepared.columns_schema, 'rows': [
            {col["name"]:json_value(value) for col,value in zip(prepared.columns_schema,item)} for item in prepared.rows[:8]], 'row_count':len(prepared.rows)}
    return {'file': public(row), 'text': content.decode('utf-8', errors='replace')[:4000] if not row['filename'].lower().endswith('.pdf') else None}


def prepare_file(user_id, file_id, project_id, storage=None):
    """An explicit UI action. Repeated calls return the same linked ledger/job."""
    row = get_record(user_id,file_id)
    project_id = uid(project_id)
    with db._connect() as conn:
        own_project(conn,user_id,project_id)
    existing = row['bindings']
    if existing:
        if any(b['project_id'] == project_id for b in existing):
            return {**public(row), 'replayed': True}
        raise HTTPException(409, '이미 다른 가게에 연결된 파일입니다. 보관함에서 해당 가게의 연결을 선택해주세요.')
    if row['assigned_project_id'] and str(row['assigned_project_id']) != project_id:
        raise HTTPException(409, '보관한 가게에 연결해주세요.')
    if not row['filename'].lower().endswith(TABULAR+DOCUMENTS):
        raise HTTPException(422,'분석에 지원되지 않는 파일 형식입니다.')
    content = (storage or StorageService()).read_bytes(row['storage_key'])
    digest = hashlib.sha256(content).hexdigest()
    prepared = None
    if row['filename'].lower().endswith(TABULAR):
        from .data_import import prepare_import
        prepared = prepare_import(content,row['filename'])
    with db._connect() as conn, conn.cursor() as cur:
        own_project(conn,user_id,project_id)
        cur.execute('SELECT id FROM files WHERE id=%s AND user_id=%s FOR UPDATE', (file_id,user_id))
        if not cur.fetchone():
            raise HTTPException(404,'파일을 찾을 수 없습니다.')
        cur.execute('SELECT deleted_at FROM library_entries WHERE file_id=%s', (file_id,))
        entry = cur.fetchone()
        if entry and entry['deleted_at']:
            raise HTTPException(404,'제거된 파일입니다.')
        cur.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))', (f'library:{user_id}:{project_id}:{digest}',))
        cur.execute('SELECT file_id FROM library_entries WHERE user_id=%s AND project_id=%s AND content_hash=%s AND deleted_at IS NULL AND file_id<>%s', (user_id,project_id,digest,file_id))
        if cur.fetchone():
            raise HTTPException(409,'이 가게에 같은 원본이 이미 있습니다. 해당 파일을 선택해주세요.')
        # Recheck under the file lock for concurrent prepare requests.
        cur.execute('SELECT id,project_id FROM table_meta WHERE source_file_id=%s AND user_id=%s AND deleted_at IS NULL', (file_id,user_id))
        table = cur.fetchone()
        cur.execute('SELECT id,project_id FROM search_index_jobs WHERE file_id=%s AND user_id=%s', (file_id,user_id))
        job = cur.fetchone()
        if table or job:
            if str((table or job)['project_id']) != project_id:
                raise HTTPException(409,'이미 다른 가게에 연결되었습니다.')
        elif prepared:
            from .data_import import write_import
            table_id = str(uuid4())
            name = row['filename'][:85]+' · '+str(file_id)[:8]
            write_import(cur, db.get_user_table_name(user_id,table_id), prepared, create=True)
            cur.execute('''INSERT INTO table_meta(id,project_id,user_id,name,columns_schema,row_count,source_file_id)
                VALUES(%s,%s,%s,%s,%s::jsonb,%s,%s)''', (table_id,project_id,user_id,name,json.dumps(prepared.columns_schema),len(prepared.rows),file_id))
        else:
            cur.execute('INSERT INTO search_index_jobs(user_id,project_id,file_id,file_sha256) VALUES(%s,%s,%s,%s)', (user_id,project_id,file_id,digest))
        cur.execute('''INSERT INTO library_entries(file_id,user_id,project_id,content_hash) VALUES(%s,%s,%s,%s)
            ON CONFLICT(file_id) DO UPDATE SET project_id=EXCLUDED.project_id''', (file_id,user_id,project_id,digest))
    return public(get_record(user_id,file_id))


def remove_file(user_id,file_id):
    get_record(user_id,file_id)
    with db._connect() as conn:
        conn.execute('SELECT id FROM files WHERE id=%s AND user_id=%s FOR UPDATE', (file_id,user_id))
        conn.execute('''INSERT INTO library_entries(file_id,user_id,deleted_at) VALUES(%s,%s,now())
          ON CONFLICT(file_id) DO UPDATE SET deleted_at=now()''', (file_id,user_id))
    # Retain originals needed by ledgers/history. This is explicitly "remove
    # from library", not destructive deletion of files or financial records.
    return {'removed':True}


def resolve_references(user_id, project_id, selections, *, confirmed=False):
    if not isinstance(selections,list) or len(selections)>10:
        raise HTTPException(422,'보관 파일은 최대 10개까지 선택할 수 있습니다.')
    if selections and not confirmed:
        raise HTTPException(422,'파일별 분석 범위와 가게를 확인해주세요.')
    refs, seen = [], set()
    for selection in selections:
        if not isinstance(selection,dict):
            raise HTTPException(422,'파일 선택 형식이 잘못되었습니다.')
        file_id = uid(selection.get('file_id'))
        if file_id in seen:
            raise HTTPException(422,'같은 파일은 분석 범위를 하나만 선택해주세요.')
        seen.add(file_id)
        row = get_record(user_id,file_id)
        table_id = uid(selection.get('binding_table_id') or selection['table_id']) if selection.get('binding_table_id') or selection.get('table_id') else None
        bindings = [b for b in row['bindings'] if (b.get('table_id') == table_id if table_id else b['kind']=='document')]
        if len(bindings)!=1:
            raise HTTPException(422,'분석할 장부 또는 준비된 문서를 먼저 선택해주세요.')
        binding = bindings[0]
        if binding['kind']=='document' and binding.get('index_status')!='succeeded':
            raise HTTPException(409,'문서의 검색 준비가 끝난 뒤 선택해주세요.')
        if binding['project_id'] != project_id and selection.get('include_other_store') is not True:
            raise HTTPException(422,'다른 가게를 분석 범위에 포함할지 확인해주세요.')
        scope = selection.get('scope') or ('linked_ledger' if table_id else 'document')
        if scope not in ({'linked_ledger','original_file'} if table_id else {'document'}):
            raise HTTPException(422,'지원하지 않는 파일 분석 범위입니다.')
        binding = dict(binding, binding_table_id=table_id)
        if scope == 'original_file':
            from .file_snapshots import original_table
            original = original_table(user_id,file_id,binding['project_id'])
            binding.update(table_id=str(original['id']),table_name=original['name'],row_count=original['row_count'])
        query_id = binding.get('table_id')
        refs.append({'file_id':file_id,'filename':row['filename'],'content_hash':row['content_hash'],
                     **binding,'query_table_name':(binding['project_name']+' · '+binding['table_name']+' · '+query_id[:8]) if query_id and (binding['project_id']!=project_id or scope=='original_file') else binding.get('table_name'),
                     'scope':scope})
    for a in refs:
        for b in refs:
            if a is not b and a.get('binding_table_id') and a.get('binding_table_id') == b.get('binding_table_id') and {a['scope'],b['scope']} == {'original_file','linked_ledger'}:
                raise HTTPException(422,'같은 장부의 원본 파일과 누적 장부를 함께 선택하면 거래가 중복됩니다. 한 범위로 맞춰주세요.')
    return refs


def reference_step(refs):
    return {'type':'meta','tool_name':'library_references','tool_output':{'files':refs,
        'scope_note':'파일별 scope를 따릅니다. original_file은 업로드 당시 행만, linked_ledger는 연결 장부 전체, document는 선택 문서를 사용합니다.'}}
