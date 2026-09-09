"""Chat can prepare cash records, but only the review screen commits them."""
from typing import Literal
from fastapi.encoders import jsonable_encoder
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field


class CashToolDraft(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    amount: str = Field(description='0보다 큰 원화 금액. 쉼표 없이 문자열, 소수점 최대 두 자리')
    occurred_on: str | None = Field(default=None, description='거래 일자 YYYY-MM-DD. 생략하면 오늘 한국 날짜. 시각은 수집하지 않음')
    kind: Literal['payment', 'refund'] = 'payment'
    channel: str | None = Field(default=None, max_length=80)
    memo: str = Field(default='', max_length=500)
    original_event_id: str | None = Field(default=None, description='현금 취소 기록의 원거래 ID. 확인한 경우만 제공')


class CashToolList(BaseModel):
    model_config = ConfigDict(extra='forbid')
    offset: int = Field(default=0, ge=0)


class CashToolGet(BaseModel):
    model_config = ConfigDict(extra='forbid')
    entry_id: UUID


CASH_TOOL_SPECS = [
    {'type':'function','function':{'name':name,'description':description,'parameters':model.model_json_schema()}}
    for name, description, model in [
        ('draft_cash_entry','현재 가게의 현금 수납·취소 입력 초안을 작성합니다. 장부에는 아직 반영되지 않습니다. review_url에서 사용자가 확인·반영해야 합니다. 실제 환불/결제는 수행하지 않습니다.',CashToolDraft),
        ('list_cash_entries','현재 가게의 현금 입력 이력과 미반영 초안을 최신순 20건 조회합니다.',CashToolList),
        ('get_cash_entry','확인한 entry_id로 현금 입력 초안·반영 상태·메모·중복 의심 기록과 검토 링크를 조회합니다.',CashToolGet),
    ]
]


def public_entry(row):
    row = jsonable_encoder(row)
    return {k:v for k,v in row.items() if k not in ('confirmation_token','similar') } | {
        'similar_count':row.get('similar',{}).get('count',0),
        'hint':'초안은 장부에 아직 반영되지 않습니다. 검토하기 버튼에서 거래 일자·금액·메모를 확인하고 반영하세요. 날짜만 기록하므로 시간대 분석은 지원하지 않습니다.' if row['status']=='draft' else '저장된 현금 입력 상태입니다.'}
