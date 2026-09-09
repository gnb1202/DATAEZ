"""Store-scoped source profiles and durable, idempotent file imports.

Whole-file retries and deterministic event review share one commit boundary.
Every mutation locks source -> batch; a successful result is replayed before
checking preview freshness. Object keys are reserved durably before writing.
"""
import hashlib
import json
from uuid import UUID, uuid4
import hmac

from pydantic import BaseModel, ConfigDict, Field

from .data_import import PreparedImport, prepare_import, validate_upload, write_import
from .db import _connect, get_user_table_name
from .exceptions import AppException, ResourceNotFound
from .import_validation import ImportValidationError, validate_type, issue
from .payment_imports import PaymentImportMapping, prepare_payment_import, prepare_payment_values, payment_schema
from .storage import StorageService
from . import event_review, ledger_baseline
from .ledger_guards import assert_unmanaged_table, lock_table_writes


class CreateSourceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=120)
    provider: str = Field(min_length=1, max_length=120)
    account: str = Field(min_length=1, max_length=120)
    feed: str = Field(min_length=1, max_length=120)
    mapping: PaymentImportMapping
    existing_table_id: UUID | None = None
    adoption_token: str | None = Field(default=None, max_length=64)
    accept_idless: bool = False


def conflict(code, message):
    return AppException(409, code, message)


def _public(row):
    return {k: v for k, v in row.items() if k not in {"storage_key", "physical_table_name", "user_id"}}


def _store(cur, user_id, project_id):
    cur.execute("SELECT id FROM projects WHERE id=%s AND user_id=%s AND deleted_at IS NULL FOR SHARE", (project_id, user_id))
    if not cur.fetchone():
        raise ResourceNotFound("가게")


def _source(cur, user_id, project_id, source_id):
    _store(cur, user_id, project_id)
    cur.execute("""SELECT s.*,t.columns_schema AS target_schema FROM ledger_sources s JOIN table_meta t ON t.id=s.table_id
        WHERE s.id=%s AND s.project_id=%s AND s.user_id=%s AND t.deleted_at IS NULL
        FOR UPDATE OF s""", (source_id, project_id, user_id))
    row = cur.fetchone()
    if not row:
        raise ResourceNotFound("출처")
    return row


def _batch(cur, user_id, project_id, batch_id):
    cur.execute("""SELECT b.source_id FROM import_batches b JOIN ledger_sources s ON s.id=b.source_id
        WHERE b.id=%s AND s.project_id=%s AND s.user_id=%s""", (batch_id, project_id, user_id))
    row = cur.fetchone()
    if not row:
        raise ResourceNotFound("업로드")
    source = _source(cur, user_id, project_id, row["source_id"])
    cur.execute("SELECT *, expires_at <= now() AS is_expired FROM import_batches WHERE id=%s FOR UPDATE", (batch_id,))
    return source, cur.fetchone()


def _active(batch):
    if batch["status"] == "expired" or batch["is_expired"]:
        raise conflict("batch_expired", "미반영 파일의 보관 기간(24시간)이 지났습니다. 같은 파일을 다시 업로드해주세요.")
    if batch["status"] == "staging":
        raise conflict("upload_incomplete", "파일 업로드가 완료되지 않았습니다. 같은 파일로 다시 시도해주세요.")


def _view(cur, source, batch, *, replayed=False, rows_added=0):
    cur.execute("""SELECT DISTINCT s.id AS source_id,s.name AS source_name FROM import_batches b
        JOIN ledger_sources s ON s.id=b.source_id JOIN table_meta t ON t.id=s.table_id
        WHERE b.content_hash=%s AND s.project_id=%s AND s.user_id=%s AND s.id<>%s
        AND t.deleted_at IS NULL AND b.status='committed' LIMIT 20""",
        (batch["content_hash"], source["project_id"], source["user_id"], source["id"]))
    return {**_public(batch), "table_id": source["table_id"], "source_name": source["name"],
            "replayed": replayed, "rows_added": rows_added, "same_file_sources": cur.fetchall(),
            "requires_reupload": batch['status'] != 'committed' and batch['rule_version'] != source['rule_version'],
            "deduplication_scope": "source_events_v1" if batch.get("review_version") == event_review.VERSION else "same_file_only"}


