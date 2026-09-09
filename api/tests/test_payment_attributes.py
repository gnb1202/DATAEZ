"""G: signed PG attributes, precision, historical hashes and NULL contracts."""
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.event_review import digest, normalize
from app.import_validation import ImportValidationError
from app.metric_definitions import MetricFilter
from app.payment_imports import PaymentImportMapping, payment_schema, prepare_payment_import
from app.rag_catalog import catalog_lines


def mapping(**overrides):
    return PaymentImportMapping(**{"amount_column": "amount", "occurred_at_column": "day", "event_kind": "refund",
        "payment_method_column": "method", "channel_column": "channel", "fee_column": "fee", **overrides})


def test_optional_attributes_preserve_text_exact_fee_and_independent_sign():
    prepared = prepare_payment_import("amount,day,method,channel,fee\n20,2026-09-01,카드,예약웹,9007199254740993.01\n30,2026-09-01,,,\n40,2026-09-01,현금,매장,-1.25\n".encode(), "p.csv", mapping())
    assert [c["name"] for c in prepared.columns_schema][6:] == ["payment_method", "channel", "fee"]
    assert prepared.rows[0][3] == -20
    assert prepared.rows[0][6:] == ("카드", "예약웹", Decimal("9007199254740993.01"))
    assert prepared.rows[1][6:] == (None, None, None)
    assert prepared.rows[2][-1] == Decimal("-1.25")
    assert normalize(prepared.rows[0], prepared.columns_schema)["fee"] == "9007199254740993.01"


def test_old_schema_and_hash_unchanged_when_attributes_unknown():
    legacy = ("0001", None, "payment", Decimal("100"), "2026-09-01T00:00:00+09:00", "KRW")
    assert len(payment_schema()) == 6
    assert digest(normalize(legacy)) == digest(normalize(legacy + (None, None, None), payment_schema(mapping())))
    assert digest(normalize(legacy)) != digest(normalize(legacy + (None, None, Decimal(0)), payment_schema(mapping())))
    fee_only = mapping(payment_method_column=None, channel_column=None)
    assert [c["name"] for c in payment_schema(fee_only)][6:] == ["fee"]
    assert normalize(legacy + (Decimal("1.00"),), payment_schema(fee_only))["fee"] == "1"


@pytest.mark.parametrize("value", ["NaN", "Infinity", "무료", "1,2"])
def test_bad_fee_reports_original_row_and_column(value):
    import csv
    import io
    out = io.StringIO()
    csv.writer(out).writerows([["amount", "day", "method", "channel", "fee"], ["1", "2026-09-01", "카드", "매장", value]])
    with pytest.raises(ImportValidationError) as exc:
        prepare_payment_import(out.getvalue().encode(), "p.csv", mapping())
    assert exc.value.issues[0]["row"] == 2 and exc.value.issues[0]["column"] == "fee"


def test_optional_mapping_is_still_required_in_every_file_and_cannot_reuse_column():
    for m in [mapping(fee_column="absent"), mapping(fee_column="amount")]:
        with pytest.raises(ImportValidationError):
            prepare_payment_import(b"amount,day,method,channel,fee\n1,2026-09-01,,,0\n", "p.csv", m)


@pytest.mark.parametrize("payload", [{"operator": "=", "value": None}, {"operator": "is_null", "value": "NULL"}, {"operator": "is_not_null", "value": ""}])
def test_null_filter_rejects_ambiguous_values(payload):
    with pytest.raises(ValidationError):
        MetricFilter(column="fee", **payload)


def test_catalog_attributes_use_original_columns_on_adopted_tables():
    meta = {"source_id": "source", "source_name": "PG", "provider": "가상PG", "feed": "결제", "data_revision": 1,
            "storage_mode": "original", "mapping": mapping(fee_column="pg_fee").model_dump(),
            "columns_schema": [{"name": "fee"}, {"name": "pg_fee"}]}
    text = "\n".join(catalog_lines(meta))
    assert "PG 수수료: pg_fee (원본 pg_fee)" in text
    assert "원본 부호" in text


def test_restoration_excel_subset_retains_original_row_numbers_and_numeric_id_checks():
    from io import BytesIO
    from openpyxl import Workbook
    book = Workbook()
    sheet = book.active
    sheet.append(['id', 'amount', 'day', 'fee'])
    sheet.append(['0001', 100, '2026-09-01', 'bad-unused-fee'])
    sheet.append(['0002', 200, '2026-09-02', '9007199254740993.01'])
    sheet.append([1234, 300, '2026-09-03', '1'])
    content = BytesIO()
    book.save(content)
    m = mapping(event_id_column='id', payment_method_column=None, channel_column=None, event_kind='signed')
    selected = prepare_payment_import(content.getvalue(), 'p.xlsx', m, selected_rows={3})
    assert selected.row_numbers == [3] and selected.rows[0][0] == '0002'
    assert selected.rows[0][-1] == Decimal('9007199254740993.01')
    with pytest.raises(ImportValidationError) as exc:
        prepare_payment_import(content.getvalue(), 'p.xlsx', m, selected_rows={4})
    assert exc.value.issues[0]['row'] == 4 and exc.value.issues[0]['column'] == 'id'
