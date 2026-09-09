"""Explicit, non-destructive baseline checks for existing physical ledgers."""
import hmac
import json
from hashlib import sha256

from psycopg import sql

from .config import settings
from .exceptions import AppException
from .event_review import VERSION, digest, normalize, event_key, signature
from .import_validation import ImportValidationError, parse_decimal, issue
from .payment_imports import PaymentImportMapping, prepare_payment_values, payment_schema

MAX_BASELINE_ROWS = 100000


def scan(cur, table_name, schema, mapping, *, storage_mode, accept_idless=False):
    cur.execute(sql.SQL("SELECT * FROM {} ORDER BY _row_id LIMIT %s").format(sql.Identifier(table_name)), (MAX_BASELINE_ROWS + 1,))
    raw = cur.fetchall()
    if len(raw) > MAX_BASELINE_ROWS:
        raise AppException(422, "baseline_too_large", "기준점 검사는 한 번에 100,000행까지 지원합니다.")
    columns = [c["name"] for c in schema]
    locations = [r["_row_id"] for r in raw]
    if storage_mode == "original":
        prepared = prepare_payment_values(columns, [[r.get(c) for c in columns] for r in raw], locations, mapping)
        events = [normalize(row, prepared.columns_schema) for row in prepared.rows]
    else:
        canonical_schema = payment_schema(mapping)
        canonical = [c["name"] for c in canonical_schema]
        events = []
        for row in raw:
            try:
                if row["event_kind"] not in {"payment", "refund"} or row["currency"] != "KRW":
                    raise ValueError("결제·취소 종류와 KRW 통화를 확인해주세요.")
                amount = parse_decimal(row["amount"])
                if (row["event_kind"] == "payment" and amount < 0) or (row["event_kind"] == "refund" and amount > 0):
                    raise ValueError("결제·취소 종류와 금액 부호가 일치하지 않습니다.")
                if row["occurred_at"] is None:
                    raise ValueError("발생일시가 비어 있습니다.")
                for name in ("event_id", "original_event_id"):
                    if row[name] is not None and (not isinstance(row[name], str) or not row[name].strip()):
                        raise ValueError("이벤트 ID는 비어 있지 않은 문자열 또는 NULL이어야 합니다.")
                events.append(normalize(tuple(row[c] for c in canonical), canonical_schema))
            except (ValueError, TypeError, KeyError) as exc:
                raise ImportValidationError([issue(row["_row_id"], "", str(exc))]) from exc
    keyed, similar, problems = {}, {}, []
    counts = {"duplicate": 0, "conflict": 0, "candidate": 0}
    records = []
    for row_id, event in zip(locations, events):
        key, content_hash, candidate_hash = event_key(event), digest(event), signature(event)
        record = {"target_row_id": row_id, "normalized": event, "content_hash": content_hash, "candidate_hash": candidate_hash}
        prior = keyed.get(key) if key is not None else None
        if prior:
            classification = "duplicate" if prior["content_hash"] == content_hash else "conflict"
            counts[classification] += 1
            problems.append({"row_number": row_id, "classification": classification, "matched_row": prior["target_row_id"]})
        else:
            match = next((r for r in similar.get(candidate_hash, []) if key is None or event_key(r["normalized"]) is None), None)
            if match:
                counts["candidate"] += 1
                problems.append({"row_number": row_id, "classification": "candidate", "matched_row": match["target_row_id"]})
        if key is not None:
            keyed.setdefault(key, record)
        similar.setdefault(candidate_hash, []).append(record)
        records.append(record)
    report = {"row_count": len(raw), "counts": counts, "issues": problems[:50], "issues_truncated": len(problems) > 50,
              "accept_idless": accept_idless, "can_adopt": not(counts["duplicate"] or counts["conflict"] or (counts["candidate"] and not accept_idless)),
              "fingerprint": digest({"schema": schema, "rows": raw}) if not raw else
                  digest({"schema": schema, "rows": [{k: str(v) if v is not None else None for k, v in r.items()} for r in raw]})}
    return report, records


def token(user_id, table_id, request, report):
    message = digest([str(user_id), str(table_id), request, report["fingerprint"], VERSION])
    return hmac.new(settings.jwt_secret_key.encode(), message.encode(), sha256).hexdigest()


def install(cur, source_id, records, report):
    if not report["can_adopt"]:
        raise AppException(409, "baseline_unresolved", "기존 장부의 중복·충돌 또는 미확인 후보를 해결한 뒤 전환해주세요.")
    if records:
        cur.executemany("""INSERT INTO source_events(source_id,target_row_id,event_kind,event_id,event_key_hash,normalized,
            content_hash,candidate_hash,first_row_number) VALUES (%s,%s,%s,%s,%s,%s::jsonb,%s,%s,%s)""",
            [(source_id, r["target_row_id"], r["normalized"]["event_kind"], r["normalized"]["event_id"],
              digest(event_key(r["normalized"])) if event_key(r["normalized"]) is not None else None,
              json.dumps(r["normalized"]), r["content_hash"], r["candidate_hash"], r["target_row_id"]) for r in records])
    cur.execute("""UPDATE ledger_sources SET event_index_version=%s,baseline_at=now(),baseline_report=%s::jsonb,
        data_revision=data_revision+1 WHERE id=%s""", (VERSION, json.dumps(report), source_id))
