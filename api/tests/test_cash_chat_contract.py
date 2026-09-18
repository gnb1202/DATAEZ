"""Chat exposes draft references, never the credential used by confirmation UI."""
from uuid import uuid4

from app.cash_agent_tools import CASH_TOOL_SPECS, public_entry


def test_cash_card_reference_preserves_scope_without_confirmation_credential():
    entry_id, project_id, token = uuid4(), uuid4(), uuid4()
    row = {
        'id': entry_id, 'project_id': project_id, 'status': 'draft',
        'payload': {'amount': '30000', 'occurred_on': '2026-09-18', 'kind': 'payment'},
        'confirmation_token': token,
        'similar': {'count': 1, 'entries': [{'id': str(uuid4())}]},
    }
    result = public_entry(row)
    assert result['id'] == str(entry_id)
    assert result['project_id'] == str(project_id)
    assert result['status'] == 'draft'
    assert result['similar_count'] == 1
    assert 'confirmation_token' not in result
    assert 'similar' not in result
    assert str(token) not in str(result)


def test_confirmation_is_not_a_model_tool_or_draft_argument():
    functions = {spec['function']['name']: spec['function'] for spec in CASH_TOOL_SPECS}
    assert set(functions) == {'draft_cash_entry', 'list_cash_entries', 'get_cash_entry'}
    schema = functions['draft_cash_entry']['parameters']
    assert schema['additionalProperties'] is False
    assert 'confirmation_token' not in schema['properties']
    assert 'separate_transaction' not in schema['properties']
