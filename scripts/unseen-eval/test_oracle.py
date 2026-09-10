import csv
from decimal import Decimal
import json
from fixtures import FILES, DATA, expected
from cases import CASES,HOLDOUT,manifest
from grading import shape,values

def test_suite_is_fixed_and_disjoint():
    assert len(CASES)==30 and len(HOLDOUT)==10
    assert len({c['id'] for c in CASES+HOLDOUT})==40
    assert json.loads((DATA/'manifest.json').read_text(encoding='utf-8'))==manifest()

def test_independent_controls():
    assert Decimal(expected(CASES[0])['__NULL__'])==Decimal('64002.10')
    assert Decimal(expected(CASES[10])['__NULL__'])==Decimal('70102.71')
    assert Decimal(expected(CASES[8])['__NULL__'])==Decimal('16211.63')
    assert Decimal(expected(HOLDOUT[0])['__NULL__'])==Decimal('7701.40')
    assert expected(CASES[11])=={'__NULL__':'2'}
    assert expected(HOLDOUT[4])=={'__NULL__':'1'}
    assert expected(CASES[4])['__NULL__']=='3500.35'

def test_csv_identifiers_and_nulls_are_preserved():
    with (DATA/'a'/FILES['a']['filename']).open(encoding='utf-8-sig',newline='') as f:rows=list(csv.DictReader(f))
    assert rows[0]['주문번호']=='000900719925474099301'
    assert rows[6]['결제수단']=='' and rows[7]['승인금액']=='0'

def test_grader_distinguishes_wrong_source_filters_and_missing_values():
    base={'table_id':'a','operation':'sum','column':'금액'}
    assert shape(base)!=shape({**base,'table_id':'b'})
    assert shape(base)!=shape({**base,'filters':[{'column':'금액','operator':'>','value':'0'}]})
    assert values({'value':None},{})!=values({'value':'0'},{})
