"""Independent fixture oracle: stdlib CSV/Decimal only; never app SQL/results."""
import csv
from collections import defaultdict
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
SAMPLES = ROOT / 'samples/pg-evaluation'


def read(name):
    with (SAMPLES / name).open(encoding='utf-8-sig', newline='') as f:
        return list(csv.DictReader(f))


def events(name, cash=False):
    return [{'id': r.get('거래번호'), 'amount': Decimal(r['금액' if cash else '거래금액']),
             'day': datetime.fromisoformat(r['발생일시' if cash else '거래일시']).astimezone(ZoneInfo('Asia/Seoul')).date().isoformat()}
            for r in read(name)]


def aggregate(rows):
    daily = defaultdict(Decimal)
    monthly = defaultdict(Decimal)
    for r in rows:
        daily[r['day']] += r['amount']
        monthly[r['day'][:7]] += r['amount']
    return {'rows': len(rows), 'net': str(sum((r['amount'] for r in rows), Decimal(0))),
            'payments': sum(r['amount'] >= 0 for r in rows), 'refunds': sum(r['amount'] < 0 for r in rows),
            'gross': str(sum((r['amount'] for r in rows if r['amount'] >= 0), Decimal(0))),
            'refund_amount': str(sum((r['amount'] for r in rows if r['amount'] < 0), Decimal(0))),
            'daily': {k: str(v) for k, v in sorted(daily.items())},
            'monthly': {k: str(v) for k, v in sorted(monthly.items())}}


def expected():
    first = events('01_gangnam_pg.csv')
    overlapping = events('03_gangnam_pg_overlap.csv')
    known = {(r['id'], r['amount'] < 0): r for r in first}
    new = []
    for r in overlapping:
        key = (r['id'], r['amount'] < 0)
        if key in known:
            assert known[key] == r
        else:
            new.append(r)
            known[key] = r
    cash_first = events('08_cash_first.csv', True)
    # Explicit business labels: exclude file row 2; include file rows 3,4,5.
    cash = cash_first + events('09_cash_review.csv', True)[1:]
    pg = first + new
    return {'as_of': '2026-09-08', 'synthetic': True,
            'gangnam_first': aggregate(first), 'overlap_added': aggregate(new),
            'gangnam_pg': aggregate(pg), 'gangnam_cash': aggregate(cash),
            'gangnam_combined': aggregate(pg + cash), 'hongdae_pg': aggregate(events('07_hongdae_pg.csv')),
            'overlap_duplicates': len(overlapping) - len(new),
            'cash_review': {'candidate': 2, 'include': 1, 'exclude': 1, 'new': 2, 'rows_added': 3},
            'precision': '9007199254740993.01'}


if __name__ == '__main__':
    import json
    result = expected()
    (SAMPLES / 'expected.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False, indent=2))
