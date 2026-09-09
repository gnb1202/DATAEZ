"""Read a bounded, owner-scoped catalog snapshot for schema retrieval."""
from psycopg import sql

from .config import settings
from .db import get_user_table_name


def schema_snapshot(cur, user_id, project_id, table_id, *, lock=False):
    cur.execute("SELECT set_config('statement_timeout',%s,true)", (str(settings.query_timeout_ms),))
    cur.execute("""SELECT t.*,f.filename AS original_filename,s.id AS source_id,
                s.name AS source_name,s.provider,s.feed,s.mapping,s.data_revision,s.storage_mode,s.input_mode
        FROM table_meta t JOIN projects p ON p.id=t.project_id AND p.user_id=t.user_id
        LEFT JOIN files f ON f.id=t.source_file_id AND f.user_id=t.user_id
        LEFT JOIN ledger_sources s ON s.table_id=t.id AND s.project_id=t.project_id AND s.user_id=t.user_id
        WHERE t.id=%s AND t.user_id=%s AND t.project_id=%s
          AND t.deleted_at IS NULL AND p.deleted_at IS NULL AND to_jsonb(t)->>'original_file_id' IS NULL""" + (" FOR UPDATE OF t FOR SHARE OF p" if lock else ""),
        (table_id, user_id, project_id))
    meta = cur.fetchone()
    if not meta:
        return None
    meta = dict(meta)
    filenames = [meta['original_filename']] if meta.get('original_filename') else []
    if meta.get('source_id'):
        cur.execute("""SELECT filename FROM import_batches WHERE source_id=%s AND status='committed'
                       ORDER BY committed_at DESC,id DESC LIMIT 20""", (meta['source_id'],))
        filenames.extend(r['filename'] for r in cur.fetchall())
    meta['filenames'] = list(dict.fromkeys(filenames))
    columns = meta.get('columns_schema') or []
    candidates = [c for c in columns if c['type'].upper() in {'DATE', 'TIMESTAMP', 'TIMESTAMPTZ'}]
    if candidates:
        mapped = (meta.get('mapping') or {}).get('occurred_at_column')
        chosen = next((c for c in candidates if c['name'] == mapped), None)
        chosen = chosen or next((c for c in candidates if c['name'] == 'occurred_at'), candidates[0])
        column = sql.Identifier(chosen['name'])
        local = sql.SQL("({} AT TIME ZONE 'Asia/Seoul')").format(column) if chosen['type'].upper() == 'TIMESTAMPTZ' else column
        cur.execute(sql.SQL("SELECT min({})::date AS first_day,max({})::date AS last_day FROM {}").format(
            local, local, sql.Identifier(get_user_table_name(user_id, table_id))))
        meta['coverage'] = {**cur.fetchone(), 'column': chosen['name']}
    return meta


def catalog_lines(meta):
    lines = []
    if meta.get('source_id'):
        lines.extend([f"연결 출처: {meta['source_name']} / 제공자: {meta['provider']} / 자료 종류: {meta['feed']}",
                      f"반영 버전: {meta['data_revision']}"])
        if meta.get('input_mode') == 'cash':
            lines.append('현금 직접입력 장부. occurred_at는 입력한 거래 일자를 한국시간 자정으로 저장한 값이며 실제 거래 시각이 아니다. 시간대 분석을 할 수 없다. 메모는 현금 입력 이력에서 조회한다.')
        # Explicit mapping semantics, not guesses based on a generic column name.
        mapping = meta.get('mapping') or {}
        lines.append(f"원본 금액 컬럼: {mapping.get('amount_column')}; 발생일 컬럼: {mapping.get('occurred_at_column')}")
        for name, label in [('payment_method', '결제수단'), ('channel', '판매채널'), ('fee', 'PG 수수료')]:
            original = mapping.get(name + '_column')
            if original:
                stored = original if meta.get('storage_mode') == 'original' else name
                lines.append(f'{label}: {stored} (원본 {original}). 빈칸은 미제공이며 0이나 다른 분류로 추정하지 않는다.')
        if mapping.get('fee_column'):
            lines.append('PG 수수료는 원본 부호를 보존한다. 취소 시 수수료 환급 여부는 별개이며, 수수료 차감액은 순결제액·실제 입금액·순이익과 다르다.')
        if {c['name'] for c in meta.get('columns_schema', [])} >= {'event_kind', 'amount', 'occurred_at'}:
            lines.extend(['결제 이벤트 원장: 승인 payment, 취소·환불 refund, 거래번호 event_id, 원거래 original_event_id.',
                          'amount는 원화 결제금액. signed 방식은 양수 승인과 음수 취소를 합산한 순결제액.',
                          'occurred_at는 결제·취소 발생일시이며 정산 입금일이 아니다.'])
    if meta.get('filenames'):
        lines.append('원본 파일 (최근 최대 20개): ' + ', '.join(str(n)[:200] for n in meta['filenames']))
    coverage = meta.get('coverage')
    if coverage and coverage.get('first_day') is not None:
        lines.append(f"데이터 기간 (한국 시간, {coverage['column']}): {coverage['first_day']} ~ {coverage['last_day']}")
    return lines
