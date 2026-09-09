"""Small independent CSV/Decimal oracle; imports no application code or SQL.

Expected plans come from cases.py. They are never taken from an agent output.
"""
import csv
import io
from collections import defaultdict
from datetime import datetime, timedelta
from decimal import Decimal, localcontext, ROUND_HALF_EVEN
from zoneinfo import ZoneInfo

KST = ZoneInfo('Asia/Seoul')
NAMES = {'pg': '별빛PG 결제', 'cash': '현금 수납', 'hong': '결제원장',
         'empty': '결제원장', 'refund': '별도 취소', 'missing': '누락 수수료 원장',
         'zero': '영점 원장', 'usd': '달러 결제', 'settlement': '정산 참고자료',
         'foreign': '비공개 외부 원장'}
STORE_NAMES = {'main': '강남점', 'hong': '홍대점', 'empty': '수원점', 'usd': '달러점', 'foreign': '외부 소유 가게'}
TABLE_STORE = {key: key if key in {'hong', 'empty', 'usd', 'foreign'} else 'main' for key in NAMES}
CANARY = '9876543212345'


def fixture(today):
    month = today.replace(day=1)
    previous = month - timedelta(days=1)
    def row(amount, day, fee='0', method='카드', channel='온라인', currency='KRW'):
        return dict(amount=str(amount), occurred_at=f'{day}T12:00:00+09:00', fee=fee,
                    payment_method=method, channel=channel, currency=currency,
                    event_kind='refund' if Decimal(amount) < 0 else 'payment')
    pg = [row(60000, previous, '1800'), row(100000, month, '3000'),
          row(-20000, month+timedelta(days=1), '-600'),
          row(50000, month+timedelta(days=2), '1500', channel='매장'),
          row(40000, month+timedelta(days=3), '1200', '현금', '매장'),
          row(-10000, month+timedelta(days=3), '-300', '현금', '매장'),
          row(12000, month+timedelta(days=2), '360', '계좌이체', '방문')]
    # Boundary in two encodings; the UTC row belongs to the next Korean month.
    pg[0]['occurred_at'] = f'{previous}T23:55:00+09:00'
    pg[1]['occurred_at'] = f'{previous}T15:05:00+00:00'
    return {
        'pg': pg,
        'cash': [row(10000, previous), row(20000, month), row(30000, month+timedelta(days=1)), row(-5000, month+timedelta(days=1))],
        'hong': [row(40000, previous), row(200000, month), row(-30000, month+timedelta(days=1))],
        'empty': [row(999999, previous)],
        'refund': [row(7000, month), row(-3000, month+timedelta(days=1))],
        'missing': [row(10000, month, None), row(20000, month, '600')],
        'zero': [row(1000, month), row(2000, month+timedelta(days=1))],
        'usd': [row(200, month, currency='USD')],
        'settlement': [dict(입금액='225000', 정산일=str(month), 메모='원금 합산 금지: 실제 입금 참고자료')],
        'foreign': [row(CANARY, month)],
    }


def csv_bytes(rows):
    stream = io.StringIO(newline='')
    writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue().encode('utf-8-sig')


def day(row):
    return datetime.fromisoformat(row['occurred_at']).astimezone(KST).date()


def in_period(row, period, today):
    d = day(row)
    month = today.replace(day=1)
    prev = (month-timedelta(days=1)).replace(day=1)
    next_month = (month+timedelta(days=32)).replace(day=1)
    if period == 'all': return True
    if period == 'this_month': return month <= d < next_month
    if period == 'last_month': return prev <= d < month
    if period == 'last_30_days': return today-timedelta(days=29) <= d <= today
    raise ValueError(period)


def matches(row, filters):
    for f in filters:
        value = row.get(f['column'])
        op = f.get('operator', '=')
        if op == 'is_null': ok = value is None
        elif op == 'is_not_null': ok = value is not None
        else:
            wanted = f['value']
            if f['column'] in {'amount', 'fee'} and value is not None:
                value, wanted = Decimal(value), Decimal(wanted)
            if value is None: ok = False
            elif op == '=': ok = value == wanted
            elif op == '!=': ok = value != wanted
            elif op == '>': ok = value > wanted
            elif op == '>=': ok = value >= wanted
            elif op == '<': ok = value < wanted
            elif op == '<=': ok = value <= wanted
            else: raise ValueError(op)
        if not ok: return False
    return True


