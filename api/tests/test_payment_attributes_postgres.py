"""G: real writes, overlap conflicts, adopted originals and saved metrics."""
import json
from decimal import Decimal
from pathlib import Path
from uuid import UUID

import pytest
from fastapi import HTTPException
from psycopg import sql

from app import db, ledger_imports as service, dashboard_metrics as metrics, table_imports
from app.exceptions import AppException
from app.payment_imports import PaymentImportMapping, prepare_payment_import
from app.metric_definitions import MetricDefinition, MultiMetricDefinition
from .test_import_postgres import live, DSN
from .test_ledger_imports_postgres import env, source, upload, preview, commit, state

pytestmark = pytest.mark.skipif(not DSN, reason="Set DATAEZ_TEST_DATABASE_URL for G verification")
MAPPING = {"amount_column": "money", "occurred_at_column": "day", "event_id_column": "id", "event_kind": "signed",
           "payment_method_column": "method", "channel_column": "channel", "fee_column": "fee"}
HEADER = "id,money,day,method,channel,fee\n"
BODY = "001,100,2026-09-01,카드,예약웹,3.00\n002,-20,2026-09-02,카드,예약웹,-0.60\n003,50,2026-09-02,현금,매장,0\n"


def imported(env):
    src = source(env, mapping=MAPPING)
    commit(env, preview(env, upload(env, src, (HEADER + BODY).encode())))
    return src


def metric(src, **values):
    return MetricDefinition(**{"table_id": src["table_id"], "column": "amount", **values})


def test_file_overlap_preserves_attributes_hashes_and_precision(env):
    src = imported(env)
    overlap = preview(env, upload(env, src, (HEADER + BODY + "004,1,2026-09-03,간편결제,예약웹,9007199254740993.01\n").encode()))
    assert overlap["summary"]["counts"]["duplicate"] == 3
    assert commit(env, overlap)["rows_added"] == 1
    with env[0]() as conn:
        rows = conn.execute(sql.SQL("SELECT payment_method,channel,fee FROM {} ORDER BY _row_id").format(
            sql.Identifier(db.get_user_table_name(env[2], str(src["table_id"]))))).fetchall()
        events = conn.execute("SELECT normalized FROM source_events WHERE source_id=%s ORDER BY target_row_id", (src["id"],)).fetchall()
    assert rows[1] == {"payment_method": "카드", "channel": "예약웹", "fee": Decimal("-0.60")}
    assert rows[-1]["fee"] == Decimal("9007199254740993.01")
    assert events[-1]["normalized"]["fee"] == "9007199254740993.01"


@pytest.mark.parametrize("changed", ["001,100,2026-09-01,현금,예약웹,3", "001,100,2026-09-01,카드,매장,3", "001,100,2026-09-01,카드,예약웹,4", "001,100,2026-09-01,카드,예약웹,"])
def test_changed_or_removed_attribute_conflicts_without_partial_writes(env, changed):
    src = imported(env)
    batch = preview(env, upload(env, src, (HEADER + changed + "\nNEW,50,2026-09-03,카드,매장,1\n").encode()))
    assert batch["summary"]["counts"]["conflict"] == 1
    with pytest.raises(AppException):
        commit(env, batch)
    assert len(state(env, src)[0]) == 3
    row = service.list_rows(env[2], env[3], batch["id"], classification="conflict")["rows"][0]
    assert row["matched"]["normalized"]["fee"] == "3"


def test_legacy_source_create_retry_compares_mapping_defaults(env):
    src = source(env)
    with env[0]() as conn:
        conn.execute("UPDATE ledger_sources SET mapping=mapping-'payment_method_column'-'channel_column'-'fee_column' WHERE id=%s", (src["id"],))
    assert source(env)["id"] == src["id"]
    assert commit(env, preview(env, upload(env, src)))["rows_added"] == 3


def test_categories_filters_and_signed_fees_save_refresh_and_isolation(env):
    src = imported(env)
    data = metrics.preview_saved_metric(env[3], env[2], metric(src, group_by="payment_method"))
    assert {r["dimension"]: r["value"] for r in data["data"]} == {"카드": "80", "현금": "50"}
    fee = metric(src, column="fee", filters=[{"column": "channel", "value": "예약웹"}])
    saved = metrics.create_saved_metric(env[3], env[2], metrics.CreateMetricRequest(title="예약웹 PG 수수료", definition=fee, refresh_interval_seconds=3600))
    assert Decimal(saved["widget_data"]["value"]) == Decimal("2.40")
    commit(env, preview(env, upload(env, src, (HEADER + "004,10,2026-09-03,카드,예약웹,0.3\n").encode())))
    refreshed = metrics.refresh_metric(UUID(env[3]), UUID(str(saved["id"])), {"id": env[2]})
    assert Decimal(refreshed["widget_data"]["value"]) == Decimal("2.70")
    with pytest.raises(HTTPException) as exc:
        metrics.preview_saved_metric(env[4], env[2], fee)
    assert exc.value.status_code == 404