def create_source(user_id, project_id, request: CreateSourceRequest):
    # Validate mapping consistency even before the first file arrives.
    mapping = request.mapping.model_dump()
    selected = [v for k, v in mapping.items() if k.endswith("_column") and v is not None]
    if len(selected) != len(set(selected)):
        raise AppException(422, "invalid_mapping", "서로 다른 필드에 같은 컬럼을 연결할 수 없습니다.")
    with _connect() as conn, conn.cursor() as cur:
        _store(cur, user_id, project_id)
        # Serialize namespace creation, including concurrent retries before a
        # source row exists. Hash collisions only serialize unrelated creates.
        namespace = json.dumps([project_id, request.provider, request.account, request.feed])
        cur.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (namespace,))
        cur.execute("SELECT * FROM ledger_sources WHERE project_id=%s AND provider=%s AND account=%s AND feed=%s",
                    (project_id, request.provider, request.account, request.feed))
        existing = cur.fetchone()
        if existing:
            _file_source(existing)
            if (PaymentImportMapping.model_validate(existing["mapping"]).model_dump() != mapping or existing["name"] != request.name
                    or (request.existing_table_id and str(existing["table_id"]) != str(request.existing_table_id))):
                raise conflict("source_exists", "같은 제공자·계정·자료 종류의 출처가 있습니다. 기존 출처를 선택해주세요.")
            return _public(existing)
        source_id, table_id = str(uuid4()), str(request.existing_table_id or uuid4())
        table_name = get_user_table_name(user_id, table_id)
        if request.existing_table_id:
            report, records, expected = _adoption_check(cur, user_id, project_id, request)
            if not request.adoption_token or not hmac.compare_digest(expected, request.adoption_token):
                raise conflict("stale_baseline", "장부 내용이나 전환 설정이 변경되었습니다. 전체 기준점 검사를 다시 실행해주세요.")
            if not report["can_adopt"]:
                raise conflict("baseline_unresolved", "기존 장부의 중복·충돌 또는 후보를 확인해주세요.")
        else:
            schema = payment_schema(request.mapping)
            write_import(cur, table_name, PreparedImport(schema, [], []), create=True)
            cur.execute("""INSERT INTO table_meta(id,project_id,user_id,name,description,columns_schema,row_count)
                VALUES (%s,%s,%s,%s,%s,%s::jsonb,0)""",
                (table_id, project_id, user_id, request.name, "출처 업로드로 관리하는 원화 결제·취소 장부", json.dumps(schema)))
        cur.execute("""INSERT INTO ledger_sources(id,project_id,user_id,name,provider,account,feed,table_id,physical_table_name,mapping,event_index_version,storage_mode)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s) RETURNING *""",
            (source_id, project_id, user_id, request.name, request.provider, request.account, request.feed, table_id, table_name, json.dumps(mapping),
             event_review.VERSION, "original" if request.existing_table_id else "canonical"))
        result = _public(cur.fetchone())
        if request.existing_table_id:
            ledger_baseline.install(cur, source_id, records, report)
            cur.execute("UPDATE table_meta SET row_count=%s WHERE id=%s", (report["row_count"], table_id))
            cur.execute("SELECT * FROM ledger_sources WHERE id=%s", (source_id,))
            result = _public(cur.fetchone())
        conn.commit()
    return result


def _adoption_check(cur, user_id, project_id, request):
    if request.existing_table_id is None:
        raise AppException(422, "table_required", "전환할 기존 장부를 선택해주세요.")
    _store(cur, user_id, project_id)
    table_id = str(request.existing_table_id)
    cur.execute("SELECT id FROM table_meta WHERE id=%s AND project_id=%s AND user_id=%s AND deleted_at IS NULL", (table_id, project_id, user_id))
    if not cur.fetchone():
        raise ResourceNotFound("장부")
    table_name = get_user_table_name(user_id, table_id)
    assert_unmanaged_table(cur, table_name)
    cur.execute("SELECT columns_schema FROM table_meta WHERE id=%s AND deleted_at IS NULL FOR UPDATE", (table_id,))
    meta = cur.fetchone()
    if not meta:
        raise ResourceNotFound("장부")
    for column in meta["columns_schema"]:
        try:
            validate_type(column["type"])
        except ValueError as exc:
            raise ImportValidationError([issue(1, column["name"], "현재 파일 적재가 지원하는 컬럼 형식으로 변경한 뒤 전환해주세요.")]) from exc
    report, records = ledger_baseline.scan(cur, table_name, meta["columns_schema"], request.mapping,
                                            storage_mode="original", accept_idless=request.accept_idless)
    expected = ledger_baseline.token(user_id, table_id, request.model_dump(mode="json", exclude={"adoption_token"}), report)
    return report, records, expected


