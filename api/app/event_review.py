"""Deterministic event comparison and provenance, independent of LLM output."""
import hashlib
import json
from datetime import datetime, timezone
from decimal import Decimal, localcontext
from zoneinfo import ZoneInfo

from psycopg import sql

from .exceptions import AppException

VERSION = 1


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def decimal_text(value):
    number = Decimal(value)
    if not number.is_finite():
        raise ValueError("금액은 유한한 숫자여야 합니다.")
    if not number:
        return "0"
    text = format(number, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def normalize(row, schema=None):
    from .payment_imports import ATTRIBUTE_TYPES, payment_schema
    values = dict(zip((c["name"] for c in (schema or payment_schema())), row, strict=True))
    event_id, original_id, kind, amount, occurred_at, currency = (values[c["name"]] for c in payment_schema())
    instant = datetime.fromisoformat(str(occurred_at))
    if instant.tzinfo is None:
        instant = instant.replace(tzinfo=ZoneInfo("Asia/Seoul"))
    event = {"event_id": event_id, "original_event_id": original_id, "event_kind": kind,
            "amount": decimal_text(amount), "occurred_at": instant.astimezone(timezone.utc).isoformat(), "currency": currency}
    # Omit unknown attributes: six-field historical events keep their hashes.
    # A real value (including fee=0) participates in conflict detection.
    for name in ATTRIBUTE_TYPES:
        if values.get(name) is not None:
            event[name] = decimal_text(values[name]) if name == "fee" else values[name]
    return event


def signature(event):
    local_day = datetime.fromisoformat(event["occurred_at"]).astimezone(ZoneInfo("Asia/Seoul")).date().isoformat()
    return digest([event["event_kind"], event["currency"], event["amount"], local_day])


def event_key(event):
    return (event["event_kind"], event["event_id"]) if event["event_id"] is not None else None


def reference(record):
    return {"batch_id": str(record["first_batch_id"]) if record.get("first_batch_id") else None,
            "filename": record.get("filename") or "기존 장부 기준점",
            "row_number": record["first_row_number"], "target_row_id": record.get("target_row_id"),
            "normalized": record["normalized"]}


def classify(cur, source, batch, prepared):
    events = [normalize(row, prepared.columns_schema) for row in prepared.rows]
    ids = list({digest(event_key(e)) for e in events if event_key(e) is not None})
    hashes = list({signature(e) for e in events})
    existing = []
    # Bounded parameter arrays and indexed lookups instead of scanning the
    # entire historical ledger or sending one SQL query for each input row.
    for offset in range(0, max(len(ids), len(hashes)), 1000):
        cur.execute("""SELECT e.*,b.filename FROM source_events e LEFT JOIN import_batches b ON b.id=e.first_batch_id
            WHERE e.source_id=%s AND (e.event_key_hash=ANY(%s::bpchar[]) OR e.candidate_hash=ANY(%s::bpchar[]))""",
            (source["id"], ids[offset:offset + 1000], hashes[offset:offset + 1000]))
        existing.extend(cur.fetchall())
    keyed, similar = {}, {}
    for record in {r["target_row_id"]: r for r in existing}.values():
        key = event_key(record["normalized"])
        if key is not None:
            keyed[key] = record
        similar.setdefault(record["candidate_hash"], []).append(record)
    # Detect all conflicting variants in the input before choosing a first row.
    variants = {}
    for row_number, event in zip(prepared.row_numbers, events):
        key = event_key(event)
        if key is not None:
            variants.setdefault(key, {}).setdefault(digest(event), {"normalized": event,
                "first_batch_id": batch["id"], "filename": batch["filename"], "first_row_number": row_number})
    reviewed = []
    for row_number, event in zip(prepared.row_numbers, events):
        key, content_hash, candidate_hash = event_key(event), digest(event), signature(event)
        match = keyed.get(key) if key is not None else None
        kind, reason, matched = "new", "새 이벤트입니다.", None
        if key is not None and len(variants[key]) > 1:
            kind, reason = "conflict", "같은 파일에 같은 이벤트 ID의 서로 다른 내용이 있습니다."
            matched = reference(next(record for fingerprint, record in variants[key].items() if fingerprint != content_hash))
        elif match:
            matched = reference(match)
            if match["content_hash"] == content_hash:
                kind, reason = "duplicate", "같은 이벤트 ID와 계산 내용이 이미 있습니다."
            else:
                kind, reason = "conflict", "같은 이벤트 ID의 금액·일시·원거래·결제수단·채널·수수료 등 내용이 다릅니다."
        else:
            candidates = similar.get(candidate_hash, [])
            match = next((r for r in candidates if key is None or r["normalized"]["event_id"] is None), None)
            if match:
                kind, reason, matched = "candidate", "ID가 없는 거래와 종류·한국 날짜·금액·통화가 같습니다. 자동 제외하지 않습니다.", reference(match)
        reviewed.append({"row_number": row_number, "normalized": event, "content_hash": content_hash,
                         "candidate_hash": candidate_hash, "classification": kind, "reason": reason,
                         "matched": matched, "decision": None, "target_row_id": None})
        # Candidates cannot become confirmed duplicates: their include/exclude
        # decision has not been made. Later occurrences stay candidates too.
        record = {"normalized": event, "content_hash": content_hash, "first_batch_id": batch["id"],
                  "first_row_number": row_number, "filename": batch["filename"], "target_row_id": None}
        if kind == "new" and key is not None:
            keyed[key] = record
        if kind in {"new", "candidate"}:
            similar.setdefault(candidate_hash, []).append(record)
    return reviewed


def save_review(cur, source_id, batch_id, rows):
    cur.execute("DELETE FROM import_rows WHERE batch_id=%s", (batch_id,))
    if rows:
        cur.executemany("""INSERT INTO import_rows(batch_id,source_id,row_number,normalized,content_hash,candidate_hash,
            classification,reason,matched) VALUES (%s,%s,%s,%s::jsonb,%s,%s,%s,%s,%s::jsonb)""",
            [(batch_id, source_id, r["row_number"], json.dumps(r["normalized"]), r["content_hash"], r["candidate_hash"],
              r["classification"], r["reason"], json.dumps(r["matched"]) if r["matched"] else None) for r in rows])


def read_review(cur, batch_id):
    cur.execute("SELECT * FROM import_rows WHERE batch_id=%s ORDER BY row_number", (batch_id,))
    return cur.fetchall()


def summarize(rows):
    counts = {key: 0 for key in ("new", "duplicate", "candidate", "conflict", "included", "excluded", "unresolved")}
    amounts = {key: Decimal(0) for key in ("total", "included", "duplicate", "excluded")}
    values = [Decimal(r["normalized"]["amount"]) for r in rows]
    with localcontext() as ctx:
        integer_digits = max((max(1, n.adjusted() + 1) for n in values), default=1)
        scale = max((max(0, -n.as_tuple().exponent) for n in values), default=0)
        ctx.prec = integer_digits + scale + len(str(len(rows))) + 2
        for row, amount in zip(rows, values):
            kind, decision = row["classification"], row.get("decision")
            counts[kind] += 1
            amounts["total"] += amount
            if kind == "new" or (kind == "candidate" and decision == "include"):
                counts["included"] += 1
                amounts["included"] += amount
            if kind == "duplicate":
                amounts["duplicate"] += amount
            if decision == "exclude":
                counts["excluded"] += 1
                amounts["excluded"] += amount
            if kind == "candidate" and decision is None:
                counts["unresolved"] += 1
    return {"row_count": len(rows), "counts": counts, "amount": str(amounts["included"]),
            "amounts": {k: str(v) for k, v in amounts.items()}, "currency": "KRW",
            "can_commit": not (counts["conflict"] or counts["unresolved"]),
            "sample": [{"row": r["row_number"], **r["normalized"], "classification": r["classification"]} for r in rows[:5]],
            "deduplication_scope": "source_events_v1"}


def write_events(cur, source, batch, reviewed, target):
    """Insert selected physical rows and exact RETURNING ids, then provenance."""
    selected = [r for r in reviewed if r["classification"] == "new" or r.get("decision") == "include"]
    physical_rows = dict(zip(target.row_numbers, target.rows))
    seen_keys = set()
    for r in selected:
        key = event_key(r["normalized"])
        if key is not None and key in seen_keys:
            raise AppException(409, "candidate_key_repeated", "같은 이벤트 ID의 후보를 두 번 포함할 수 없습니다. 한 행만 포함해주세요.")
        if key is not None:
            seen_keys.add(key)
    if selected:
        identifier = lambda name: sql.Identifier(name.replace("%", "%%"))
        query = sql.SQL("INSERT INTO {} ({}) VALUES ({}) RETURNING _row_id").format(identifier(source["physical_table_name"]),
            sql.SQL(",").join(identifier(c["name"]) for c in target.columns_schema),
            sql.SQL(",").join(sql.Placeholder() for _ in target.columns_schema))
        cur.executemany(query, [physical_rows[r["row_number"]] for r in selected], returning=True)
        for index, row in enumerate(selected):
            row["target_row_id"] = cur.fetchone()["_row_id"]
            if index + 1 < len(selected):
                cur.nextset()
        cur.executemany("""INSERT INTO source_events(source_id,target_row_id,event_kind,event_id,event_key_hash,normalized,
            content_hash,candidate_hash,first_batch_id,first_row_number) VALUES (%s,%s,%s,%s,%s,%s::jsonb,%s,%s,%s,%s)""",
            [(source["id"], r["target_row_id"], r["normalized"]["event_kind"], r["normalized"]["event_id"],
              digest(event_key(r["normalized"])) if event_key(r["normalized"]) is not None else None,
              json.dumps(r["normalized"]), r["content_hash"], r["candidate_hash"], batch["id"], r["row_number"]) for r in selected])
    row_ids = {r["row_number"]: r["target_row_id"] for r in selected}
    for row in reviewed:
        match = row.get("matched")
        if row["classification"] == "duplicate" and match:
            row["target_row_id"] = (row_ids.get(match["row_number"]) if str(match["batch_id"]) == str(batch["id"])
                                     else match["target_row_id"])
    if reviewed:
        cur.executemany("UPDATE import_rows SET target_row_id=%s WHERE batch_id=%s AND row_number=%s",
                        [(r["target_row_id"], batch["id"], r["row_number"]) for r in reviewed])
    return len(selected)
