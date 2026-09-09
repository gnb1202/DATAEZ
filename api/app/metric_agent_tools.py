"""Metric tools share the same validated service as the dashboard form."""

from copy import deepcopy

from .metric_definitions import MetricDefinition, MetricSource, FormulaOperand, StoreMetricSelection


def _inline_schema(node, definitions):
    if isinstance(node, list):
        return [_inline_schema(item, definitions) for item in node]
    if isinstance(node, dict):
        if "$ref" in node:
            return _inline_schema(definitions[node["$ref"].split("/")[-1]], definitions)
        return {key: _inline_schema(value, definitions) for key, value in node.items() if key != "$defs"}
    return node


def _definition_properties():
    schema = MetricDefinition.model_json_schema()
    properties = deepcopy(schema["properties"])
    properties.pop("table_id")
    properties["table_name"] = {"type": "string", "description": "현재 가게에서 확인한 정확한 장부 이름. 추측 금지."}
    properties["filters"]["items"] = schema["$defs"]["MetricFilter"]
    source_schema = MetricSource.model_json_schema()
    source = _inline_schema(source_schema, source_schema.get("$defs", {}))
    source["properties"].pop("table_id")
    source["properties"]["table_name"] = properties["table_name"]
    source["required"] = ["table_name", "label", "column"]
    properties["sources"] = {"type": "array", "minItems": 2, "maxItems": 5, "items": source,
        "description": "같은 가게의 독립된 원화 결제 이벤트 장부 2~5개. 지정하면 version=2, operation=sum만 지원. table_name/column 등 최상위 단일 장부 필드는 함께 보내지 마세요. 취소 장부는 amount_mode=refund."}
    operand_schema = FormulaOperand.model_json_schema()
    operand = _inline_schema(operand_schema, operand_schema.get("$defs", {}))
    single = operand["properties"]["definition"]
    single["properties"].pop("table_id")
    single["properties"]["table_name"] = properties["table_name"]
    single["required"] = ["table_name"]
    properties["left"] = deepcopy(operand)
    properties["right"] = deepcopy(operand)
    properties["as_percent"] = {"type":"boolean", "description":"v3/v4 ratio를 백분율로 표시할지 여부. 기본 true."}
    properties["dimension_label"] = {"type":"string", "description":"v4 필수: 그룹 축 이름(주, 월, 판매채널 등). 양쪽 definition.group_by가 필요하며 날짜는 같은 date_grain·time_range를 사용합니다."}
    properties["missing_group"] = {"type":"string", "enum":["undefined","zero"], "description":"v4만 사용. 기본 undefined: 한쪽에 거래가 없는 그룹은 계산 불가. 사용자가 빈 그룹을 0으로 요청한 경우에만 zero(양쪽 sum/count만). 숫자 NULL과 분모 0은 0으로 바꾸지 않습니다."}
    properties["operation"]["enum"] += ["difference", "ratio", "percent_change"]
    properties["version"] = {"type": "integer", "enum": [1, 2, 3, 4], "description":"1 단일 장부, 2 여러 장부 합계, 3 두 스칼라 집계의 차이·비율·증감률, 4 날짜별·분류별 계산식 차트. v3/v4는 left/right/operation/as_percent 및 v4 전용 dimension_label/chart_type/missing_group을 사용하며 최상위 table_name·filters·time_range 등 v1 필드를 섞지 않습니다."}
    properties["group_by"]["description"] = "단일 장부: 컬럼 이름. sources 통합 지표: none(합계), date(날짜별), source(장부별)."
    stores_schema = StoreMetricSelection.model_json_schema()
    properties['stores'] = {'type':'array','minItems':2,'maxItems':10,'items':_inline_schema(stores_schema,stores_schema.get('$defs',{})),
        'description':'v5 전용: 사용자가 선택한 가게 project_id와 각 가게의 sources(1~5개, 전체 최대20개). list_stores/list_store_tables/inspect_store_table로 확인한 UUID만 사용. 원화 결제·취소 발생 이벤트 기준.'}
    properties['version']['enum'].append(5)
    properties['version']['description'] += ' 5 여러 가게의 순결제액: stores, operation=sum, group_by=none/store, time_range, chart_type=bar만 사용. 기존 sources/table_name/left/right 등 최상위 필드는 섞지 마세요.'
    properties['group_by']['description'] += ' 여러 가게 v5: none(전체 합계) 또는 store(가게별 막대).'
    return properties


