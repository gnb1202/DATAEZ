"""Import boundaries: REST and chat expose validation and use one service."""
import json
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.agent_tools import ToolExecutor
from app.import_validation import ImportValidationError, issue
from app.payment_imports import PaymentImportMapping, prepare_payment_import

USER, STORE, TABLE = [str(uuid4()) for _ in range(3)]
META = {"id": TABLE, "name": "결제", "project_id": STORE, "columns_schema": [{"name": "amount", "type": "BIGINT"}], "row_count": 1}


def test_chat_import_uses_atomic_service_and_reports_structured_errors():
    with patch("app.agent_tools.list_table_metas", return_value=[META]), patch("app.agent_tools.record_audit"), \
         patch("app.agent_tools.append_imported_table", side_effect=ImportValidationError([issue(3, "amount", "정수가 필요합니다.")])) as append:
        executor = ToolExecutor(USER, STORE, attached_files=[{"content": b"amount\n1.2", "filename": "ledger.csv"}])
        result = executor.execute("import_file", json.dumps({"action": "append_existing", "table_name": "결제", "file_index": 0}))
    assert result["error"] == "import_validation_error" and result["issues"][0]["row"] == 3
    assert not executor.mutations_performed
    assert append.call_args.args[:3] == (USER, STORE, TABLE)


def test_chat_success_tracks_returned_table_id():
    with patch("app.agent_tools.list_table_metas", return_value=[]), patch("app.agent_tools.record_audit"), \
         patch("app.agent_tools.create_imported_table", return_value=META) as create:
        executor = ToolExecutor(USER, STORE, attached_files=[{"content": b"amount\n100", "filename": "ledger.csv"}])
        result = executor.execute("import_file", json.dumps({"action": "create_new", "table_name": "결제"}))
    assert result["success"] and result["rows_imported"] == 1
    assert TABLE in executor.mutated_table_ids
    assert create.call_args.args[:3] == (USER, STORE, "결제")


def test_rest_import_and_append_have_same_size_limit(monkeypatch):
    from app import main
    from app.auth import get_current_user
    monkeypatch.setattr(main.settings, "max_upload_size_mb", 0)
    monkeypatch.setattr(main, "get_project", MagicMock(return_value={"id": STORE}))
    monkeypatch.setattr(main, "get_table_meta", MagicMock(return_value=META))
    create, append = MagicMock(), MagicMock()
    monkeypatch.setattr(main, "create_imported_table", create)
    monkeypatch.setattr(main, "append_imported_table", append)
    main.app.dependency_overrides[get_current_user] = lambda: {"id": USER}
    try:
        client = TestClient(main.app)
        for path in [f"/api/projects/{STORE}/tables/import", f"/api/projects/{STORE}/tables/{TABLE}/append"]:
            response = client.post(path, files={"file": ("ledger.csv", b"a\n1")})
            assert response.status_code == 400
        create.assert_not_called()
        append.assert_not_called()
    finally:
        main.app.dependency_overrides.pop(get_current_user, None)


@pytest.mark.parametrize("row", ["001,USD,1,2026-09-01", "001,KRW,NaN,2026-09-01", "001,KRW,1,09/01/2026", ",KRW,1,2026-09-01"])
def test_mapped_payment_missing_currency_date_and_amount_are_rejected(row):
    mapping = PaymentImportMapping(event_id_column="key", currency_column="currency", amount_column="money", occurred_at_column="day")
    with pytest.raises(ImportValidationError) as error:
        prepare_payment_import(f"key,currency,money,day\n{row}\n".encode(), "ledger.csv", mapping)
    assert error.value.issues[0]["row"] == 2


def test_mapping_without_id_preserves_two_same_amount_events():
    mapping = PaymentImportMapping(amount_column="money", occurred_at_column="day", event_kind="signed")
    prepared = prepare_payment_import(b"money,day\n100,2026-09-01\n100,2026-09-01\n-20,2026-09-02\n", "ledger.csv", mapping)
    assert len(prepared.rows) == 3
    assert prepared.rows[0][0] is None and prepared.rows[2][2] == "refund"
    assert prepared.rows[0][4] == "2026-09-01T00:00:00+09:00"
