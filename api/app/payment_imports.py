"""Explicit payment-event mapping for the source/batch service.

Generic table uploads keep their columns. This adapter is deliberately explicit:
it must never infer a payment ledger from a settlement or reservation file.
"""
from datetime import datetime
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field

from .data_import import PreparedImport, _load_dataframe
from .import_validation import ImportValidationError, cast_value, issue, parse_decimal


class PaymentImportMapping(BaseModel):
    model_config = ConfigDict(extra="forbid")
    amount_column: str = Field(min_length=1, max_length=200)
    occurred_at_column: str = Field(min_length=1, max_length=200)
    event_id_column: str | None = Field(default=None, min_length=1, max_length=200)
    original_event_id_column: str | None = Field(default=None, min_length=1, max_length=200)
    currency_column: str | None = Field(default=None, min_length=1, max_length=200)
    payment_method_column: str | None = Field(default=None, min_length=1, max_length=200)
    channel_column: str | None = Field(default=None, min_length=1, max_length=200)
    fee_column: str | None = Field(default=None, min_length=1, max_length=200)
    currency: Literal["KRW"] = "KRW"
    timezone: Literal["Asia/Seoul"] = "Asia/Seoul"
    event_kind: Literal["payment", "refund", "signed"] = "payment"


ATTRIBUTE_TYPES = {"payment_method": "TEXT", "channel": "TEXT", "fee": "NUMERIC"}


def payment_schema(mapping: PaymentImportMapping | None = None):
    schema = [{"name": name, "type": dtype, "nullable": nullable} for name, dtype, nullable in [
        ("event_id", "TEXT", True), ("original_event_id", "TEXT", True), ("event_kind", "TEXT", False),
        ("amount", "NUMERIC", False), ("occurred_at", "TIMESTAMPTZ", False), ("currency", "TEXT", False),
    ]]
    # Old source profiles retain their exact six-column shape. Only explicitly
    # mapped attributes become queryable columns; absent data is never invented.
    if mapping:
        schema.extend({"name": name, "type": dtype, "nullable": True}
                      for name, dtype in ATTRIBUTE_TYPES.items() if getattr(mapping, name + "_column"))
    return schema


def prepare_payment_import(content: bytes, filename: str, mapping: PaymentImportMapping, *, selected_rows: set[int] | None = None) -> PreparedImport:
    frame = _load_dataframe(content, filename)
    if selected_rows is not None:
        # Restoration reads only the exact originally accepted rows. Excluded
        # candidates must never supply attributes for another physical event.
        locations = frame.attrs["row_numbers"]
        indices = [i for i, number in enumerate(locations) if number in selected_rows]
        if {locations[i] for i in indices} != selected_rows:
            raise ImportValidationError([issue(1, "", "최초 반영 원본 행을 찾을 수 없습니다.")])
        numeric = frame.attrs.get("numeric_cells", set())
        frame = frame.iloc[indices].copy()
        frame.attrs["row_numbers"] = [locations[i] for i in indices]
        frame.attrs["numeric_cells"] = {(new, col) for new, old in enumerate(indices)
                                        for col in range(len(frame.columns)) if (old, col) in numeric}
    return _prepare_payment_frame(frame, mapping)


def prepare_payment_values(columns, rows, row_numbers, mapping):
    """Map already validated physical rows without a float/CSV round trip."""
    from decimal import Decimal
    import pandas as pd
    frame = pd.DataFrame(rows, columns=columns, dtype=object)
    frame.attrs["row_numbers"] = row_numbers
    frame.attrs["numeric_cells"] = {(i, j) for i, row in enumerate(rows) for j, value in enumerate(row)
                                    if isinstance(value, (int, float, Decimal))}
    return _prepare_payment_frame(frame, mapping)


def _prepare_payment_frame(frame, mapping):
    selected = {role: name for role, name in mapping.model_dump().items() if role.endswith("_column") and name is not None}
    if len(set(selected.values())) != len(selected):
        raise ImportValidationError([issue(1, "", "서로 다른 필드에 같은 컬럼을 연결할 수 없습니다.")])
    indices = {}
    for role, name in selected.items():
        matches = [i for i, c in enumerate(frame.columns) if c == name]
        if len(matches) != 1:
            raise ImportValidationError([issue(1, name, "정확히 하나의 원본 컬럼을 선택해주세요.")])
        indices[role] = matches[0]
    schema = payment_schema(mapping)
    rows, problems = [], []
    locations = frame.attrs["row_numbers"]
    for row_index, values in enumerate(frame.itertuples(index=False, name=None)):
        converted = {}
        for role, index in indices.items():
            raw = values[index]
            try:
                if role in {"original_event_id_column", *(name + "_column" for name in ATTRIBUTE_TYPES)} and (raw is None or str(raw).strip() == ""):
                    converted[role] = None
                    continue
                if raw is None or str(raw).strip() == "":
                    raise ValueError("연결된 필드의 값이 비어 있습니다.")
                if role in {"event_id_column", "original_event_id_column"}:
                    if (row_index, index) in frame.attrs.get("numeric_cells", set()):
                        raise ValueError("ID는 원본에서 텍스트로 제공해주세요.")
                    converted[role] = cast_value(raw, "TEXT")
                elif role == "amount_column":
                    amount = parse_decimal(raw)
                    if mapping.event_kind == "payment" and amount < 0:
                        raise ValueError("음수 금액은 취소 또는 부호 유지 방식으로 연결해주세요.")
                    converted[role] = amount.copy_abs().copy_negate() if mapping.event_kind == "refund" else amount
                elif role == "currency_column":
                    if str(raw).strip() != mapping.currency:
                        raise ValueError("원화(KRW) 거래만 지원합니다.")
                    converted[role] = mapping.currency
                elif role in {"payment_method_column", "channel_column"}:
                    converted[role] = cast_value(raw, "TEXT")
                elif role == "fee_column":
                    # Fee reversal policies vary by provider. Preserve the
                    # signed original fee independently of the payment amount.
                    converted[role] = parse_decimal(raw)
                else:
                    text = str(raw).strip()
                    # Reuse strict ISO validation before assigning local zone.
                    dtype = "TIMESTAMPTZ" if text.endswith("Z") or (len(text) > 10 and ("+" in text[10:] or "-" in text[10:])) else "TIMESTAMP"
                    parsed = datetime.fromisoformat(cast_value(text, dtype))
                    converted[role] = parsed.replace(tzinfo=ZoneInfo(mapping.timezone)).isoformat() if parsed.tzinfo is None else parsed.isoformat()
            except ValueError as exc:
                problems.append(issue(locations[row_index], selected[role], str(exc)))
        if all(role in converted for role in indices):
            amount = converted["amount_column"]
            kind = ("refund" if amount < 0 else "payment") if mapping.event_kind == "signed" else mapping.event_kind
            rows.append((converted.get("event_id_column"), converted.get("original_event_id_column"), kind,
                         amount, converted["occurred_at_column"], mapping.currency,
                         *(converted[name + "_column"] for name in ATTRIBUTE_TYPES if name + "_column" in indices)))
        if len(problems) >= 50:
            break
    if problems:
        raise ImportValidationError(problems)
    return PreparedImport(schema, rows, locations)
