"""Restore attributes from proven origins without changing financial events.

Snapshots use short source locks; immutable file reads/parsing happen outside
transactions. Apply locks source -> preview -> metadata -> physical table,
rechecks the full snapshot and publishes rows, registry, rules and audit together.
"""
import hashlib
import json
from datetime import date, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from psycopg import sql
from pydantic import BaseModel, ConfigDict, Field, model_validator

from .config import settings
from .db import _connect
from .event_review import digest, normalize, decimal_text, event_key, signature
from .exceptions import AppException, ResourceNotFound
from .import_validation import ImportValidationError
from .ledger_imports import _source, _indexed, conflict, _file_source
from .ledger_guards import lock_table_writes
from .payment_imports import ATTRIBUTE_TYPES, PaymentImportMapping, payment_schema, prepare_payment_import, prepare_payment_values

MAX_ROWS = 100000
MAX_FILES = 500
MAX_BYTES = 100 * 1024 * 1024


class RestoreAttributesRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    payment_method_column: str | None = Field(default=None, min_length=1, max_length=200)
    channel_column: str | None = Field(default=None, min_length=1, max_length=200)
    fee_column: str | None = Field(default=None, min_length=1, max_length=200)

    @model_validator(mode="after")
    def require_addition(self):
        if not self.model_dump(exclude_none=True):
            raise ValueError("추가할 속성의 원본 컬럼을 하나 이상 선택해주세요.")
        return self


