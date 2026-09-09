"""Read-only file guidance. Suggestions are candidates, never payment semantics."""
import re
from decimal import Decimal, localcontext
from hashlib import sha256

from . import db
from .data_import import _load_dataframe
from .import_validation import ImportValidationError, issue
from .ledger_imports import _store
from .payment_imports import _prepare_payment_frame


ALIASES = {
    'amount_column': {'amount', 'money', '금액', '결제금액', '승인금액', '취소금액'},
    'occurred_at_column': {'occurredat', 'paidat', 'day', 'date', '발생일시', '거래일시', '거래일자', '결제일시', '결제일', '승인일시', '취소일시'},
    'event_id_column': {'eventid', '이벤트id', '이벤트아이디', '이벤트번호'},
    'original_event_id_column': {'originaleventid', '원거래id', '원거래번호'},
    'currency_column': {'currency', '통화', '통화코드'},
    'payment_method_column': {'paymentmethod', '결제수단', '지불수단'},
    'channel_column': {'channel', '판매채널', '채널'},
    'fee_column': {'fee', 'pgfee', 'pg수수료', '수수료'},
}


def _read(user_id, project_id, content, filename):
    # Release the owner check connection before parsing a potentially large file.
    with db._connect() as conn, conn.cursor() as cur:
        _store(cur, user_id, project_id)
    frame = _load_dataframe(content, filename)
    if not len(frame) or len(frame) > 100000 or len(frame.columns) > 200:
        raise ImportValidationError([issue(1, '', '1~100,000행, 최대 200개 컬럼의 결제 파일을 사용해주세요.')])
    if len(set(frame.columns)) != len(frame.columns) or any(len(str(c)) > 200 for c in frame.columns):
        raise ImportValidationError([issue(1, '', '원본 컬럼 이름을 중복 없이 200자 이하로 정리해주세요.')])
    return frame


def _candidates(frame):
    return {role: [str(c) for c in frame.columns if re.sub(r'[\s_\-]', '', str(c)).lower() in names]
            for role, names in ALIASES.items()}


def inspect_file(user_id, project_id, content, filename):
    frame = _read(user_id, project_id, content, filename)
    candidates = _candidates(frame)
    return {'filename': filename, 'fingerprint': sha256(content).hexdigest(), 'row_count': len(frame),
            'columns': list(frame.columns), 'candidates': candidates,
            'suggested_mapping': {role: names[0] if len(names) == 1 else None for role, names in candidates.items()},
            'sample': [{'row': frame.attrs['row_numbers'][i], 'values': [None if v is None else str(v)[:160] for v in row]}
                       for i, row in enumerate(frame.head(5).itertuples(index=False, name=None))],
            'sample_is_partial': len(frame) > 5, 'first_sheet_only': filename.lower().endswith(('.xlsx', '.xls')),
            'stored': False}


def validate_mapping(user_id, project_id, content, filename, mapping):
    frame = _read(user_id, project_id, content, filename)
    if _candidates(frame)['currency_column'] and not mapping.currency_column:
        raise ImportValidationError([issue(1, '', '통화 컬럼이 있습니다. 원화 여부를 검사할 통화 컬럼을 연결해주세요.')])
    prepared = _prepare_payment_frame(frame, mapping)
    amounts = [r[3] for r in prepared.rows]
    with localcontext() as ctx:
        integer_digits = max(max(1, amount.adjusted() + 1) for amount in amounts)
        scale = max(max(0, -amount.as_tuple().exponent) for amount in amounts)
        ctx.prec = integer_digits + scale + len(str(len(amounts))) + 2
        total = sum(amounts, Decimal(0))
    return {'row_count': len(prepared.rows), 'amount': str(total), 'currency': 'KRW',
            'mapping': mapping.model_dump(mode='json'), 'stored': False,
            'sample': [{'row': n, 'event_id': r[0], 'event_kind': r[2], 'amount': str(r[3]), 'occurred_at': r[4]}
                       for n, r in zip(prepared.row_numbers[:5], prepared.rows[:5])],
            'note': '파일 전체의 형식과 금액을 확인했습니다. 중복 제외 후 최종 반영액은 다음 단계에서 확인하세요.'}
