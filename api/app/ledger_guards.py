"""Managed ledgers are immutable through generic REST and agent write paths."""
from .exceptions import AppException


def lock_table_writes(cur, table_name: str):
    cur.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", ("ledger-write:" + table_name,))


def assert_unmanaged_table(cur, table_name: str):
    # Adoption holds the same transaction lock through baseline validation and
    # source insertion. A generic writer must recheck after that commit.
    lock_table_writes(cur, table_name)
    assert_not_original(cur, table_name)
    cur.execute("SELECT id FROM ledger_sources WHERE physical_table_name=%s", (table_name,))
    if cur.fetchone():
        raise AppException(409, "managed_ledger", "출처로 관리하는 장부입니다. 출처 업로드 화면에서 파일을 반영해주세요. 직접 수정·삭제는 지원하지 않습니다.")


def assert_not_original(cur, table_name):
    cur.execute("""SELECT id FROM table_meta t WHERE to_jsonb(t)->>'original_file_id' IS NOT NULL
        AND 'ut_' || left(replace(user_id::text,'-',''),8) || '_' || left(replace(id::text,'-',''),8) = %s""", (table_name,))
    if cur.fetchone():
        raise AppException(409, "original_file_readonly", "파일 원본 분석 자료는 읽기 전용입니다. 새 거래는 누적 장부에 반영해주세요.")