def _jsonable(value):
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, Decimal):
        return decimal_text(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    return value


def _mapping(source, additions):
    current = PaymentImportMapping.model_validate(source["mapping"]).model_dump()
    if any(current[key] is not None for key in additions):
        raise conflict("attribute_already_mapped", "이미 연결한 속성의 변경·덮어쓰기는 지원하지 않습니다. 미연결 속성만 선택해주세요.")
    new = PaymentImportMapping(**{**current, **additions})
    selected = [v for k, v in new.model_dump().items() if k.endswith("_column") and v is not None]
    if len(selected) != len(set(selected)):
        raise AppException(422, "invalid_mapping", "기존 필드를 포함해 서로 다른 필드에 같은 컬럼을 연결할 수 없습니다.")
    return new


def _snapshot(cur, source):
    _file_source(source)
    _indexed(source)
    cur.execute("SELECT set_config('statement_timeout',%s,true)", (str(settings.query_timeout_ms),))
    cur.execute(sql.SQL("SELECT * FROM {} ORDER BY _row_id LIMIT %s").format(sql.Identifier(source["physical_table_name"])), (MAX_ROWS + 1,))
    physical = cur.fetchall()
    cur.execute("SELECT * FROM source_events WHERE source_id=%s ORDER BY target_row_id LIMIT %s", (source["id"], MAX_ROWS + 1))
    events = cur.fetchall()
    if max(len(physical), len(events)) > MAX_ROWS:
        raise AppException(422, "restoration_too_large", "속성 복원은 한 번에 100,000행까지 지원합니다.")
    files = []
    if source['storage_mode'] != 'original':
        cur.execute("""SELECT b.id,b.filename,b.storage_key,b.content_hash,b.size_bytes,b.status FROM import_batches b
            WHERE b.source_id=%s AND EXISTS (SELECT 1 FROM source_events e WHERE e.source_id=b.source_id AND e.first_batch_id=b.id)
            ORDER BY b.id""", (source["id"],))
        files = cur.fetchall()
    if len(files) > MAX_FILES or sum(f["size_bytes"] for f in files) > MAX_BYTES:
        raise AppException(422, "restoration_too_large", "복원 원본은 500개 파일·합계 100MB까지 지원합니다.")
    cur.execute("""SELECT id,status,rule_version,preview_token FROM import_batches WHERE source_id=%s
                   AND status NOT IN ('committed','expired') ORDER BY id""", (source["id"],))
    pending = cur.fetchall()
    cur.execute("SELECT row_count,columns_schema FROM table_meta WHERE id=%s", (source["table_id"],))
    meta = cur.fetchone()
    state = {"source": {k: source[k] for k in ("id", "table_id", "mapping", "storage_mode", "rule_version", "data_revision", "event_index_version")}
             | {"target_schema": meta['columns_schema']},
             "physical": physical, "events": events, "files": files, "pending": pending, "row_count": meta['row_count']}
    return state, digest(_jsonable(state))


def _plan(state, mapping, additions, storage):
    source, events = state["source"], state["events"]
    names = [name for name in ATTRIBUTE_TYPES if name + "_column" in additions]
    report = {"can_apply": False, "row_count": len(events), "file_count": len(state["files"]),
              "pending_uploads": len(state["pending"]), "origin": source["storage_mode"],
              "attributes": {n: {"column": additions[n + "_column"], "provided": 0, "missing": 0} for n in names},
              "issues": [], "issue_count": 0, "sample": []}
    def problem(code, message, row=None, filename=None, column=None):
        report["issue_count"] += 1
        if len(report["issues"]) < 50:
            report["issues"].append({"code": code, "message": message, "row": row, "filename": filename, "column": column})

    physical = {r["_row_id"]: r for r in state["physical"]}
    if len(events) != state["row_count"] or set(physical) != {e["target_row_id"] for e in events}:
        problem("registry_mismatch", "장부 행과 중복 판정 기록이 일치하지 않습니다. 전체 기준점 확인이 필요합니다.")
        return report, []
    previous = PaymentImportMapping.model_validate(source["mapping"])
    old_schema = payment_schema(previous)
    new_schema = payment_schema(mapping)
    original_mode = source["storage_mode"] == "original"
    if not original_mode and source["target_schema"] != old_schema:
        problem("schema_mismatch", "현재 장부 컬럼이 등록된 매핑과 일치하지 않습니다.")
        return report, []
    # Validate physical contents against the current registry before looking up
    # optional attributes. Any out-of-band edit blocks the entire operation.
    try:
        if original_mode:
            columns = [c["name"] for c in source["target_schema"]]
            for name in names:
                if name == "fee":
                    column = next((c for c in source["target_schema"] if c["name"] == additions['fee_column']), None)
                    if not column or not column['type'].upper().startswith(('NUMERIC', 'DECIMAL', 'BIGINT', 'INTEGER', 'SMALLINT', 'INT', 'REAL', 'DOUBLE')):
                        problem("fee_type", "기존 원본 장부의 수수료는 숫자 컬럼이어야 합니다.", column=additions['fee_column'])
                        return report, []
            prepared = prepare_payment_values(columns, [[r[c] for c in columns] for r in state['physical']], list(physical), mapping)
            proposed = {n: normalize(row, prepared.columns_schema) for n, row in zip(prepared.row_numbers, prepared.rows)}
            current = {n: {k: v for k, v in event.items() if k not in names} for n, event in proposed.items()}
        else:
            current = {n: normalize(tuple(r[c['name']] for c in old_schema), old_schema) for n, r in physical.items()}
            proposed = {}
    except (ImportValidationError, ValueError, TypeError, KeyError) as exc:
        problem("invalid_stored_rows", exc.detail if isinstance(exc, ImportValidationError) else "현재 장부 값을 검증할 수 없습니다.")
        return report, []
    for event in events:
        normalized = event['normalized']
        key = event_key(normalized)
        if (current[event['target_row_id']] != normalized or digest(normalized) != event['content_hash']
                or event['event_id'] != normalized['event_id'] or event['event_kind'] != normalized['event_kind']
                or event['event_key_hash'] != (digest(key) if key is not None else None)
                or event['candidate_hash'] != signature(normalized)):
            problem("event_changed", "현재 장부와 중복 판정 내용이 다릅니다.", event['target_row_id'])

    if not original_mode:
        by_file = {}
        for event in events:
            if event['first_batch_id'] is None:
                problem("origin_missing", "최초 반영 파일·행을 증명할 수 없습니다. 거래를 추측해 연결하지 않습니다.", event['target_row_id'])
            else:
                by_file.setdefault(str(event['first_batch_id']), []).append(event)
        files = {str(f['id']): f for f in state['files']}
        for batch_id, group in by_file.items():
            file = files.get(batch_id)
            if not file or file['status'] != 'committed':
                problem("origin_missing", "최초 반영 완료 파일을 찾을 수 없습니다.")
                continue
            try:
                content = storage.read_staged(file['storage_key'])
            except Exception:
                problem("file_unavailable", "보관된 원본 파일을 읽을 수 없습니다. 원본 보관 상태를 확인해주세요.", filename=file['filename'])
                continue
            if len(content) != file['size_bytes'] or hashlib.sha256(content).hexdigest() != file['content_hash']:
                problem("file_changed", "보관된 원본 파일의 내용이 최초 반영본과 다릅니다.", filename=file['filename'])
                continue
            try:
                selected = {e['first_row_number'] for e in group}
                if len(selected) != len(group):
                    problem("origin_repeated", "여러 장부 행이 같은 최초 원본 행을 가리킵니다.", filename=file['filename'])
                    continue
                prepared = prepare_payment_import(content, file['filename'], mapping, selected_rows=selected)
                rows = {n: normalize(row, prepared.columns_schema) for n, row in zip(prepared.row_numbers, prepared.rows)}
            except ImportValidationError as exc:
                for item in exc.issues:
                    problem("invalid_original", item['message'], item['row'], file['filename'], item['column'])
                continue
            for event in group:
                new = rows[event['first_row_number']]
                if {k: v for k, v in new.items() if k not in names} != event['normalized']:
                    problem("original_mismatch", "원본 행의 기존 금액·ID·일시·연결 속성이 현재 기록과 다릅니다.", event['first_row_number'], file['filename'])
                    continue
                proposed[event['target_row_id']] = new
    changes = []
    files = {str(f['id']): f for f in state['files']}
    for event in events:
        row_id = event['target_row_id']
        if row_id not in proposed:
            continue
        new = proposed[row_id]
        for name in names:
            report['attributes'][name]['provided' if name in new else 'missing'] += 1
        origin = files.get(str(event['first_batch_id']), {})
        change = {"target_row_id": row_id, "before": event['normalized'], "after": new,
                  "origin_batch_id": str(event['first_batch_id']) if not original_mode and event['first_batch_id'] else None,
                  "origin_row_number": row_id if original_mode else event['first_row_number']}
        changes.append(change)
        if len(report['sample']) < 10:
            report['sample'].append({"target_row_id": row_id, "event_id": event['event_id'],
                "filename": "보존된 원본 장부" if original_mode else origin.get('filename'),
                "row_number": row_id if original_mode else event['first_row_number'],
                "values": {n: new.get(n) for n in names}})
    report['can_apply'] = report['issue_count'] == 0 and len(changes) == len(events)
    return report, changes


def _public(row, *, replayed=False):
    return {k: _jsonable(v) for k, v in row.items() if k not in {'snapshot_hash', 'is_expired'}} | {'replayed': replayed}


def preview_restoration(user_id, project_id, source_id, request, storage):
    additions = request.model_dump(exclude_none=True)
    with _connect() as conn, conn.cursor() as cur:
        source = _source(cur, user_id, project_id, source_id)
        mapping = _mapping(source, additions)
        state, fingerprint = _snapshot(cur, source)
    report, _ = _plan(state, mapping, additions, storage)
    with _connect() as conn, conn.cursor() as cur:
        source = _source(cur, user_id, project_id, source_id)
        _, latest = _snapshot(cur, source)
        if latest != fingerprint:
            raise conflict('stale_restoration', '검사 중 장부나 업로드 상태가 바뀌었습니다. 속성 복원을 다시 검사해주세요.')
        cur.execute("""INSERT INTO source_attribute_restorations(id,source_id,status,additions,mapping,old_rule_version,new_rule_version,snapshot_hash,report)
            VALUES (%s,%s,%s,%s::jsonb,%s::jsonb,%s,%s,%s,%s::jsonb) RETURNING *""",
            (str(uuid4()), source_id, 'ready' if report['can_apply'] else 'blocked', json.dumps(additions), mapping.model_dump_json(),
             source['rule_version'], source['rule_version'] + 1, fingerprint, json.dumps(report)))
        result = _public(cur.fetchone())
        conn.commit()
    return result


def _restoration(cur, source_id, restoration_id):
    cur.execute("""SELECT *,expires_at<=now() AS is_expired FROM source_attribute_restorations
                   WHERE source_id=%s AND id=%s FOR UPDATE""", (source_id, restoration_id))
    row = cur.fetchone()
    if not row:
        raise ResourceNotFound('속성 복원 검사')
    return row


def _ready(row, fingerprint):
    if row['status'] != 'ready' or row['is_expired'] or row['snapshot_hash'] != fingerprint:
        raise conflict('stale_restoration', '검사가 만료되었거나 장부·업로드 상태가 바뀌었습니다. 속성 복원을 다시 검사해주세요.')


def apply_restoration(user_id, project_id, source_id, restoration_id, storage):
    with _connect() as conn, conn.cursor() as cur:
        source = _source(cur, user_id, project_id, source_id)
        record = _restoration(cur, source_id, restoration_id)
        if record['status'] == 'applied':
            return _public(record, replayed=True)
        state, fingerprint = _snapshot(cur, source)
        _ready(record, fingerprint)
        mapping = _mapping(source, record['additions'])
    report, changes = _plan(state, mapping, record['additions'], storage)
    if not report['can_apply'] or report != record['report']:
        raise conflict('restoration_original_changed', '원본 재검증 결과가 달라졌습니다. 보관 상태를 확인하고 다시 검사해주세요.')
    with _connect() as conn, conn.cursor() as cur:
        source = _source(cur, user_id, project_id, source_id)
        record = _restoration(cur, source_id, restoration_id)
        if record['status'] == 'applied':
            return _public(record, replayed=True)
        lock_table_writes(cur, source['physical_table_name'])
        # RAG also locks metadata before reading the physical table. Keep that
        # ordering when ALTER TABLE needs an exclusive relation lock.
        cur.execute('SELECT id FROM table_meta WHERE id=%s FOR UPDATE', (source['table_id'],))
        latest_state, latest = _snapshot(cur, source)
        _ready(record, latest)
        names = list(report['attributes'])
        if source['storage_mode'] == 'canonical':
            for name in names:
                cur.execute(sql.SQL('ALTER TABLE {} ADD COLUMN {} {}').format(sql.Identifier(source['physical_table_name']),
                            sql.Identifier(name), sql.SQL(ATTRIBUTE_TYPES[name])))
            if changes:
                cur.executemany(sql.SQL('UPDATE {} SET {} WHERE _row_id=%s').format(sql.Identifier(source['physical_table_name']),
                    sql.SQL(',').join(sql.SQL('{}=%s').format(sql.Identifier(n)) for n in names)),
                    [tuple(c['after'].get(n) for n in names) + (c['target_row_id'],) for c in changes])
            schema = payment_schema(mapping)
        else:
            schema = latest_state['source']['target_schema']
        if changes:
            cur.executemany('UPDATE source_events SET normalized=%s::jsonb,content_hash=%s WHERE source_id=%s AND target_row_id=%s',
                            [(json.dumps(c['after']), digest(c['after']), source_id, c['target_row_id']) for c in changes])
            cur.executemany("""INSERT INTO source_attribute_changes(restoration_id,source_id,target_row_id,before_normalized,after_normalized,origin_batch_id,origin_row_number)
                VALUES (%s,%s,%s,%s::jsonb,%s::jsonb,%s,%s)""",
                [(restoration_id, source_id, c['target_row_id'], json.dumps(c['before']), json.dumps(c['after']), c['origin_batch_id'], c['origin_row_number']) for c in changes])
        cur.execute('UPDATE table_meta SET columns_schema=%s::jsonb,updated_at=now() WHERE id=%s', (json.dumps(schema), source['table_id']))
        cur.execute('UPDATE ledger_sources SET mapping=%s::jsonb,rule_version=rule_version+1,data_revision=data_revision+1 WHERE id=%s RETURNING rule_version,data_revision',
                    (mapping.model_dump_json(), source_id))
        versions = cur.fetchone()
        # Historical review decisions/results stay as originally recorded. Old
        # pending previews lose their decisions and must be uploaded anew.
        cur.execute("""DELETE FROM import_rows r USING import_batches b WHERE r.batch_id=b.id
                       AND b.source_id=%s AND b.status NOT IN ('committed','expired')""", (source_id,))
        cur.execute("""UPDATE import_batches SET status=CASE WHEN status='staging' THEN status ELSE 'uploaded' END,
            preview_token=NULL,preview_revision=NULL,summary=NULL,review_version=0,
            error=%s::jsonb WHERE source_id=%s AND status NOT IN ('committed','expired')""",
            (json.dumps({'detail': '출처에 속성이 추가되었습니다. 같은 파일을 새로 업로드해 검사해주세요.', 'code': 'mapping_changed'}), source_id))
        result = {**versions, 'table_id': str(source['table_id']), 'rows_verified': len(changes), 'attributes': report['attributes'], 'invalidated_uploads': cur.rowcount}
        cur.execute("""UPDATE source_attribute_restorations SET status='applied',applied_at=now(),result=%s::jsonb
                       WHERE id=%s RETURNING *""", (json.dumps(result), restoration_id))
        result = _public(cur.fetchone())
        conn.commit()
    return result


def list_restorations(user_id, project_id, source_id):
    with _connect() as conn, conn.cursor() as cur:
        _source(cur, user_id, project_id, source_id)
        cur.execute('SELECT * FROM source_attribute_restorations WHERE source_id=%s ORDER BY created_at DESC,id DESC LIMIT 20', (source_id,))
        return [_public(row) for row in cur.fetchall()]


def list_changes(user_id, project_id, source_id, restoration_id, limit=50, offset=0):
    with _connect() as conn, conn.cursor() as cur:
        _source(cur, user_id, project_id, source_id)
        _restoration(cur, source_id, restoration_id)
        cur.execute('SELECT count(*) AS n FROM source_attribute_changes WHERE restoration_id=%s', (restoration_id,))
        total = cur.fetchone()['n']
        cur.execute('''SELECT c.*,b.filename AS origin_filename FROM source_attribute_changes c
            LEFT JOIN import_batches b ON b.id=c.origin_batch_id AND b.source_id=c.source_id
            WHERE c.restoration_id=%s ORDER BY c.target_row_id LIMIT %s OFFSET %s''', (restoration_id, limit, offset))
        return {'changes': [_jsonable(row) for row in cur.fetchall()], 'total': total}
