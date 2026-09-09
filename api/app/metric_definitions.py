"""Versioned, executable metric contracts. Version 1 remains backwards compatible."""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator, TypeAdapter


class MetricFilter(BaseModel):
    model_config = ConfigDict(extra="forbid")
    column: str = Field(min_length=1, max_length=200)
    operator: Literal["=", "!=", ">", ">=", "<", "<=", "is_null", "is_not_null"] = Field(
        default="=", description="사용자가 요청한 필터만 지정합니다. is_not_null이나 빈 문자열 제외(!= '')로 누락 값을 없애려면 사용자 명시가 필요합니다. 현재 표본에 누락이 없어도 예방적으로 넣지 마세요.")
    value: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def check_value(self):
        if self.operator in {"is_null", "is_not_null"}:
            if self.value is not None:
                raise ValueError("미제공 여부 필터에는 value를 지정하지 마세요.")
        elif self.value is None:
            raise ValueError("비교 필터에는 value가 필요합니다.")
        return self


class MetricDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    version: Literal[1] = 1
    table_id: UUID
    unit: Literal["KRW", "count", "number"] | None = Field(default=None, description="확인한 데이터 단위. 원화 KRW, 건수 count, 일반 숫자 number. 환산하지 않습니다.")
    operation: Literal["sum", "count", "avg", "min", "max"] = "sum"
    column: str | None = Field(default=None, min_length=1, max_length=200)
    group_by: str | None = Field(default=None, min_length=1, max_length=200)
    date_grain: Literal["day", "week", "month"] | None = None
    chart_type: Literal["bar", "line", "pie"] = "bar"
    date_column: str | None = Field(default=None, min_length=1, max_length=200)
    time_range: Literal["all", "this_month", "last_month", "last_30_days"] = "all"
    filters: list[MetricFilter] = Field(default_factory=list, max_length=10)

    @model_validator(mode="after")
    def check_definition(self):
        if self.operation == "count" and self.unit not in (None,"count"):
            raise ValueError("행 건수 지표의 단위는 건수입니다.")
        if self.operation != "count" and not self.column:
            raise ValueError("집계할 숫자 컬럼을 선택해주세요.")
        if self.date_grain and not self.group_by:
            raise ValueError("날짜 단위에는 그룹 컬럼이 필요합니다.")
        if self.time_range != "all" and not self.date_column:
            raise ValueError("기간 필터에 사용할 날짜 컬럼이 필요합니다.")
        return self


