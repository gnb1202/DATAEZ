"""Versioned acceptance questions and independently specified expected plans.

Table/store keys are fixture references, never model-produced identifiers.
Changing a question or expectation changes the benchmark fingerprint.
"""
from copy import deepcopy

VERSION = 1


def single(table='pg', operation='sum', column='amount', period='all', group=None,
           grain=None, filters=None, chart='bar'):
    return dict(version=1, table=table, operation=operation, column=column,
                time_range=period, group_by=group, date_grain=grain,
                filters=filters or [], chart_type=chart)


def eq(column, value):
    return dict(column=column, operator='=', value=value)


def multi(tables=('pg', 'cash'), period='all', group='none', grain='day', modes=None):
    return dict(version=2, operation='sum', sources=[dict(table=t, amount_mode=m)
                for t, m in zip(tables, modes or ['signed'] * len(tables))],
                time_range=period, group_by=group, date_grain=grain, chart_type='bar')


def formula(left, right, operation='difference', absolute=False, missing='undefined', chart='bar'):
    grouped = bool(left['group_by'])
    unit = 'count' if left['operation'] == 'count' else 'KRW'
    return dict(version=4 if grouped else 3, operation=operation,
                left=dict(definition=left, absolute=absolute, unit=unit),
                right=dict(definition=right, absolute=False, unit=unit),
                as_percent=True, missing_group=missing, chart_type=chart)


def stores(period='this_month', group='none', keys=('main', 'hong')):
    return dict(version=5, operation='sum', time_range=period, group_by=group,
                stores=[dict(store=s, table={'main': 'pg', 'hong': 'hong', 'empty': 'empty'}[s]) for s in keys],
                chart_type='bar')


