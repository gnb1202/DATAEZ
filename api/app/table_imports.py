"""One transaction for imported rows, file ownership and table metadata."""
import json
from uuid import uuid4

from .data_import import prepare_import, write_import
from .db import _connect, get_user_table_name
from .exceptions import ResourceNotFound
from .ledger_guards import assert_unmanaged_table

def create_imported_table(user_id, project_id, name, content, filename, storage):
    prepared = prepare_import(content, filename)
    table_id, file_id = str(uuid4()), str(uuid4())
    # Parse before writing files. Failed DB writes may leave an unreferenced
    # object; do not delete after an ambiguous commit/connection failure.
    # Batch retention/cleanup belongs to the next source/batch phase.
    with _connect() as conn, conn.cursor() as cur:
        cur.execute("SELECT id FROM projects WHERE id=%s AND user_id=%s AND deleted_at IS NULL FOR SHARE", (project_id, user_id))
        if not cur.fetchone():
            raise ResourceNotFound("가게")
        storage_key = storage.upload_bytes(content, filename)
        cur.execute("INSERT INTO files (id,user_id,filename,storage_key,size_bytes) VALUES (%s,%s,%s,%s,%s)",
                    (file_id, user_id, filename, storage_key, len(content)))
        write_import(cur, get_user_table_name(user_id, table_id), prepared, create=True)
        cur.execute("""INSERT INTO table_meta (id,project_id,user_id,name,columns_schema,row_count,source_file_id)
                    VALUES (%s,%s,%s,%s,%s::jsonb,%s,%s)
                    RETURNING id,project_id,user_id,name,description,columns_schema,row_count,source_file_id,created_at,updated_at""",
                    (table_id, project_id, user_id, name, json.dumps(prepared.columns_schema), len(prepared.rows), file_id))
        meta = cur.fetchone()
        conn.commit()
    return meta


def append_imported_table(user_id, project_id, table_id, content, filename):
    # Validation uses the schema protected by this metadata row lock. A stale
    # client row_count cannot overwrite another successful append's count.
    with _connect() as conn, conn.cursor() as cur:
        assert_unmanaged_table(cur, get_user_table_name(user_id, table_id))
        cur.execute("""SELECT t.columns_schema FROM table_meta t JOIN projects p ON p.id=t.project_id
                    WHERE t.id=%s AND t.user_id=%s AND t.project_id=%s AND t.deleted_at IS NULL
                    AND p.user_id=%s AND p.deleted_at IS NULL FOR UPDATE OF t FOR SHARE OF p""",
                    (table_id, user_id, project_id, user_id))
        meta = cur.fetchone()
        if not meta:
            raise ResourceNotFound("장부")
        prepared = prepare_import(content, filename, meta["columns_schema"])
        write_import(cur, get_user_table_name(user_id, table_id), prepared, create=False)
        cur.execute("""UPDATE table_meta SET row_count=row_count+%s, updated_at=now()
                    WHERE id=%s AND user_id=%s AND project_id=%s RETURNING row_count""",
                    (len(prepared.rows), table_id, user_id, project_id))
        total = cur.fetchone()["row_count"]
        conn.commit()
    return {"rows_inserted": len(prepared.rows), "total_row_count": total}
