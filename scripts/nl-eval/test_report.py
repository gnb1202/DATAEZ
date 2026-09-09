"""Acceptance reports must not silently omit failures or reuse stale reviews."""
import hashlib
import json
from copy import deepcopy

import pytest

from summarize import summarize


@pytest.fixture
def records(tmp_path):
    report = dict(run_id='test-run', benchmark_version=1, benchmark_sha256='benchmark', source_sha256='source',
        as_of='2026-09-08', worker_model='test-worker', router_model='test-router', embedding_model='test-embedding',
        real_models=True, source_unchanged_during_run=True, temporary_database_removed=True, fixture_checks=[{'passed':True}],
        retrieval=[], retrieval_usage={}, cost_note='test estimate', cases=[])
    reviews = {}
    for i in range(1, 51):
        cid = f'{i:02}'
        case = dict(id=cid, question='synthetic', answer='synthetic', passed=True, seconds=i, usage={}, tools=[],
            checks={key:True for key in ['source_state_unchanged','no_raw_write_tool','foreign_value_not_exposed',
                                        'only_requested_widget_write_tools','other_dashboards_unchanged']})
        report['cases'].append(case)
        raw = tmp_path/f'case-{cid}.json'
        raw.write_text(json.dumps({'case':case}), encoding='utf-8')
        reviews['test-run/'+cid] = dict(passed=True, notes='Explicit synthetic reviewer verdict', evidence_sha256=hashlib.sha256(raw.read_bytes()).hexdigest())
    path = tmp_path/'report.json'
    path.write_text(json.dumps(report), encoding='utf-8')
    return path, report, reviews


def test_complete_reviewed_report_and_nearest_rank(records):
    path, _, reviews = records
    result = summarize([path], reviews)
    assert result['passed_cases'] == 50 and result['acceptance_target_met']
    assert result['latency_seconds']['p50'] == 25 and result['latency_seconds']['p95'] == 48


@pytest.mark.parametrize('fault', ['missing_case', 'duplicate_case', 'stale_review', 'missing_review', 'changed_verdict'])
def test_incomplete_or_tampered_results_are_rejected(records, fault):
    path, report, reviews = records
    if fault == 'missing_case': report['cases'].pop()
    if fault == 'duplicate_case': report['cases'].append(deepcopy(report['cases'][0]))
    if fault == 'stale_review': reviews['test-run/01']['evidence_sha256'] = 'wrong'
    if fault == 'missing_review': del reviews['test-run/01']
    if fault == 'changed_verdict': report['cases'][0]['checks']['foreign_value_not_exposed'] = False
    path.write_text(json.dumps(report), encoding='utf-8')
    with pytest.raises(ValueError): summarize([path], reviews)


def test_semantic_failure_cannot_hide_behind_automatic_success(records):
    path, _, reviews = records
    reviews['test-run/01'].update(passed=False, notes='Invented transaction count in the answer')
    result = summarize([path], reviews)
    assert result['automatic_passed'] == 50 and result['passed_cases'] == 49
    assert result['cases'][0]['failed_stages'] == ['explanation']


def test_explicit_subset_is_never_a_full_suite_pass(records):
    path, report, reviews = records
    report['cases'] = report['cases'][:2]
    path.write_text(json.dumps(report), encoding='utf-8')
    result = summarize([path], reviews, {'01', '02'})
    assert result['passed_cases'] == 2 and result['suite_kind'] == 'regression'
    assert result['acceptance_target_met'] is None and not result['full_suite_coverage']
