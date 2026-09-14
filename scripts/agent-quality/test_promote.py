import json
import pytest
from catalog import load_catalog
from promote import promote


def inputs(tmp_path):
    case = dict(load_catalog()['cases'][0])
    case.update(id='Regression01',question='합성 파일의 일별 매출을 선그래프로 보여줘',review='합성 파일의 전체 기간 일별 합계가 정답과 일치해야 한다')
    candidate={'schema_version':1,'kind':'synthetic_regression_candidate','question':case['question'],
               'expected_behavior':case['review'],'synthetic_confirmed':True}
    c,contract,out=(tmp_path/name for name in ('candidate.json','contract.json','new.json'))
    c.write_text(json.dumps(candidate),encoding='utf-8')
    contract.write_text(json.dumps(case),encoding='utf-8')
    return c,contract,out,case


def test_promote_new_catalog_no_overwrite(tmp_path):
    c,contract,out,_=inputs(tmp_path)
    assert promote(c,contract,out)=='Regression01'
    assert len(load_catalog(out)['cases'])==25
    with pytest.raises(FileExistsError): promote(c,contract,out)


@pytest.mark.parametrize('mutation', ['wrong_total','unreviewed','private_fields','changed_question','changed_review'])
def test_reject_invalid_candidates(tmp_path,mutation):
    c,contract,out,case=inputs(tmp_path)
    candidate=json.loads(c.read_text())
    if mutation=='wrong_total': case['expected']={'2026-09-01':'1'}
    elif mutation=='unreviewed': candidate['synthetic_confirmed']=False
    elif mutation=='private_fields': candidate['answer']='PRIVATE'
    elif mutation=='changed_question': case['question']='different question'
    elif mutation=='changed_review': case['review']='different criterion'
    c.write_text(json.dumps(candidate),encoding='utf-8');contract.write_text(json.dumps(case),encoding='utf-8')
    with pytest.raises(ValueError): promote(c,contract,out)
    assert not out.exists()
