"""Rebuild one owner's store catalog using current filenames, dates and mappings.

Run from api/ with --user-id UUID --project-id UUID. Default is a read-only
plan; --apply makes real embedding API calls and replaces only changed entries.
This does not alter source files, ledger rows, document chunks or metric values.
"""
import argparse
import json
from pathlib import Path
import sys
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'api'))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--user-id', required=True, type=UUID)
    parser.add_argument('--project-id', required=True, type=UUID)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    from app import db, rag
    from app.rag_catalog import schema_snapshot
    from app.config import settings
    uid, pid = str(args.user_id), str(args.project_id)
    results = []
    try:
        if not db.get_project(pid, uid):
            raise ValueError('Store not found for this owner')
        if args.apply and not settings.rag_enabled:
            raise ValueError('Enable RAG before applying a catalog rebuild')

        def matches_current(table_id):
            with db._connect() as conn, conn.cursor() as cur:
                meta = schema_snapshot(cur, uid, pid, table_id)
                if not meta:
                    return False
                wanted = rag._hash_content(settings.openai_embedding_model + '\n' + rag.build_schema_doc(meta))
                cur.execute('SELECT content_hash FROM schema_embeddings WHERE table_meta_id=%s AND user_id=%s AND project_id=%s', (table_id, uid, pid))
                row = cur.fetchone()
                return bool(row and row['content_hash'] == wanted)

        for table in db.list_table_metas(pid, uid):
            tid = str(table['id'])
            current = matches_current(tid)
            status = 'current' if current else 'needs_reindex'
            if args.apply and not current:
                rag.upsert_schema_embedding(uid, pid, tid)
                status = 'updated' if matches_current(tid) else 'failed_or_changed_during_indexing'
            result = {'table_id': tid, 'name': table['name'], 'status': status}
            results.append(result)
            print(json.dumps(result, ensure_ascii=False), flush=True)
        return int(any(r['status'] == 'failed_or_changed_during_indexing' for r in results))
    finally:
        db.close_pool()


if __name__ == '__main__':
    raise SystemExit(main())