class MetricSource(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    table_id: UUID
    label: str = Field(min_length=1, max_length=80)
    column: str = Field(min_length=1, max_length=200)
    date_column: str | None = Field(default=None, min_length=1, max_length=200)
    # signed: positive payments / negative cancellations already in the source.
    # refund: a separate cancellation-event ledger, normalized to -abs(amount).
    amount_mode: Literal["signed", "refund"] = Field(default="signed", description=
        "signed는 원본 부호 합계. refund는 별도 취소 장부의 각 거래 금액에 -abs를 적용한 뒤 합산(-SUM(ABS(amount))). 양수·음수 취소가 섞여도 각각 차감합니다.")
    currency: Literal["KRW"] = "KRW"
    filters: list[MetricFilter] = Field(default_factory=list, max_length=10)


class MultiMetricDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    version: Literal[2] = 2
    operation: Literal["sum"] = "sum"
    sources: list[MetricSource] = Field(min_length=2, max_length=5)
    group_by: Literal["none", "date", "source"] = "none"
    date_grain: Literal["day", "week", "month"] = "day"
    time_range: Literal["all", "this_month", "last_month", "last_30_days"] = "all"
    chart_type: Literal["bar", "line"] = "bar"

    @model_validator(mode="after")
    def validate_sources(self):
        if len({s.table_id for s in self.sources}) != len(self.sources):
            raise ValueError("같은 장부를 통합 지표에 두 번 포함할 수 없습니다.")
        if len({s.label for s in self.sources}) != len(self.sources):
            raise ValueError("장부별 표시 이름은 서로 달라야 합니다.")
        if self.group_by == "date" or self.time_range != "all":
            if any(not s.date_column for s in self.sources):
                raise ValueError("날짜별 집계·기간 필터에는 모든 장부의 날짜 컬럼이 필요합니다.")
        return self


# The v1 member accepts old payloads without an explicit version. v2 has a
# different required shape; extra='forbid' prevents mixing the two contracts.
class FormulaOperand(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    label: str = Field(min_length=1, max_length=80)
    definition: MetricDefinition
    unit: Literal["KRW", "count", "number"]
    absolute: bool = Field(default=False, description=
        "집계 결과에 절댓값을 적용합니다(ABS(SUM(amount))). 개별 거래 절댓값 합계(SUM(ABS(amount)))와 다릅니다. 별도 취소 장부를 차감하는 통합 지표는 v2 sources.amount_mode=refund를 사용하세요.")

    @model_validator(mode="after")
    def scalar_only(self):
        if self.definition.unit is not None and self.definition.unit != self.unit:
            raise ValueError("집계 단위와 계산식 항목의 단위가 다릅니다.")
        if self.definition.group_by:
            raise ValueError("계산식의 각 항목은 그룹 없는 집계여야 합니다.")
        if self.definition.operation == "count" and self.unit != "count":
            raise ValueError("행 건수의 단위는 count입니다.")
        return self


class FormulaMetricDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    version: Literal[3] = 3
    operation: Literal["difference", "ratio", "percent_change"]
    left: FormulaOperand
    right: FormulaOperand
    as_percent: bool = True

    @model_validator(mode="after")
    def compatible_units(self):
        if self.left.unit != self.right.unit:
            raise ValueError("두 집계의 단위가 같아야 합니다. 원화·건수 등 다른 단위를 섞지 마세요.")
        if self.operation != 'ratio' and not self.as_percent:
            raise ValueError("as_percent는 ratio에서만 변경할 수 있습니다.")
        return self


class GroupedFormulaOperand(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    label: str = Field(min_length=1, max_length=80)
    definition: MetricDefinition
    unit: Literal['KRW', 'count', 'number']
    absolute: bool = Field(default=False, description=
        "각 그룹의 집계 결과에 절댓값을 적용합니다. 개별 행 절댓값 합계가 아니며, 부호가 혼합된 취소 원장을 차감하는 용도로 쓰지 마세요.")

    @model_validator(mode='after')
    def grouped_only(self):
        if self.definition.unit is not None and self.definition.unit != self.unit:
            raise ValueError("집계 단위와 계산식 항목의 단위가 다릅니다.")
        if not self.definition.group_by:
            raise ValueError('그룹별 계산식에는 양쪽 집계의 group_by가 필요합니다.')
        if self.definition.operation == 'count' and self.unit != 'count':
            raise ValueError('행 건수의 단위는 count입니다.')
        return self


class GroupedFormulaMetricDefinition(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    version: Literal[4] = 4
    operation: Literal['difference', 'ratio', 'percent_change']
    left: GroupedFormulaOperand
    right: GroupedFormulaOperand
    as_percent: bool = True
    chart_type: Literal['bar', 'line'] = 'bar'
    dimension_label: str = Field(min_length=1, max_length=80)
    missing_group: Literal['undefined', 'zero'] = 'undefined'

    @model_validator(mode='after')
    def compatible_groups(self):
        if self.left.unit != self.right.unit:
            raise ValueError('두 집계의 단위가 같아야 합니다.')
        if self.operation != 'ratio' and not self.as_percent:
            raise ValueError('as_percent는 ratio에서만 변경할 수 있습니다.')
        left, right = self.left.definition, self.right.definition
        if left.date_grain != right.date_grain:
            raise ValueError('두 집계의 날짜 단위가 같아야 합니다.')
        if left.date_grain and left.time_range != right.time_range:
            raise ValueError('날짜별 계산식의 두 집계는 같은 기간이어야 합니다. 날짜를 이동해 다른 기간과 맞추는 비교는 아직 지원하지 않습니다.')
        if self.missing_group == 'zero' and any(d.operation not in ('sum', 'count') for d in [left, right]):
            raise ValueError('빈 그룹의 0 처리는 합계·건수 집계에서만 사용할 수 있습니다.')
        return self


class StoreMetricSource(MetricSource):
    currency_column: str | None = Field(default=None,min_length=1,max_length=200)


class StoreMetricSelection(BaseModel):
    model_config = ConfigDict(extra='forbid')
    project_id: UUID
    sources: list[StoreMetricSource] = Field(min_length=1, max_length=5)


class MultiStoreMetricDefinition(BaseModel):
    model_config = ConfigDict(extra='forbid')
    version: Literal[5] = 5
    operation: Literal['sum'] = 'sum'
    basis: Literal['net_payments'] = 'net_payments'
    date_basis: Literal['payment_refund_occurred_at'] = 'payment_refund_occurred_at'
    stores: list[StoreMetricSelection] = Field(min_length=2, max_length=10)
    group_by: Literal['none', 'store'] = 'store'
    chart_type: Literal['bar'] = 'bar'
    time_range: Literal['all', 'this_month', 'last_month', 'last_30_days'] = 'all'

    @model_validator(mode='after')
    def validate_selection(self):
        if len({s.project_id for s in self.stores}) != len(self.stores):
            raise ValueError('같은 가게를 두 번 선택할 수 없습니다.')
        sources = [source for store in self.stores for source in store.sources]
        if len(sources) > 20 or len({s.table_id for s in sources}) != len(sources):
            raise ValueError('전체 장부는 중복 없이 최대 20개를 선택할 수 있습니다.')
        for store in self.stores:
            if len({s.label for s in store.sources}) != len(store.sources):
                raise ValueError('한 가게 안의 장부 표시 이름은 서로 달라야 합니다.')
        if self.time_range != 'all' and any(not s.date_column for s in sources):
            raise ValueError('기간 비교에는 모든 장부의 결제·취소 발생일 컬럼이 필요합니다.')
        return self


DashboardMetricDefinition = MetricDefinition | MultiMetricDefinition | FormulaMetricDefinition | GroupedFormulaMetricDefinition | MultiStoreMetricDefinition
_definition_adapter = TypeAdapter(DashboardMetricDefinition)


def parse_metric_definition(value) -> DashboardMetricDefinition:
    return _definition_adapter.validate_python(value)
