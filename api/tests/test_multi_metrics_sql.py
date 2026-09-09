"""Execute the production compiler's SQL in PostgreSQL WASM (no Docker).

Install once: npm ci --prefix scripts/sql-eval (from repo root).
PGlite validates SQL semantics; psycopg and concurrent locks need the separate
DATAEZ_TEST_DATABASE_URL integration suite.
"""
import json
from pathlib import Path
import shutil
import subprocess
from uuid import UUID

import pytest
from psycopg import sql
from psycopg._queries import _query2pg_nocache

from app.db import get_user_table_name
from app.dashboard_metrics import compile_metric
from app.metric_definitions import MetricDefinition, MultiMetricDefinition
from app.multi_metrics import compile_multi

ROOT = Path(__file__).resolve().parents[2]
RUNNER = ROOT / "scripts" / "sql-eval" / "run.mjs"
USER = str(UUID(int=1))
IDS = [str(UUID(int=n << 96)) for n in range(2, 6)]
TABLES = [sql.Identifier(get_user_table_name(USER, tid)).as_string() for tid in IDS]
ODD_COLUMN = '금액" %s'
COLUMN = sql.Identifier(ODD_COLUMN).as_string()


@pytest.fixture(scope="module")
def results():
    node = shutil.which("node")
    if not node or not (RUNNER.parent / "node_modules" / "@electric-sql" / "pglite").exists():
        pytest.skip("Install SQL eval dependencies: npm ci --prefix scripts/sql-eval")
    cash, card, refunds, precise = TABLES
    d0 = "date_trunc('month', CURRENT_DATE)"
    d1 = f"{d0} + interval '1 day'"
    setup = "SET TIME ZONE 'Asia/Seoul';" + "".join(
        f"CREATE TABLE {table} ({COLUMN} numeric, stamp timestamp, status text DEFAULT '완료');" for table in TABLES
    ) + f"""
        INSERT INTO {cash} VALUES (60000,{d0},'완료'),(40000,{d1},'완료'),
          (500,{d0} - interval '1 day','완료'),(999,{d0} + interval '1 month','완료'),(123,{d0},'대기');
        INSERT INTO {card} VALUES (200000,{d1},'완료');
        INSERT INTO {refunds} VALUES (50000,{d1},'완료');
        INSERT INTO {precise} VALUES (9007199254740993.01,{d0},'완료');
    """
    sources = [{"table_id": tid, "label": label, "column": ODD_COLUMN, "date_column": "stamp",
                "amount_mode": "refund" if label == "취소" else "signed",
                "filters": [{"column": "status", "value": "완료"}]}
               for tid, label in zip(IDS, ["현금", "카드", "취소"])]
    cases = []

    def add_query(name, query, params, before=None):
        # Intentionally exercise the installed driver's actual %s -> $n
        # conversion rather than a hand-written approximation in the runner.
        wire_query, formats, _, _ = _query2pg_nocache(query.as_string().encode("utf-8"), "utf-8")
        assert len(formats) == len(params)
        cases.append({"name": name, "before": before, "query": wire_query.decode("utf-8"), "params": params})

    def case(name, before=None, **changes):
        definition = MultiMetricDefinition.model_validate({"sources": sources, "time_range": "this_month", **changes})
        query, params = compile_multi(USER, definition)
        add_query(name, query, params, before)

    query, params = compile_metric(get_user_table_name(USER, IDS[0]), MetricDefinition(
        table_id=IDS[0], column=ODD_COLUMN, date_column="stamp", time_range="this_month", filters=[{"column": "status", "value": "완료"}]))
    add_query("single_special_identifier", query, params)
    case("total")
    case("date", group_by="date")
    case("source", group_by="source")
    case("last_month", time_range="last_month")
    case("all", time_range="all")
    case("negative_refund", before=f"UPDATE {refunds} SET {COLUMN}=-50000")
    case("refresh", before=f"INSERT INTO {cash} VALUES (50000,{d1},'완료')")
    case("precise", sources=[{**sources[0], "table_id": IDS[3]}, {**sources[1], "filters": [{"column": "status", "value": "없음"}]}])
    case("literal_label", sources=[{**s, "label": s["label"] + "'); DROP TABLE users; --"} for s in sources], group_by="source")
    case("literal_filter", sources=[{**s, "filters": [{"column": "status", "value": "완료' OR 1=1 --"}]} for s in sources])
    case("missing_amount", before=f"INSERT INTO {cash} VALUES (NULL,{d0},'완료')")
    case("missing_date", before=f"DELETE FROM {cash} WHERE {COLUMN} IS NULL; INSERT INTO {card} VALUES (10,NULL,'완료')")
    case("nonfinite", before=f"DELETE FROM {card} WHERE stamp IS NULL; INSERT INTO {card} VALUES ('NaN',{d0},'완료')")
    case("last_30_days", time_range="last_30_days", before=f"""
        TRUNCATE {cash}, {card}, {refunds};
        INSERT INTO {cash} VALUES (10,CURRENT_DATE - interval '29 days','완료'),
          (20,CURRENT_DATE - interval '30 days','완료'),(30,CURRENT_DATE,'완료'),
          (40,CURRENT_DATE + interval '1 day','완료');
    """)
    case("too_many_groups", group_by="date", time_range="all", before=f"""
        TRUNCATE {cash};
        INSERT INTO {cash} SELECT 1, DATE '2020-01-01' + n, '완료' FROM generate_series(0,1000) n;
    """)
    case("empty", before=f"TRUNCATE {cash}, {card}, {refunds}")
    run = subprocess.run([node, str(RUNNER)], input=json.dumps({"setup": setup, "cases": cases}),
                         capture_output=True, encoding="utf-8", timeout=90)
    assert run.returncode == 0, run.stderr[-5000:]
    return {name: rows[0] for name, rows in json.loads(run.stdout).items()}


@pytest.mark.parametrize("name,expected", [
    ("total", "250000"), ("negative_refund", "250000"), ("refresh", "300000"),
    ("last_month", "500"), ("all", "251499"), ("precise", "9007199254740993.01"),
    ("last_30_days", "40"), ("empty", None), ("literal_filter", None),
])
def test_real_sql_totals(results, name, expected):
    assert results[name]["data"] == [{"value": expected}]
    assert results[name]["missing_amounts"] == 0


def test_real_sql_daily_and_source_grouping(results):
    assert [row["value"] for row in results["date"]["data"]] == ["60000", "190000"]
    assert {r["dimension"]: r["value"] for r in results["source"]["data"]} == {"현금": "100000", "카드": "200000", "취소": "-50000"}
    assert results["source"]["source_counts"] == {"현금": 2, "카드": 1, "취소": 1}


def test_real_sql_quoted_source_label_is_literal(results):
    assert len(results["literal_label"]["data"]) == 3
    assert all("DROP TABLE" in row["dimension"] for row in results["literal_label"]["data"])


def test_real_sql_quality_checks_include_unassignable_dates(results):
    assert results["missing_amount"]["missing_amounts"] == 1
    assert results["missing_date"]["missing_dates"] == 1
    assert results["nonfinite"]["invalid_amounts"] == 1


def test_real_sql_group_overflow_is_detectable(results):
    assert len(results["too_many_groups"]["data"]) == 1001


def test_real_sql_single_ledger_percent_column(results):
    assert results["single_special_identifier"]["value"] == "100000"
