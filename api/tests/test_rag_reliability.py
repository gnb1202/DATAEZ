"""RAG failure states and embedding attribution; no external API calls."""
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

import pytest

from app import rag, llm
from app.agent_tools import ToolExecutor
from app.exceptions import AppException
from app.llm_telemetry import TurnLedger


@pytest.mark.parametrize('tool', ['search_schema', 'search_documents'])
def test_disabled_search_is_not_reported_as_no_data(monkeypatch, tool):
    monkeypatch.setattr(rag.settings, 'rag_enabled', False)
    with patch('app.agent_tools.list_table_metas', return_value=[]), patch.object(rag, 'embed_one') as embed:
        result = ToolExecutor(str(uuid4()), str(uuid4())).execute(tool, '{"query":"매출"}')
    assert result['error'] == 'rag_disabled' and 'results' not in result
    embed.assert_not_called()


@pytest.mark.parametrize('search', [rag.hybrid_search_schema, rag.hybrid_search_documents])
def test_embedding_failure_is_not_an_empty_success(monkeypatch, search):
    monkeypatch.setattr(rag.settings, 'rag_enabled', True)
    with patch.object(rag, 'embed_one', side_effect=RuntimeError('private provider detail')):
        with pytest.raises(AppException) as err:
            search(user_id=str(uuid4()), project_id=str(uuid4()), query='현금 받은 기록')
    assert err.value.code == 'rag_unavailable'
    assert 'private' not in err.value.detail


def test_embedding_response_order_and_turn_ledger():
    ledger = TurnLedger()
    response = SimpleNamespace(data=[SimpleNamespace(index=1, embedding=[0.0, 1.0]), SimpleNamespace(index=0, embedding=[1.0, 0.0])],
                               usage=SimpleNamespace(prompt_tokens=17, total_tokens=17))
    with patch.object(llm, 'get_openai_client') as client:
        client.return_value.embeddings.create.return_value = response
        assert llm.generate_embeddings(['first', 'second'], ledger=ledger) == [[1.0, 0.0], [0.0, 1.0]]
    assert ledger.total_tokens == 17 and ledger.summary()['by_role']['embedding']['calls'] == 1


def test_incomplete_embedding_response_rejected():
    with patch.object(llm, 'get_openai_client') as client:
        client.return_value.embeddings.create.return_value = SimpleNamespace(
            data=[SimpleNamespace(index=1, embedding=[1.0])], usage=None)
        with pytest.raises(ValueError, match='align'):
            llm.generate_embeddings(['first', 'second'])