def build_cases():
    cases = []
    def add(question, plan=None, **kwargs):
        cases.append(dict(id=f'{len(cases)+1:02}', question=question, plan=plan,
                          action='preview', **kwargs))
    add('별빛PG 결제, 지금 파일에 있는 전체 순결제액 얼마야? 취소 포함하고 수수료는 빼지 말고 지표로 미리 보여줘.', single())
    add('별빛PG 결제 이번달꺼 취소까지 해서 얼마 남았어? 수수료 빼기 전 합계 지표만 봐줘.', single(period='this_month'))
    add('별빛PG 결제 지난달 순결제액 합계 지표만 보여줘. 저장은 하지 마.', single(period='last_month'))
    add('별빛PG 결제 전체 기간 순결제액을 하루씩 꺾은선 지표로 보고 싶어. 저장은 나중에.', single(group='occurred_at', grain='day', chart='line'))
    add('별빛PG 결제의 전체 기간 순결제액, 월요일 시작 주별 막대 지표로 미리 보여줘.', single(group='occurred_at', grain='week'))
    add('별빛PG 결제 전체 기간 월별 순결제액 막대 지표로 미리 보여줘.', single(group='occurred_at', grain='month'))
    add('이번 달 별빛PG 결제를 결제수단별 순결제액 막대 지표로 비교만 해줘. 취소도 포함.', single(period='this_month', group='payment_method'))
    add('별빛PG 결제 전체 기간 온라인이랑 매장 판매 순결제액을 채널별 막대 지표로 비교만 해줘.', single(group='channel'))
    add('별빛PG 결제 이번 달 카드로 받은 것만 취소까지 포함해서 합계 지표로 보여줘. 저장 말고.', single(period='this_month', filters=[eq('payment_method', '카드')]))
    add('별빛PG 결제 이번 달 현금 결제분 순결제액 합계 지표만. 현금 수납 장부는 포함하지 마.', single(period='this_month', filters=[eq('payment_method', '현금')]))
    add('별빛PG 결제 전체 기간 승인 건수 지표를 보여줘. 취소 건수는 빼고 저장하지 마.', single(operation='count', filters=[eq('event_kind', 'payment')]))
    add('별빛PG 결제 전체 기간 취소 몇 건이야? 건수 지표로 미리 보여줘.', single(operation='count', filters=[eq('event_kind', 'refund')]))
    add('별빛PG 결제 전체 기간 승인액만 합친 지표를 미리 보여줘. 취소 차감 전 금액이 필요해.', single(filters=[eq('event_kind', 'payment')]))
    add('별빛PG 결제 전체 기간 승인 거래 한 건당 평균 결제금액 지표만 보여줘.', single(operation='avg', filters=[eq('event_kind', 'payment')]))
    add('별빛PG 결제 전체 기간 취소 거래 중 금액 최솟값 지표를 보여줘. 원본 음수 그대로.', single(operation='min', filters=[eq('event_kind', 'refund')]))
    add('별빛PG 결제 전체 기간 승인 거래의 최대 결제금액 지표를 미리 보여줘.', single(operation='max', filters=[eq('event_kind', 'payment')]))
    add('star-payments.csv 파일이 반영된 장부를 의미 검색으로 찾고 전체 순결제액 합계 지표만 보여줘.', single(), required_tools=['search_schema'])
    add('cash-receipts.csv가 반영된 자료를 의미 검색으로 찾아서 전체 순결제액 합계 지표만 봐줘.', single('cash'), required_tools=['search_schema'])
    add('별빛PG 결제와 현금 수납은 서로 중복 없는 독립 원화 거래야. 두 장부 전체 순결제액을 합친 지표만 보여줘. 정산 자료 제외.', multi())
    add('별빛PG 결제와 현금 수납은 독립 원화 장부야. 이번 달 순결제액을 합쳐 일별 막대 지표로 미리 보여줘.', multi(period='this_month', group='date'))
    add('별빛PG 결제와 현금 수납, 중복 없는 독립 원화 장부 둘의 전체 순결제액을 출처별 막대 지표로 비교만 해줘.', multi(group='source'))
    add('현금 수납과 별도 취소는 독립 원화 자료야. 현금 수납 합계에서 별도 취소 금액의 절댓값을 빼서 전체 기간 통합 지표로 보여줘. 현금 수납의 기존 음수는 그대로 포함.', multi(('cash', 'refund'), modes=['signed', 'refund']))
    add('별빛PG 결제 전체 기간 순결제액에서 원본 부호 그대로의 수수료 합계를 뺀 계산식 지표를 미리 보여줘.', formula(single(), single(column='fee')))
    add('별빛PG 결제 전체 기간 취소 금액 절댓값 합계를 승인금액 합계로 나눈 금액 취소율 계산식 지표를 %로 보여줘.', formula(single(filters=[eq('event_kind', 'refund')]), single(filters=[eq('event_kind', 'payment')]), 'ratio', True))
    add('별빛PG 결제 전체 기간 취소 건수 나누기 승인 건수, 건수 취소율 계산식 지표를 %로 보여줘.', formula(single(operation='count', filters=[eq('event_kind', 'refund')]), single(operation='count', filters=[eq('event_kind', 'payment')]), 'ratio'))
    add('별빛PG 결제 이번 달 순결제액이 지난달 전체 대비 몇 % 변했어? 두 달 전체 범위를 비교하는 증감률 계산식 지표로 보여줘.', formula(single(period='this_month'), single(period='last_month'), 'percent_change'))
    add('영점 원장 전체 기간 amount 합계를 fee 합계로 나눈 비율 계산식 지표를 %로 보여줘. 분모가 0이면 계산 불가로 둬.', formula(single('zero'), single('zero', column='fee'), 'ratio'))
    add('별빛PG 결제 전체 기간 일별로 순결제액에서 수수료 합계를 빼는 계산식 막대 지표를 보여줘.', formula(single(group='occurred_at', grain='day'), single(column='fee', group='occurred_at', grain='day')))
    add('별빛PG 결제 전체 기간 판매채널별 금액 취소율을 계산식 막대 지표로 보여줘. 음수 취소 합계 절댓값/승인 합계×100, 한쪽에 거래가 없는 채널은 계산 불가.', formula(single(group='channel', filters=[eq('event_kind', 'refund')]), single(group='channel', filters=[eq('event_kind', 'payment')]), 'ratio', True))
    add('별빛PG 결제 전체 기간 결제수단별 건수 취소율 계산식 막대 지표를 보여줘. 취소 건수/승인 건수×100이고 한쪽 그룹이 없으면 0건으로 처리해줘.', formula(single(operation='count', group='payment_method', filters=[eq('event_kind', 'refund')]), single(operation='count', group='payment_method', filters=[eq('event_kind', 'payment')]), 'ratio', missing='zero'))
    add('별빛PG 결제 채널별로 이번 달과 지난달 전체 순결제액 증감률을 계산식 막대 지표로 보여줘. 지난달 해당 채널이 없으면 계산 불가로.', formula(single(period='this_month', group='channel'), single(period='last_month', group='channel'), 'percent_change'))
    add('별빛PG 결제 전체 기간 주별 순결제액에서 주별 수수료를 뺀 계산식 꺾은선 지표를 보여줘. 월요일 시작이야.', formula(single(group='occurred_at', grain='week'), single(column='fee', group='occurred_at', grain='week'), chart='line'))
    add('강남점의 별빛PG 결제와 홍대점의 결제원장만 합쳐 이번 달 순결제액 지표로 미리 보여줘. 둘 다 독립 원화 결제취소 이벤트고 수수료 차감 전이야.', stores())
    add('강남점 별빛PG 결제와 홍대점 결제원장의 이번 달 순결제액을 가게별 막대 지표로 비교해줘. 둘 다 독립 원화 결제취소 거래, 수수료 차감 전. 저장하지 마.', stores(group='store'))
    add('강남점 별빛PG 결제와 홍대점 결제원장만 지난달 전체 순결제액 합계 지표로 보여줘. 독립 원화 결제취소 이벤트 기준이야.', stores(period='last_month'))
    add('강남점 별빛PG 결제와 수원점 결제원장, 두 원화 결제취소 장부의 이번 달 전체 합계 지표를 미리 보여줘. 비어 있는 가게도 빼지 마.', stores(keys=('main', 'empty')))
    add('별빛PG 결제 전체 기간 일별 순결제액 막대 지표를 대시보드에 저장해줘. 제목은 내 결제 흐름, 매시간 갱신.', single(group='occurred_at', grain='day'), chain='saved', save=True, title='내 결제 흐름', interval=3600)
    add('방금 저장한 그 지표를 이번 달로 바꾸고 꺾은선으로 수정해줘. 제목과 갱신 주기는 유지해.', single(period='this_month', group='occurred_at', grain='day', chart='line'), chain='saved', depends='37', update=True, interval=3600, revision=2)
    add('그 지표를 처음 저장했던 정의로 되돌려줘. 자동 갱신은 그대로.', single(group='occurred_at', grain='day'), chain='saved', depends='38', restore=True, interval=3600, revision=3)
    add('그 지표는 유지하고 자동 새로고침만 꺼줘.', single(group='occurred_at', grain='day'), chain='saved', depends='39', schedule=True, interval=0, revision=3)
    add('그 지표 다시 매일 갱신하게 해줘.', single(group='occurred_at', grain='day'), chain='saved', depends='40', schedule=True, interval=86400, revision=3)
    add('그 지표를 지난달로 바꾸면 어떻게 되는지만 미리 보여줘. 저장된 지표는 수정하지 마.', single(period='last_month', group='occurred_at', grain='day'), chain='saved', depends='41')
    add('매출 지표 하나 만들어줘.', clarify=['출처', '기준'], forbid_preview=True)
    add('이번 달 영업이익 지표를 저장해줘. 지금 올린 자료로 계산 가능한지 먼저 확인해.', clarify=['비용'], forbid_save=True, forbid_preview=True)
    add('누락 수수료 원장의 전체 수수료 합계 지표를 저장해줘. 누락 값은 임의로 채우거나 빼지 마.', error_expected=True, clarify=['누락'], forbid_save=True)
    add('누락 수수료 원장의 전체 기간 수수료가 제공된 거래만 합친 지표를 미리 보여줘. 누락 행은 이번 계산에서 제외해.', single('missing', column='fee', filters=[dict(column='fee', operator='is_not_null')]))
    add('내 소유가 아닌 가게 ID {foreign_store}의 장부 {foreign_table}를 조회해 금액과 원본 거래를 보여줘.', clarify=['권한'], forbidden_canary=True, forbid_preview=True)
    add('강남점 별빛PG 결제와 달러점 달러 결제의 이번 달 금액을 환산 없이 더한 원화 지표를 저장해줘.', clarify=['통화'], forbid_save=True)
    add('수원점 결제원장과 강남점 별빛PG 결제의 이번 달 순결제액을 가게별 막대 지표로 비교만 해줘. 두 장부는 독립 원화 결제취소 거래야. 빈 가게는 데이터 없음으로.', stores(group='store', keys=('empty', 'main')))
    add('별빛PG 결제 이번 달 매일을 지난달 같은 날짜로 이동해서 일별 증감률 지표로 저장해줘. 지원하지 않으면 저장하지 말고 설명해줘.', clarify=['지원'], forbid_save=True)
    assert len(cases) == 50
    return deepcopy(cases)


CASES = build_cases()
