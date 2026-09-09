"""Read-only chat tools operate on real, owner-scoped import snapshots."""
import json
from unittest.mock import patch
from uuid import uuid4

import pytest

from app import db, ledger_imports, ledger_agent_tools
from app.agent_tools import ToolExecutor, TOOL_META
from app.agent import _select_tools
from app.router import OrchestratorResult
from .test_import_postgres import live, DSN
from .test_ledger_imports_postgres import env, source, upload, preview, commit, state


@pytest.fixture
def executor(env):
    with patch("app.agent_tools.list_table_metas", return_value=[]):
        return ToolExecutor(env[2], env[3])


@pytest.mark.skipif(not DSN, reason="Set DATAEZ_TEST_DATABASE_URL")
def test_chat_review_snapshot_and_link_are_read_only(env, executor):
    src = source(env)
    first = commit(env, preview(env, upload(env, src)))
    batch = preview(env, upload(env, src, content=b"id,money,day\n0001,100000,2026-09-01\n0004,50000,2026-09-03\n"))
    before = state(env, src)
    sources = executor.execute("list_ledger_sources", "{}")["sources"]
    assert len(sources) == 1 and sources[0]["row_count"] == 3
    assert sources[0]["last_committed_at"] == first["committed_at"]
    assert "physical_table_name" not in sources[0] and "baseline_report" not in sources[0]
    history = executor.execute("list_import_history", json.dumps({"source_id": str(src["id"])}))
    assert history["total"] == 2 and history["batches"][0]["summary"]["amount"] == "50000"
    review = executor.execute("inspect_import_review", json.dumps({"batch_id": str(batch["id"]), "classification": "duplicate"}))
    assert review["total"] == 1 and len(review["rows"]) == 1
    assert review["batch"]["summary"]["counts"]["new"] == 1
    assert str(review["rows"][0]["matched"]["batch_id"]) == str(first["id"])
    assert review["rows"][0]["matched"]["row_number"] == 2
    assert review["review_url"] == f"/dashboard?project={env[3]}&section=tables&source={src['id']}&batch={batch['id']}"
    assert "preview_token" not in review and "storage_key" not in review["batch"]
    assert not executor.mutations_performed and state(env, src) == before


@pytest.mark.skipif(not DSN, reason="Set DATAEZ_TEST_DATABASE_URL")
@pytest.mark.parametrize("foreign_owner", [False, True])
def test_chat_source_history_and_rows_cannot_cross_scope(env, foreign_owner):
    src = source(env)
    batch = preview(env, upload(env, src))
    with patch("app.agent_tools.list_table_metas", return_value=[]):
        executor = ToolExecutor(str(uuid4()) if foreign_owner else env[2], env[3] if foreign_owner else env[4])
    for tool, args in [("list_import_history", {"source_id": str(src["id"])}), ("inspect_import_review", {"batch_id": str(batch["id"])})]:
        result = executor.execute(tool, json.dumps(args))
        assert result["error"] == "not_found"
        assert "rows" not in result and "batches" not in result
    result = executor.execute("list_ledger_sources", "{}")
    assert "error" in result if foreign_owner else result["sources"] == []


@pytest.mark.skipif(not DSN, reason="Set DATAEZ_TEST_DATABASE_URL")
def test_chat_review_pages_do_not_claim_whole_file_is_current_page(env, executor):
    src = source(env)
    content = "id,money,day\n" + "".join(f"E{i},1,2026-09-01\n" for i in range(23))
    batch = preview(env, upload(env, src, content=content.encode()))
    result = executor.execute("inspect_import_review", json.dumps({"batch_id": str(batch["id"]), "offset": 20}))
    assert result["total"] == result["batch"]["summary"]["row_count"] == 23
    assert len(result["rows"]) == 3 and result["offset"] == 20 and result["limit"] == 20


@pytest.mark.skipif(not DSN, reason="Set DATAEZ_TEST_DATABASE_URL")
def test_conflict_guidance_matches_actual_uneditable_classification(env, executor):
    from app.ledger_routes import RowDecision
    from app.exceptions import AppException
    src = source(env)
    commit(env, preview(env, upload(env, src)))
    batch = preview(env, upload(env, src, content=b"id,money,day\n0001,999999,2026-09-01\n"))
    assert batch['summary']['counts']['conflict'] == 1
    before = state(env, src)
    review = executor.execute('inspect_import_review', json.dumps({'batch_id': str(batch['id'])}))
    assert review['decision_policy']['editable_classifications'] == ['candidate']
    for choice in ['include', 'exclude']:
        with pytest.raises(AppException) as exc:
            ledger_imports.decide_rows(env[2], env[3], str(batch['id']), str(batch['preview_token']), [RowDecision(row_number=2, decision=choice)])
        # Conflict batches are already failed, so the ready-preview guard
        # rejects the whole request before row decisions can be considered.
        assert exc.value.status_code == 409 and exc.value.code == 'stale_preview'
    assert state(env, src) == before


@pytest.mark.parametrize("tool,args", [
    ("list_ledger_sources", {"project_id": str(uuid4())}),
    ("list_import_history", {"source_id": "invalid"}),
    ("list_import_history", {"source_id": str(uuid4()), "offset": -1}),
    ("inspect_import_review", {"batch_id": str(uuid4()), "classification": "anything"}),
    ("inspect_import_review", {"batch_id": str(uuid4()), "decision": "include"}),
])
def test_read_tools_reject_scope_override_and_mutation_arguments(tool, args):
    with patch("app.agent_tools.list_table_metas", return_value=[]), patch.object(ledger_imports, "list_sources") as read:
        executor = ToolExecutor(str(uuid4()), str(uuid4()))
        assert "error" in executor.execute(tool, json.dumps(args))
        assert not executor.mutations_performed
        read.assert_not_called()


def test_review_routing_includes_lookup_dependencies_without_write_tools():
    with patch("app.agent.select_tools_via_orchestrator", return_value=OrchestratorResult(tools=["inspect_import_review"], intent="analysis")):
        specs, _, _ = _select_tools("왜 이번 파일이 중복으로 빠졌어?")
    names = {spec["function"]["name"] for spec in specs}
    assert names == {"list_ledger_sources", "list_import_history", "inspect_import_review"}
    assert all(TOOL_META[name]["read_only"] and not TOOL_META[name]["mutation"] for name in names)


def test_disabled_rag_does_not_require_vector_schema(monkeypatch):
    monkeypatch.setattr(db.settings, "rag_enabled", False)
    with patch.object(db, "_connect") as connect:
        db.ensure_rag_tables()
    connect.assert_not_called()
