"""File import in three stages: raw read, full validation, transactional write."""
import csv
import io
import re
from dataclasses import dataclass
from typing import Any

import pandas as pd
from psycopg import sql

from .config import settings
from .db import _connect
from .exceptions import FileTooLarge, UnsupportedFileType
from .import_validation import (
    ImportValidationError, cast_value as _cast_value, identifier_column,
    issue, numeric_dimensions, parse_decimal, validate_type,
)


def validate_upload(content: bytes, filename: str):
    if not filename.lower().endswith((".csv", ".xlsx", ".xls")):
        raise UnsupportedFileType(filename)
    if len(content) > settings.max_upload_size_mb * 1024 * 1024:
        raise FileTooLarge(settings.max_upload_size_mb)
    if not content or not content.strip():
        raise ImportValidationError([issue(1, "", "파일이 비어 있습니다.")])


def _sanitize_column_name(name: str) -> str:
    name = re.sub(r"[^a-zA-Z0-9가-힣_]", "_", name.strip())
    name = re.sub(r"^[0-9]+", "", name)
    return re.sub(r"_+", "_", name).strip("_").lower() or "col"


def _column_names(headers) -> list[str]:
    used = {"_row_id"}
    result = []
    for header in headers:
        base = _sanitize_column_name(str(header))
        # PostgreSQL truncates identifiers to 63 bytes; reserve suffix space.
        base = base.encode("utf-8")[:54].decode("utf-8", errors="ignore")
        name, suffix = base, 0
        while name in used:
            suffix += 1
            name = f"{base}_{suffix}"
        used.add(name)
        result.append(name)
    return result


def _load_dataframe(content: bytes, filename: str) -> pd.DataFrame:
    validate_upload(content, filename)
    if filename.lower().endswith((".xlsx", ".xls")):
        from .import_excel import read_excel
        return read_excel(content, filename)
    decoded = None
    for encoding in ("utf-8-sig", "cp949", "euc-kr"):
        try:
            decoded = content.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    if decoded is None:
        raise ImportValidationError([issue(1, "", "UTF-8 또는 CP949 인코딩의 CSV를 사용해주세요.")])
    reader = csv.reader(io.StringIO(decoded, newline=""), strict=True)
    rows, row_numbers = [], []
    try:
        headers = next(reader)
        if not headers or any(not h.strip() for h in headers):
            raise ImportValidationError([issue(1, "", "모든 컬럼에 이름이 필요합니다.")])
        while True:
            line = reader.line_num + 1
            try:
                row = next(reader)
            except StopIteration:
                break
            if not row:
                continue
            if len(row) != len(headers):
                raise ImportValidationError([issue(line, "", "헤더와 데이터의 컬럼 수가 다릅니다.")])
            rows.append(row)
            row_numbers.append(line)
    except (csv.Error, StopIteration) as exc:
        raise ImportValidationError([issue(reader.line_num or 1, "", "CSV 구분자와 따옴표 형식을 확인해주세요.")]) from exc
    df = pd.DataFrame(rows, columns=headers, dtype=object)
    df.attrs["row_numbers"] = row_numbers
    return df


def _present(value):
    return value is not None and value != "" and not pd.isna(value)


def _infer_type(values: list, name: str) -> str:
    if identifier_column(name) or not values:
        return "TEXT"
    texts = [str(v).strip() for v in values]
    if any(re.match(r"^[+-]?0\d+$", t) for t in texts):
        return "TEXT"
    if all(t.lower() in {"true", "false"} for t in texts):
        return "BOOLEAN"
    try:
        numbers = [parse_decimal(t) for t in texts]
    except ValueError:
        numbers = []
    if numbers:
        integers = max(numeric_dimensions(n)[0] for n in numbers)
        scale = max(numeric_dimensions(n)[1] for n in numbers)
        if scale == 0 and all(-(2**63) <= n < 2**63 for n in numbers):
            return "BIGINT"
        precision = max(integers + scale, 1)
        if precision <= 1000:
            return f"NUMERIC({precision},{scale})"
        return "TEXT"
    if all(re.match(r"^\d{4}-\d{2}-\d{2}(?:$|[T ])", t) for t in texts):
        if all(len(t) == 10 for t in texts):
            return "DATE"
        if all(re.search(r"(?:Z|[+-]\d{2}:\d{2})$", t) for t in texts):
            return "TIMESTAMPTZ"
        return "TIMESTAMP"
    return "TEXT"


def infer_columns_schema(df: pd.DataFrame) -> list[dict[str, Any]]:
    names = _column_names(df.columns)
    result, occurrences = [], {}
    for i, name in enumerate(names):
        source_name = str(df.columns[i])
        occurrence = occurrences.get(source_name, 0)
        occurrences[source_name] = occurrence + 1
        result.append({"name": name, "type": _infer_type([v for v in df.iloc[:, i] if _present(v)], source_name),
                       "nullable": True, "source_name": source_name, "source_occurrence": occurrence})
    return result


@dataclass(frozen=True)
class PreparedImport:
    columns_schema: list[dict[str, Any]]
    rows: list[tuple]
    row_numbers: list[int]