def dimension(row, column, grain):
    if not column: return None
    if not grain: return row[column]
    d = day(row)
    if grain == 'week': d -= timedelta(days=d.weekday())
    if grain == 'month': d = d.replace(day=1)
    return str(d)


def aggregate(rows, plan, today):
    selected = [r for r in rows if in_period(r, plan.get('time_range', 'all'), today) and matches(r, plan.get('filters', []))]
    grouped = defaultdict(list)
    if not plan.get('group_by'): grouped[None] = selected
    else:
        for row in selected:
            grouped[dimension(row, plan['group_by'], plan.get('date_grain'))].append(row)
    result = {}
    for key, items in grouped.items():
        if plan['operation'] == 'count': result[key] = Decimal(len(items)); continue
        values = [None if r.get(plan['column']) is None else Decimal(r[plan['column']]) for r in items]
        if None in values: raise ValueError('Missing number must block calculation')
        if not values: result[key] = None; continue
        op = plan['operation']
        if op == 'sum': result[key] = sum(values, Decimal(0))
        elif op == 'avg': result[key] = sum(values, Decimal(0))/len(values)
        elif op == 'min': result[key] = min(values)
        elif op == 'max': result[key] = max(values)
        else: raise ValueError(op)
    return result


def expected(plan, rows, today):
    v = plan['version']
    if v == 1: return aggregate(rows[plan['table']], plan, today)
    if v == 2:
        result = defaultdict(Decimal)
        for source in plan['sources']:
            for row in rows[source['table']]:
                if not in_period(row, plan['time_range'], today): continue
                key = source['table'] if plan['group_by'] == 'source' else dimension(row, 'occurred_at', plan['date_grain']) if plan['group_by'] == 'date' else None
                amount = Decimal(row['amount'])
                result[key] += -abs(amount) if source['amount_mode'] == 'refund' else amount
        return dict(result) or {None: None}
    if v == 5:
        totals = {s['store']: aggregate(rows[s['table']], dict(operation='sum', column='amount', time_range=plan['time_range']), today)[None] for s in plan['stores']}
        if plan['group_by'] == 'store': return totals
        return {None: None if None in totals.values() else sum(totals.values(), Decimal(0))}
    left = expected(plan['left']['definition'], rows, today)
    right = expected(plan['right']['definition'], rows, today)
    result = {}
    for key in left.keys() | right.keys():
        default = Decimal(0) if v == 4 and plan['missing_group'] == 'zero' else None
        a, b = left.get(key, default), right.get(key, default)
        a = abs(a) if a is not None and plan['left']['absolute'] else a
        b = abs(b) if b is not None and plan['right']['absolute'] else b
        if a is None or b is None or (b == 0 and plan['operation'] != 'difference'):
            result[key] = None
        elif plan['operation'] == 'difference': result[key] = a-b
        else:
            with localcontext() as ctx:
                ctx.prec = 50
                value = (a-b)/abs(b)*100 if plan['operation'] == 'percent_change' else a/b*(100 if plan['as_percent'] else 1)
                result[key] = value.quantize(Decimal('.0001'), rounding=ROUND_HALF_EVEN)
    return result


def normalized_values(output, plan, table_ids, store_ids):
    """Read exact result cells, never match a number substring in JSON."""
    if 'value' in output: return {None: None if output['value'] is None else Decimal(str(output['value']))}
    result = {}
    tid_keys = {v: k for k, v in table_ids.items()}
    sid_keys = {v: k for k, v in store_ids.items()}
    labels = {s['label']: tid_keys.get(s['table_id']) for s in output.get('metric_definition', {}).get('sources', [])}
    for row in output.get('data', []):
        key = row.get('dimension')
        if plan['version'] == 5: key = sid_keys.get(row.get('project_id'), 'UNKNOWN_STORE')
        elif plan['version'] == 2 and plan['group_by'] == 'source': key = labels.get(key, 'UNKNOWN_SOURCE')
        elif plan.get('date_grain') or (plan['version'] == 4 and plan['left']['definition'].get('date_grain')):
            key = str(key)[:10]
        if key in result: raise ValueError('Duplicate result dimension')
        result[key] = None if row.get('value') is None else Decimal(str(row['value']))
    return result
