"""G expected values from immutable raw CSVs; no application code or SQL."""
import csv
from collections import defaultdict
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SAMPLES = ROOT / 'samples/pg-evaluation'


def expected():
    events = {}
    for name in ['01_gangnam_pg.csv', '03_gangnam_pg_overlap.csv']:
        with (SAMPLES / name).open(encoding='utf-8-sig', newline='') as file:
            for row in csv.DictReader(file):
                key = (row['거래번호'], row['거래구분'])
                if key in events:
                    assert events[key] == row, 'Fixture event changed across files'
                events[key] = row
    result = {'rows': len(events)}
    for column, output in [('결제수단', 'methods'), ('판매채널', 'channels')]:
        groups = defaultdict(lambda: {'amount': Decimal(0), 'fee': Decimal(0), 'count': 0})
        for row in events.values():
            group = groups[row[column]]
            group['amount'] += Decimal(row['거래금액'])
            group['fee'] += Decimal(row['PG수수료'])
            group['count'] += 1
        result[output] = {k: {f: str(v) if isinstance(v, Decimal) else v for f, v in group.items()} for k, group in groups.items()}
    result['fee_total'] = str(sum((Decimal(row['PG수수료']) for row in events.values()), Decimal(0)))
    return result