def prepare_import(content: bytes, filename: str, columns_schema: list[dict] | None = None) -> PreparedImport:
    """Read/validate the entire file without storage or DB side effects."""
    df = _load_dataframe(content, filename)
    inferred = infer_columns_schema(df)
    schema = [dict(c) for c in (columns_schema if columns_schema is not None else inferred)]
    source_names = _column_names(df.columns)
    target_names = [c["name"] for c in schema]
    problems = []
    if len(set(target_names)) != len(target_names) or "_row_id" in target_names:
        raise ImportValidationError([issue(1, "", "중복되거나 예약된 컬럼 이름입니다.")])
    if len(set(df.columns)) == len(df.columns) and set(df.columns) == set(target_names):
        # Exported files use canonical column names; support that round trip.
        indexes = [list(df.columns).index(name) for name in target_names]
    elif all("source_name" in c for c in schema):
        indexes = []
        for column in schema:
            matches = [i for i, name in enumerate(df.columns) if str(name) == column["source_name"]]
            occurrence = column.get("source_occurrence", 0)
            if occurrence >= len(matches):
                raise ImportValidationError([issue(1, column["source_name"], "기존 장부에 연결된 원본 컬럼이 없습니다.")])
            indexes.append(matches[occurrence])
        if len(set(indexes)) != len(df.columns) or len(indexes) != len(df.columns):
            raise ImportValidationError([issue(1, "", "기존 장부와 원본 컬럼의 개수가 다릅니다.")])
    elif set(source_names) != set(target_names):
        missing = sorted(set(target_names) - set(source_names))
        extra = sorted(set(source_names) - set(target_names))
        raise ImportValidationError([issue(1, "", f"장부와 컬럼이 다릅니다. 누락: {missing}, 추가: {extra}")])
    else:
        bases = [_sanitize_column_name(str(c)) for c in df.columns]
        if len(set(bases)) != len(bases):
            raise ImportValidationError([issue(1, "", "컬럼 이름이 겹칩니다. 원본 매핑이 없는 기존 장부에는 추가할 수 없습니다.")])
        indexes = [source_names.index(name) for name in target_names]
    for column in schema:
        try:
            column["type"] = validate_type(column["type"])
        except ValueError as exc:
            problems.append(issue(1, column["name"], str(exc)))
    if problems:
        raise ImportValidationError(problems)
    row_numbers = df.attrs.get("row_numbers", list(range(2, len(df) + 2)))
    numeric_cells = df.attrs.get("numeric_cells", set())
    rows = []
    for row_index, values in enumerate(df.itertuples(index=False, name=None)):
        output = []
        for column, source_index in zip(schema, indexes):
            raw = values[source_index]
            try:
                if identifier_column(str(df.columns[source_index])) and (row_index, source_index) in numeric_cells:
                    raise ValueError("Excel 숫자 셀의 ID는 손실 여부를 확인할 수 없습니다. 원본에서 텍스트로 제공해주세요.")
                if identifier_column(str(df.columns[source_index])) and column["type"] != "TEXT":
                    raise ValueError("ID 컬럼은 TEXT 타입이 필요합니다.")
                value = _cast_value(raw if _present(raw) else None, column["type"])
                if value is None and not column.get("nullable", True):
                    raise ValueError("필수 값이 비어 있습니다.")
                output.append(value)
            except ValueError as exc:
                problems.append(issue(row_numbers[row_index], str(df.columns[source_index]), str(exc)))
        rows.append(tuple(output))
        if len(problems) >= 50:
            break
    if problems:
        raise ImportValidationError(problems)
    return PreparedImport(schema, rows, row_numbers)


def write_import(cur, table_name: str, prepared: PreparedImport, *, create: bool):
    """Write within the caller's transaction. Never connect or commit here."""
    if create:
        columns = [sql.SQL("_row_id BIGSERIAL PRIMARY KEY")]
        columns.extend(sql.SQL("{} {}{}").format(sql.Identifier(c["name"]), sql.SQL(validate_type(c["type"])),
            sql.SQL("") if c.get("nullable", True) else sql.SQL(" NOT NULL")) for c in prepared.columns_schema)
        cur.execute(sql.SQL("CREATE TABLE {} ({})").format(sql.Identifier(table_name), sql.SQL(", ").join(columns)))
    if prepared.rows:
        identifier = lambda name: sql.Identifier(name.replace("%", "%%"))
        query = sql.SQL("INSERT INTO {} ({}) VALUES ({})").format(identifier(table_name),
            sql.SQL(", ").join(identifier(c["name"]) for c in prepared.columns_schema),
            sql.SQL(", ").join(sql.Placeholder() for _ in prepared.columns_schema))
        cur.executemany(query, prepared.rows)


def import_csv_to_table(content: bytes, filename: str, table_name: str, columns_schema=None, *, cur=None):
    prepared = prepare_import(content, filename, columns_schema)
    if cur is not None:
        write_import(cur, table_name, prepared, create=True)
    else:
        with _connect() as conn, conn.cursor() as cursor:
            write_import(cursor, table_name, prepared, create=True)
            conn.commit()
    return prepared.columns_schema, len(prepared.rows)


def append_csv_to_table(content: bytes, filename: str, table_name: str, existing_schema, *, cur=None):
    prepared = prepare_import(content, filename, existing_schema)
    if cur is not None:
        write_import(cur, table_name, prepared, create=False)
    else:
        with _connect() as conn, conn.cursor() as cursor:
            write_import(cursor, table_name, prepared, create=False)
            conn.commit()
    return len(prepared.rows)