def _tool(name, description, properties, required):
    return {"type": "function", "function": {
        "name": name, "description": description,
        "parameters": {"type": "object", "properties": properties, "required": required, "additionalProperties": False},
    }}


METRIC_TOOL_SPECS = [
    _tool("preview_metric", "저장할 수 있는 지표를 계산해 미리 보여줍니다. 단일 장부 집계 또는 sources로 여러 장부의 원화 결제액을 통합합니다. 각 출처를 search_schema/list_tables/describe_table로 먼저 확인하세요.",
          {**_definition_properties(), "title": {"type":"string", "minLength":1, "maxLength":120, "description":"출처와 계산 기준을 담은 지표 이름"}}, ["operation"]),
    _tool("save_metric", "사용자가 대시보드 저장/추가를 요청한 지표를 저장하고 계산합니다. 미리보기와 동일한 정의를 전달하세요. refresh_interval_seconds: 수동 0, 매시간 3600, 매일 86400. 원본 거래는 변경하지 않습니다.",
          {**_definition_properties(), "title": {"type": "string", "minLength": 1, "maxLength": 120},
           "refresh_interval_seconds": {"type": "integer", "enum": [0, 3600, 86400]}}, ["operation", "title"]),
    _tool("list_metrics", "현재 가게의 저장된 지표 ID·정의·갱신 주기를 조회합니다. '그 지표'의 주기를 바꾸기 전에 대상을 확인하세요.", {}, []),
    _tool("set_metric_refresh", "확인된 저장 지표의 자동 갱신 주기를 설정하거나 중지합니다. 0은 자동 갱신 중지, 3600은 매시간, 86400은 매일입니다.",
          {"metric_id": {"type": "string", "format": "uuid"}, "refresh_interval_seconds": {"type": "integer", "enum": [0, 3600, 86400]}},
          ["metric_id", "refresh_interval_seconds"]),
]

METRIC_TOOL_SPECS.extend([
    _tool('list_stores','여러 가게 분석에 사용할 본인 소유 가게 목록. 사용자가 지정한 이름을 확인하고 동명이면 구분을 질문하세요. 다음 페이지는 next_offset 사용.',{'offset':{'type':'integer','minimum':0}},[]),
    _tool('list_store_tables','사용자가 선택한 가게의 장부 목록. project_id는 list_stores에서 확인하세요. 다음 페이지는 next_offset 사용.',{'project_id':{'type':'string','format':'uuid'},'offset':{'type':'integer','minimum':0}},['project_id']),
    _tool('inspect_store_table','선택한 가게 장부의 실제 컬럼, 일부 샘플, 관리 출처 매핑을 확인합니다. 샘플만으로 합계를 계산하지 마세요.',{'project_id':{'type':'string','format':'uuid'},'table_id':{'type':'string','format':'uuid'}},['project_id','table_id']),
    _tool('search_store_schema','선택한 본인 가게 범위에서 파일/장부/컬럼을 RAG 검색합니다. 검색 장애나 미완성 색인은 자료 없음이 아닙니다.',{'project_id':{'type':'string','format':'uuid'},'query':{'type':'string','minLength':1}},['project_id','query']),
    _tool("update_metric", "사용자가 요청한 저장 지표의 제목·정의를 변경하고 재계산합니다. list_metrics로 ID와 definition_revision을 먼저 확인하고 전체 정의를 전달하세요. ID·배치·주기를 유지합니다. 미리보기만 요청한 경우 사용하지 마세요.",
          {**_definition_properties(), "metric_id":{"type":"string","format":"uuid"}, "expected_revision":{"type":"integer","minimum":1}, "title":{"type":"string","minLength":1,"maxLength":120}},
          ["metric_id","expected_revision","title","operation"]),
    _tool("get_metric_history", "현재 가게 지표의 변경 이력과 최신 정의를 확인합니다.",
          {"metric_id":{"type":"string","format":"uuid"},"offset":{"type":"integer","minimum":0,"description":"next_offset이 있으면 다음 이력 페이지 조회"}}, ["metric_id"]),
    _tool("restore_metric", "사용자가 되돌리기를 요청한 지표를 확인된 과거 정의로 복원하여 새 변경 이력으로 저장합니다. 현재 데이터로 다시 계산하며 과거 수치를 복사하지 않습니다.",
          {"metric_id":{"type":"string","format":"uuid"},"revision":{"type":"integer","minimum":1},"expected_revision":{"type":"integer","minimum":1}},
          ["metric_id","revision","expected_revision"]),
])