def preview_adoption(user_id, project_id, request):
    with _connect() as conn, conn.cursor() as cur:
        report, _, token = _adoption_check(cur, user_id, project_id, request)
        return {**report, "adoption_token": token}


def _file_source(source):
    if source.get('input_mode') == 'cash':
        raise conflict('cash_source_only', '현금 직접입력 장부는 현금 입력 화면에서 기록합니다.')


def baseline_source(user_id, project_id, source_id, accept_idless=False):
    with _connect() as conn, conn.cursor() as cur:
        source = _source(cur, user_id, project_id, source_id)
        _file_source(source)
        if source["event_index_version"] == event_review.VERSION:
            return {**(source["baseline_report"] or {}), "can_adopt": True, "already_verified": True}
        lock_table_writes(cur, source["physical_table_name"])
        report, records = ledger_baseline.scan(cur, source["physical_table_name"], source["target_schema"],
            PaymentImportMapping.model_validate(source["mapping"]), storage_mode=source["storage_mode"], accept_idless=accept_idless)
        if report["can_adopt"]:
            ledger_baseline.install(cur, source_id, records, report)
        else:
            cur.execute("UPDATE ledger_sources SET baseline_report=%s::jsonb WHERE id=%s", (json.dumps(report), source_id))
        conn.commit()
        return report


def _indexed(source):
    if source["event_index_version"] != event_review.VERSION:
        raise conflict("baseline_required", "기존 출처 장부의 전체 기준점 검사를 먼저 실행해주세요.")


def list_sources(user_id, project_id):
    with _connect() as conn, conn.cursor() as cur:
        _store(cur, user_id, project_id)
        cur.execute("""SELECT s.*,t.row_count,
            greatest(s.last_manual_entry_at,(SELECT max(b.committed_at) FROM import_batches b WHERE b.source_id=s.id AND b.status='committed')) AS last_committed_at
            FROM ledger_sources s JOIN table_meta t ON t.id=s.table_id
            WHERE s.project_id=%s AND s.user_id=%s AND t.deleted_at IS NULL ORDER BY s.created_at,s.id""", (project_id, user_id))
        return [_public(row) for row in cur.fetchall()]