def test_unknown_fee_blocks_total_preserves_last_value_and_can_count_unknown(env):
    src = imported(env)
    fee = metric(src, column="fee", group_by="channel")
    saved = metrics.create_saved_metric(env[3], env[2], metrics.CreateMetricRequest(title="채널별 수수료", definition=fee))
    commit(env, preview(env, upload(env, src, (HEADER + "004,30,2026-09-03,,,\n").encode())))
    with pytest.raises(HTTPException) as exc:
        metrics.preview_saved_metric(env[3], env[2], fee)
    assert "미제공인 행 1건" in exc.value.detail
    with pytest.raises(HTTPException):
        metrics.refresh_metric(UUID(env[3]), UUID(str(saved["id"])), {"id": env[2]})
    with env[0]() as conn:
        data = conn.execute("SELECT widget_data FROM dashboard_widgets WHERE id=%s", (saved["id"],)).fetchone()["widget_data"]
    assert data["data"] == saved["widget_data"]["data"] and data["refresh_error"]
    count = metrics.preview_saved_metric(env[3], env[2], metric(src, operation="count", column=None, filters=[{"column": "fee", "operator": "is_null"}]))
    assert count["value"] == 1
    provided = metrics.preview_saved_metric(env[3], env[2], metric(src, column="fee", filters=[{"column": "fee", "operator": "is_not_null"}]))
    assert Decimal(provided["value"]) == Decimal("2.4") and "제공됨" in provided["calculation_label"]
    grouped = metrics.preview_saved_metric(env[3], env[2], metric(src, group_by="payment_method"))
    assert next(r for r in grouped["data"] if r["dimension"] is None)["value"] == "30"


def test_adopted_original_attributes_participate_in_baseline_and_dedup(env):
    meta = table_imports.create_imported_table(env[2], env[3], "기존 PG", (HEADER + BODY).encode(), "p.csv", env[1])
    request = service.CreateSourceRequest(name="기존 PG 출처", provider="PG", account="기존", feed="결제", mapping=MAPPING, existing_table_id=meta["id"])
    report = service.preview_adoption(env[2], env[3], request)
    request.adoption_token = report["adoption_token"]
    src = service.create_source(env[2], env[3], request)
    assert src["storage_mode"] == "original"
    assert commit(env, preview(env, upload(env, src, (HEADER + BODY).encode())))["rows_added"] == 0
    changed = preview(env, upload(env, src, (HEADER + "001,100,2026-09-01,카드,다른채널,3\n").encode()))
    assert changed["status"] == "failed"


def test_sample_csv_and_excel_preserve_all_mapped_attributes(env):
    root = Path(__file__).resolve().parents[2]
    manifest = json.loads((root / "samples/pg-evaluation/manifest.json").read_text(encoding="utf-8"))
    mapping = PaymentImportMapping(**manifest["pg_mapping"], payment_method_column="결제수단", channel_column="판매채널", fee_column="PG수수료")
    csv = prepare_payment_import((root / "samples/pg-evaluation/01_gangnam_pg.csv").read_bytes(), "p.csv", mapping)
    book = root / manifest["workbook"]
    xlsx = prepare_payment_import(book.read_bytes(), book.name, mapping)
    assert csv.rows == xlsx.rows and len(csv.rows) == 40


def test_null_filters_use_same_parameter_order_in_multi_source_queries(env):
    first = imported(env)
    second = source(env, account="second", name="보조 PG", mapping=MAPPING)
    commit(env, preview(env, upload(env, second, (HEADER + "009,10,2026-09-03,카드,매장,1\n010,20,2026-09-03,현금,매장,\n").encode())))
    definition = MultiMetricDefinition(sources=[
        {"table_id": first["table_id"], "label": "PG 1", "column": "fee", "filters": [{"column": "fee", "operator": "is_not_null"}, {"column": "channel", "value": "예약웹"}]},
        {"table_id": second["table_id"], "label": "PG 2", "column": "fee", "filters": [{"column": "channel", "value": "매장"}, {"column": "fee", "operator": "is_not_null"}]},
    ])
    result = metrics.preview_saved_metric(env[3], env[2], definition)
    assert Decimal(result["value"]) == Decimal("3.40")
