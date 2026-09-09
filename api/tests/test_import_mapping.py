"""First-upload guidance uses full validation without creating data or profiles."""
from io import BytesIO
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from openpyxl import Workbook
from fastapi.testclient import TestClient
from app import import_mapping as service
from app.payment_imports import PaymentImportMapping
from app.import_validation import ImportValidationError
from .test_import_postgres import live, DSN


CONTENT = '이벤트ID,결제금액,결제일시,통화,결제수단\n00001,100000,2026-09-01,KRW,카드\n00002,-20000,2026-09-02,KRW,카드\n'.encode()
MAPPING = {'amount_column':'결제금액','occurred_at_column':'결제일시','currency_column':'통화','event_id_column':'이벤트ID','event_kind':'signed'}


@pytest.fixture
def readonly():
    with patch.object(service.db,'_connect',return_value=MagicMock()),patch.object(service,'_store'):
        yield


def inspect(content=CONTENT, filename='test.csv'):
    return service.inspect_file('owner','store',content,filename)


def validate(content=CONTENT, mapping=None, filename='test.csv'):
    return service.validate_mapping('owner','store',content,filename,PaymentImportMapping(**(mapping or MAPPING)))


def test_candidates_preserve_original_columns_and_text_id(readonly):
    result=inspect()
    assert result['suggested_mapping']['amount_column']=='결제금액'
    assert result['suggested_mapping']['event_id_column']=='이벤트ID'
    assert result['sample'][0]['values'][0]=='00001' and result['row_count']==2
    assert result['stored'] is False and len(result['fingerprint'])==64
    assert 'event_kind' not in result['suggested_mapping']
    result=validate()
    assert result['amount']=='80000' and result['stored'] is False
    assert result['sample'][1]['event_kind']=='refund'
    assert result['sample'][0]['occurred_at'].endswith('+09:00')


def test_ambiguous_or_unknown_names_are_not_automatically_selected(readonly):
    result=inspect('승인금액,취소금액,정산입금액,거래번호\n100,10,90,0001\n'.encode())
    assert result['candidates']['amount_column']==['승인금액','취소금액']
    assert result['suggested_mapping']['amount_column'] is None
    assert result['suggested_mapping']['event_id_column'] is None


@pytest.mark.parametrize('content', [b'amount,amount\n1,2\n', b'amount,day\n', b'amount,day\n1,2026-09-01,extra\n', b''])
def test_invalid_file_has_actionable_validation_error(readonly,content):
    with pytest.raises(ImportValidationError): inspect(content)


def test_sample_does_not_hide_late_row_validation_failure(readonly):
    content=('amount,day\n'+'100,2026-09-01\n'*8+'bad,2026-09-01\n').encode()
    assert inspect(content)['sample_is_partial']
    with pytest.raises(ImportValidationError) as error:
        validate(content,{'amount_column':'amount','occurred_at_column':'day'})
    assert error.value.issues[0]['row']==10


@pytest.mark.parametrize('change',[{'currency_column':None},{'amount_column':'통화'},{'occurred_at_column':'missing'},{'event_kind':'payment'}])
def test_bad_mapping_is_rejected(readonly,change):
    with pytest.raises(ImportValidationError): validate(mapping={**MAPPING,**change})


@pytest.mark.parametrize('currency',['USD',''])
def test_foreign_or_missing_currency_is_not_hidden(readonly,currency):
    with pytest.raises(ImportValidationError): validate(CONTENT.replace(b'KRW',currency.encode()))


def test_exact_total_beyond_default_decimal_context(readonly):
    number='90071992547409939999999999999999.01'
    result=validate(f'amount,day\n{number},2026-09-01\n0.01,2026-09-01\n'.encode(),{'amount_column':'amount','occurred_at_column':'day'})
    assert result['amount']=='90071992547409939999999999999999.02'
    tiny='9'*1000+'e-1999'
    result=validate(f'amount,day\n1e1000,2026-09-01\n{tiny},2026-09-01\n'.encode(),{'amount_column':'amount','occurred_at_column':'day'})
    assert result['amount']=='1'+'0'*1000+'.'+'0'*999+'9'*1000


def test_excel_first_sheet_and_numeric_id_rules(readonly):
    book=Workbook();sheet=book.active;sheet.append(['event_id','amount','day']);sheet.append(['0001',100,'2026-09-01'])
    book.create_sheet('ignored').append(['not a ledger']);out=BytesIO();book.save(out)
    assert inspect(out.getvalue(),'book.xlsx')['first_sheet_only']
    mapping={'event_id_column':'event_id','amount_column':'amount','occurred_at_column':'day'}
    assert validate(out.getvalue(),mapping,'book.xlsx')['sample'][0]['event_id']=='0001'
    sheet['A2']=123;out=BytesIO();book.save(out)
    with pytest.raises(ImportValidationError): validate(out.getvalue(),mapping,'book.xlsx')


@pytest.mark.skipif(not DSN,reason='Set DATAEZ_TEST_DATABASE_URL')
def test_authenticated_routes_ownership_and_no_persistent_writes(live):
    from app import main
    from app.auth import get_current_user
    connect,_,user,store,other=live
    client=TestClient(main.app)
    main.app.dependency_overrides[get_current_user]=lambda:{'id':user}
    try:
        for endpoint in ('inspect','validate'):
            path=f'/api/projects/{store}/import-mapping/{endpoint}'
            kwargs={'files':{'file':('payments.csv',CONTENT)},'data':{'mapping':PaymentImportMapping(**MAPPING).model_dump_json()}}
            response=client.post(path,**kwargs);assert response.status_code==200,response.text
            assert response.json()['stored'] is False
            foreign=client.post(path.replace(store,str(uuid4())),**kwargs);assert foreign.status_code==404
        with connect() as conn:
            for table in ('table_meta','files','ledger_sources','import_batches'):
                assert conn.execute(f'SELECT count(*) AS n FROM {table}').fetchone()['n']==0
        assert client.post(f'/api/projects/{store}/import-mapping/validate',files={'file':('file.csv',CONTENT)},data={'mapping':'broken'}).status_code==422
    finally: main.app.dependency_overrides.pop(get_current_user,None)