def upload_batch(user_id, project_id, source_id, request_key, content, filename, storage: StorageService):
    validate_upload(content, filename)
    fingerprint = hashlib.sha256(content).hexdigest()
    # Commit a recoverable reservation BEFORE any nontransactional object write.
    with _connect() as conn, conn.cursor() as cur:
        source = _source(cur, user_id, project_id, source_id)
        _file_source(source)
        cur.execute("""SELECT b.* FROM import_requests r JOIN import_batches b ON b.id=r.batch_id
            WHERE r.source_id=%s AND r.request_key=%s""", (source_id, request_key))
        previous = cur.fetchone()
        if previous and previous['content_hash'] == fingerprint and previous['status'] == 'committed':
            # A rule upgrade must not turn a successful old request retry into
            # a new import or an idempotency error.
            return _view(cur, source, previous, replayed=True)
        if previous and (previous["content_hash"] != fingerprint or previous["rule_version"] != source["rule_version"]):
            raise conflict("idempotency_mismatch", "이미 사용한 요청 키에 다른 파일을 보낼 수 없습니다. 새 파일 업로드로 시작해주세요.")
        cur.execute("""SELECT * FROM import_batches WHERE source_id=%s AND content_hash=%s
            AND sheet_index=0 AND rule_version=%s""", (source_id, fingerprint, source["rule_version"]))
        batch = cur.fetchone()
        if not batch:
            batch_id = str(uuid4())
            cur.execute("""INSERT INTO import_batches(id,source_id,storage_key,filename,size_bytes,content_hash,rule_version,status)
                VALUES (%s,%s,%s,%s,%s,%s,%s,'staging') RETURNING *""",
                (batch_id, source_id, storage.staged_key(batch_id), filename, len(content), fingerprint, source["rule_version"]))
            batch = cur.fetchone()
        if not previous:
            cur.execute("INSERT INTO import_requests(source_id,request_key,batch_id) VALUES (%s,%s,%s)", (source_id, request_key, batch["id"]))
        batch_id = batch["id"]
        conn.commit()
    with _connect() as conn, conn.cursor() as cur:
        source, batch = _batch(cur, user_id, project_id, batch_id)
        if batch["status"] == "committed":
            return _view(cur, source, batch, replayed=True)
        if batch["status"] not in {"staging", "expired"} and not batch["is_expired"]:
            return _view(cur, source, batch)
        # Shared source/batch locks serialize upload, preview, commit and expiry.
        # A crash after write leaves the durable reservation for retry/cleanup.
        storage.write_staged(batch["storage_key"], content)
        cur.execute("DELETE FROM import_rows WHERE batch_id=%s", (batch_id,))
        # Pending objects stay out of the general files/conversations API.
        # Publish file metadata only in the final ledger commit transaction.
        cur.execute("""UPDATE import_batches SET status='uploaded',expires_at=now()+interval '24 hours',
            preview_token=NULL,preview_revision=NULL,summary=NULL,error=NULL,review_version=0 WHERE id=%s RETURNING *""", (batch_id,))
        result = _view(cur, source, cur.fetchone())
        conn.commit()
    return result


def _prepare(batch, source, storage):
    content = storage.read_staged(batch["storage_key"])
    if hashlib.sha256(content).hexdigest() != batch["content_hash"]:
        raise conflict("file_changed", "보관된 파일의 내용이 변경되었습니다. 관리자에게 문의해주세요.")
    mapping = PaymentImportMapping.model_validate(source["mapping"])
    if source["storage_mode"] == "original":
        target = prepare_import(content, batch["filename"], source["target_schema"])
        canonical = prepare_payment_values([c["name"] for c in target.columns_schema], target.rows, target.row_numbers, mapping)
        return canonical, target
    canonical = prepare_payment_import(content, batch["filename"], mapping)
    return canonical, canonical


def preview_batch(user_id, project_id, batch_id, storage):
    with _connect() as conn, conn.cursor() as cur:
        source, batch = _batch(cur, user_id, project_id, batch_id)
        if batch["status"] == "committed":
            return _view(cur, source, batch, replayed=True)
        _active(batch)
        if batch['rule_version'] != source['rule_version']:
            raise conflict('mapping_changed', '출처에 속성이 추가되었습니다. 같은 파일을 새로 업로드해 검사해주세요.')
        _indexed(source)
        try:
            prepared, _ = _prepare(batch, source, storage)
        except ImportValidationError as exc:
            cur.execute("DELETE FROM import_rows WHERE batch_id=%s", (batch_id,))
            cur.execute("""UPDATE import_batches SET status='failed',preview_token=NULL,summary=NULL,error=%s::jsonb WHERE id=%s""",
                        (json.dumps({"detail": exc.detail, "issues": exc.issues}), batch_id))
            conn.commit()
            raise
        reviewed = event_review.classify(cur, source, batch, prepared)
        event_review.save_review(cur, source["id"], batch_id, reviewed)
        summary = event_review.summarize(reviewed)
        status = "failed" if summary["counts"]["conflict"] else "ready"
        cur.execute("""UPDATE import_batches SET status=%s,preview_token=%s,preview_revision=%s,summary=%s::jsonb,
            review_version=%s,error=NULL WHERE id=%s RETURNING *""", (status, str(uuid4()), source["data_revision"], json.dumps(summary), event_review.VERSION, batch_id))
        result = _view(cur, source, cur.fetchone())
        conn.commit()
    return result


