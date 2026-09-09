"""Read real file bytes; ensure corruption is rejected before any DB write."""
import io
from decimal import Decimal
from unittest.mock import MagicMock, patch
from zipfile import ZipFile

import pytest
from openpyxl import Workbook

from app.data_import import prepare_import, import_csv_to_table, append_csv_to_table, write_import
from app.import_validation import ImportValidationError, cast_value


def prepare(text, schema=None):
    return prepare_import(text.encode("utf-8"), "ledger.csv", schema)


def workbook_bytes(rows):
    workbook = Workbook()
    for row in rows:
        workbook.active.append(row)
    buffer = io.BytesIO()
    workbook.save(buffer)
    workbook.close()
    return buffer.getvalue()


def test_csv_preserves_identifiers_missing_tokens_and_exact_amounts():
    result = prepare("event_id,amount,note\n000012345678901234567890,9007199254740993.01,NA\nAbC,0.000000123,NULL\n")
    assert result.rows[0] == ("000012345678901234567890", Decimal("9007199254740993.01"), "NA")
    assert result.rows[1] == ("AbC", Decimal("0.000000123"), "NULL")
    assert result.columns_schema[1]["type"] == "NUMERIC(25,9)"


def test_precision_is_based_on_every_row_not_first_100():
    result = prepare("amount\n" + "1.00\n" * 100 + "99999999999999999999.123456789\n")
    assert result.rows[-1] == (Decimal("99999999999999999999.123456789"),)
    assert result.columns_schema[0]["type"] == "NUMERIC(29,9)"


def test_bigint_no_float_roundtrip():
    assert cast_value("9007199254740993", "BIGINT") == 9007199254740993


@pytest.mark.parametrize("value,dtype", [("42.7", "BIGINT"), ("9223372036854775808", "BIGINT"),
    ("0.001", "NUMERIC(5,2)"), ("1000", "NUMERIC(5,2)"), ("NaN", "NUMERIC"), ("Infinity", "NUMERIC"),
    ("2026-02-30", "DATE"), ("01/02/2026", "DATE"), ("2026-09-01T00:00:00Z", "TIMESTAMP"), ("false-ish", "BOOLEAN")])
def test_lossy_or_ambiguous_values_fail(value, dtype):
    with pytest.raises(ValueError):
        cast_value(value, dtype)


def test_zero_and_trailing_zeros_fit_numeric_scale():
    assert cast_value("0.00", "NUMERIC(2,2)") == Decimal("0.00")
    assert cast_value("1.2300", "NUMERIC(5,2)") == Decimal("1.23")
    assert cast_value("false", "BOOLEAN") is False


def test_append_missing_extra_and_invalid_columns_never_write():
    schema = [{"name": "amount", "type": "NUMERIC(15,2)", "nullable": False}]
    with patch("app.data_import._connect") as connect:
        for payload in [b"different\n100\n", b"amount,extra\n100,x\n", b"amount\nwrong\n", b'amount\n""\n']:
            with pytest.raises(ImportValidationError):
                append_csv_to_table(payload, "ledger.csv", "test", schema)
        connect.assert_not_called()


def test_reordered_columns_keep_correct_values():
    schema = [{"name": "amount", "type": "NUMERIC"}, {"name": "event_id", "type": "TEXT"}]
    assert prepare("event_id,amount\n001,12.34\n", schema).rows == [(Decimal("12.34"), "001")]


def test_sanitized_name_collisions_preserve_each_column():
    result = prepare("A!,A?,A_1\nfirst,second,third\n")
    assert [c["name"] for c in result.columns_schema] == ["a", "a_1", "a_1_1"]
    assert result.rows == [("first", "second", "third")]


def test_reordered_colliding_headers_use_persisted_original_mapping():
    original = prepare("A!,A?,A_1\nfirst,second,third\n")
    appended = prepare("A?,A_1,A!\nsecond,third,first\n", original.columns_schema)
    assert appended.rows == [("first", "second", "third")]
    exported = prepare("a,a_1,a_1_1\nfirst,second,third\n", original.columns_schema)
    assert exported.rows == appended.rows


def test_legacy_schema_without_original_mapping_rejects_ambiguous_headers():
    schema = [{"name": "a", "type": "TEXT"}, {"name": "a_1", "type": "TEXT"}]
    with pytest.raises(ImportValidationError):
        prepare("A!,A?\nfirst,second\n", schema)


def test_error_reports_physical_row_after_multiline_record():
    schema = [{"name": "note", "type": "TEXT"}, {"name": "amount", "type": "NUMERIC"}]
    with pytest.raises(ImportValidationError) as caught:
        prepare('note,amount\n"line1\nline2",1\n\ninvalid,not-money\n', schema)
    assert caught.value.issues[0]["row"] == 5
    assert caught.value.issues[0]["column"] == "amount"


@pytest.mark.parametrize("content", [b"a,b\n1,2,3\n", b'a,b\n"unterminated,2', b"\xef\xbb\xbf", b"\n", b"a,\n1,2\n"])
def test_malformed_csv_is_not_reinterpreted_with_another_encoding(content):
    with pytest.raises(ImportValidationError):
        prepare_import(content, "ledger.csv")


def test_korean_cp949_bom_and_blank_records():
    assert prepare_import("거래번호,금액\n001,100\n".encode("cp949"), "ledger.csv").rows == [("001", 100)]
    assert prepare_import(b"\xef\xbb\xbfa\n\nx\n", "ledger.csv").row_numbers == [3]


def test_schema_type_cannot_inject_sql():
    with pytest.raises(ImportValidationError), patch("app.data_import._connect") as connect:
        import_csv_to_table(b"amount\n1\n", "ledger.csv", "test", [{"name": "amount", "type": "NUMERIC); DROP TABLE users;--"}])
    connect.assert_not_called()


def test_caller_cursor_never_opens_or_commits_another_connection():
    cur = MagicMock()
    with patch("app.data_import._connect") as connect:
        import_csv_to_table(b"amount\n1\n", "ledger.csv", "test", cur=cur)
    connect.assert_not_called()
    cur.executemany.assert_called_once()
    assert "IF NOT EXISTS" not in cur.execute.call_args.args[0].as_string()


def test_xlsx_text_id_and_raw_numeric_lexeme():
    content = workbook_bytes([["event_id", "amount"], ["001", 1.25]])
    # Simulate an exact numeric cell written by an external export, beyond JS
    # and Python float precision; only the archive lexeme retains all digits.
    output = io.BytesIO()
    with ZipFile(io.BytesIO(content)) as source, ZipFile(output, "w") as target:
        for name in source.namelist():
            data = source.read(name)
            if name == "xl/worksheets/sheet1.xml":
                data = data.replace(b"<v>1.25</v>", b"<v>9007199254740993.01</v>")
            target.writestr(name, data)
    assert prepare_import(output.getvalue(), "ledger.xlsx").rows == [("001", Decimal("9007199254740993.01"))]


def test_excel_numeric_id_and_formula_rejected():
    for rows in [[["event_id", "amount"], [123, 1]], [["amount"], ["=1+1"]]]:
        with pytest.raises(ImportValidationError):
            prepare_import(workbook_bytes(rows), "ledger.xlsx")


def test_required_date_failure_has_row_and_column():
    schema = [{"name": "date", "type": "DATE", "nullable": False}]
    with pytest.raises(ImportValidationError) as caught:
        prepare('date\n2026-09-01\n""\n', schema)
    assert caught.value.issues[0]["row"] == 3


def test_zero_rows_with_headers_is_valid():
    result = prepare("amount,note\n")
    assert result.rows == [] and len(result.columns_schema) == 2