def commit_batch(user_id, project_id, batch_id, preview_token, storage):
    with _connect() as conn, conn.cursor() as cur:
        source, batch = _batch(cur, user_id, project_id, batch_id)
        if batch["status"] == "committed":
            return _view(cur, source, batch, replayed=True)
        _active(batch)
        _indexed(source)
        if (batch["status"] != "ready" or str(batch["preview_token"]) != str(preview_token)
                or batch["preview_revision"] != source["data_revision"] or batch["rule_version"] != source["rule_version"]
                or batch["review_version"] != event_review.VERSION):
            raise conflict("stale_preview", "출처 데이터 또는 미리보기가 변경되었습니다. 미리보기를 다시 확인해주세요.")
        prepared, target = _prepare(batch, source, storage)
        reviewed = event_review.read_review(cur, batch_id)
        # Recompute classifications from the immutable original and current
        # registry, then require the reviewed content and decisions to match.
        current = event_review.classify(cur, source, batch, prepared)
        proof = lambda rows: [(r["row_number"], r["content_hash"], r["classification"], event_review.digest(r.get("matched"))) for r in rows]
        if proof(current) != proof(reviewed):
            raise conflict("stale_review", "거래 판정이 변경되었습니다. 미리보기를 다시 실행해주세요.")
        summary = event_review.summarize(reviewed)
        if not summary["can_commit"]:
            raise conflict("review_unresolved", "충돌 또는 결정하지 않은 중복 후보가 있습니다.")
        file_id = str(uuid4())
        cur.execute("INSERT INTO files(id,user_id,filename,storage_key,size_bytes) VALUES (%s,%s,%s,%s,%s)",
                    (file_id, user_id, batch["filename"], batch["storage_key"], batch["size_bytes"]))
        count = event_review.write_events(cur, source, batch, reviewed, target)
        cur.execute("""UPDATE table_meta SET row_count=row_count+%s,source_file_id=COALESCE(source_file_id,%s),updated_at=now()
            WHERE id=%s RETURNING row_count""", (count, file_id, source["table_id"]))
        total = cur.fetchone()["row_count"]
        cur.execute("UPDATE ledger_sources SET data_revision=data_revision+1 WHERE id=%s RETURNING data_revision", (source["id"],))
        revision = cur.fetchone()["data_revision"]
        saved_result = {"rows_inserted": count, "total_row_count": total, "amount": summary["amount"],
                        "duplicates_skipped": summary["counts"]["duplicate"], "candidates_excluded": summary["counts"]["excluded"],
                        "amounts": summary["amounts"], "currency": "KRW", "data_revision": revision, "table_id": str(source["table_id"])}
        cur.execute("""UPDATE import_batches SET status='committed',file_id=%s,result=%s::jsonb,committed_at=now(),error=NULL
            WHERE id=%s RETURNING *""", (file_id, json.dumps(saved_result), batch_id))
        result = _view(cur, source, cur.fetchone(), rows_added=count)
        conn.commit()
    return result


def decide_rows(user_id, project_id, batch_id, preview_token, decisions):
    with _connect() as conn, conn.cursor() as cur:
        source, batch = _batch(cur, user_id, project_id, batch_id)
        if batch["status"] == "committed":
            return _view(cur, source, batch, replayed=True)
        _active(batch)
        _indexed(source)
        if (str(batch["preview_token"]) != str(preview_token) or batch["preview_revision"] != source["data_revision"]
                or batch["review_version"] != event_review.VERSION or batch["status"] != "ready"
                or batch['rule_version'] != source['rule_version']):
            raise conflict("stale_preview", "미리보기가 변경되었습니다. 다시 확인해주세요.")
        reviewed = event_review.read_review(cur, batch_id)
        by_number = {r["row_number"]: r for r in reviewed}
        if len({d.row_number for d in decisions}) != len(decisions):
            raise AppException(422, "duplicate_decision", "같은 행을 여러 번 결정할 수 없습니다.")
        for decision in decisions:
            row = by_number.get(decision.row_number)
            if row is None or row["classification"] != "candidate":
                raise AppException(422, "invalid_decision", "이 배치의 중복 후보 행만 포함·제외할 수 있습니다.")
            row["decision"] = decision.decision
        # A repeated candidate key must still obey confirmed-key uniqueness.
        included = [event_review.event_key(r["normalized"]) for r in reviewed
                    if r["classification"] == "new" or r["decision"] == "include"]
        included = [key for key in included if key is not None]
        if len(included) != len(set(included)):
            raise conflict("candidate_key_repeated", "같은 이벤트 ID의 후보는 한 행만 포함해주세요.")
        for decision in decisions:
            cur.execute("UPDATE import_rows SET decision=%s WHERE batch_id=%s AND row_number=%s", (decision.decision, batch_id, decision.row_number))
        summary = event_review.summarize(reviewed)
        cur.execute("UPDATE import_batches SET summary=%s::jsonb,preview_token=%s WHERE id=%s RETURNING *",
                    (json.dumps(summary), str(uuid4()), batch_id))
        result = _view(cur, source, cur.fetchone())
        conn.commit()
        return result


def list_rows(user_id, project_id, batch_id, classification=None, limit=50, offset=0):
    with _connect() as conn, conn.cursor() as cur:
        _, batch = _batch(cur, user_id, project_id, batch_id)
        params = [batch_id]
        where = "batch_id=%s"
        if classification:
            where += " AND classification=%s"
            params.append(classification)
        cur.execute(f"SELECT count(*) AS n FROM import_rows WHERE {where}", params)
        total = cur.fetchone()["n"]
        cur.execute(f"SELECT row_number,normalized,classification,reason,matched,decision,target_row_id FROM import_rows WHERE {where} ORDER BY row_number LIMIT %s OFFSET %s", params + [limit, offset])
        return {"rows": cur.fetchall(), "total": total, "preview_token": batch["preview_token"], "status": batch["status"],
                "batch": {key: batch[key] for key in ("id", "source_id", "filename", "status", "summary", "result", "error", "created_at", "committed_at")}}


def get_batch(user_id, project_id, batch_id):
    with _connect() as conn, conn.cursor() as cur:
        source, batch = _batch(cur, user_id, project_id, batch_id)
        return _view(cur, source, batch)


def list_batches(user_id, project_id, source_id, limit=20, offset=0):
    with _connect() as conn, conn.cursor() as cur:
        source = _source(cur, user_id, project_id, source_id)
        cur.execute("SELECT count(*) AS n FROM import_batches WHERE source_id=%s", (source_id,))
        total = cur.fetchone()["n"]
        cur.execute("""SELECT * FROM import_batches WHERE source_id=%s ORDER BY created_at DESC,id DESC LIMIT %s OFFSET %s""",
                    (source_id, limit, offset))
        return {"batches": [{**_public(row), "table_id": source["table_id"]} for row in cur.fetchall()], "total": total}


def expire_pending_batches(storage, limit=20):
    # One source -> batch transaction per object, including deleted stores.
    # Retain committed originals indefinitely; retries keep the same batch id.
    with _connect() as conn, conn.cursor() as cur:
        cur.execute("""SELECT id,source_id FROM import_batches WHERE status NOT IN ('committed','expired')
            AND expires_at<=now() ORDER BY expires_at LIMIT %s""", (limit,))
        candidates = cur.fetchall()
    expired = 0
    for candidate in candidates:
        with _connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT id FROM ledger_sources WHERE id=%s FOR UPDATE SKIP LOCKED", (candidate["source_id"],))
            if not cur.fetchone():
                continue
            cur.execute("""SELECT * FROM import_batches WHERE id=%s AND status NOT IN ('committed','expired')
                AND expires_at<=now() FOR UPDATE""", (candidate["id"],))
            batch = cur.fetchone()
            if not batch:
                continue
            storage.delete_staged(batch["storage_key"])
            cur.execute("DELETE FROM import_rows WHERE batch_id=%s", (batch["id"],))
            cur.execute("""UPDATE import_batches SET status='expired',file_id=NULL,preview_token=NULL,summary=NULL,error=NULL WHERE id=%s""", (batch["id"],))
            if batch["file_id"]:
                cur.execute("DELETE FROM files WHERE id=%s", (batch["file_id"],))
            conn.commit()
            expired += 1
    return expired
