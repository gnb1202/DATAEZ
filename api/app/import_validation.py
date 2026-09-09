"""Strict value validation shared by file import and source mapping."""
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from .exceptions import AppException


class ImportValidationError(AppException):
    def __init__(self, issues: list[dict]):
        self.issues = issues[:50]
        description = " · ".join(f"{i.get('row', 1)}행 {i.get('column', '')}: {i['message']}" for i in self.issues[:5])
        super().__init__(422, "import_validation_error", description)


def issue(row, column, message):
    return {"row": row, "column": column, "message": message}


def identifier_column(name: str) -> bool:
    return bool(re.search(r"(^id$|(^|[ _])id$|_id$|번호|아이디|식별자|코드)", name.lower().strip()))


def parse_decimal(value) -> Decimal:
    text = str(value).strip()
    if not re.fullmatch(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?", text):
        raise ValueError("숫자 형식을 확인해주세요. 쉼표·통화 기호는 지원하지 않습니다.")
    try:
        number = Decimal(text)
    except InvalidOperation:
        raise ValueError("숫자 형식을 확인해주세요.") from None
    if not number.is_finite() or abs(number.adjusted()) > 1000 or len(number.as_tuple().digits) > 1000:
        raise ValueError("지원 범위를 벗어난 숫자입니다.")
    return number


def numeric_dimensions(number: Decimal) -> tuple[int, int]:
    return (0 if number.is_zero() else max(number.adjusted() + 1, 0)), max(-number.as_tuple().exponent, 0)


def validate_type(pg_type: str) -> str:
    dtype = pg_type.upper().strip()
    if dtype in {"TEXT", "BIGINT", "INTEGER", "SMALLINT", "BOOLEAN", "DATE", "TIMESTAMP", "TIMESTAMPTZ", "NUMERIC"}:
        return dtype
    match = re.fullmatch(r"(?:NUMERIC|DECIMAL)\((\d+),\s*(\d+)\)", dtype)
    if match and 1 <= int(match[1]) <= 1000 and 0 <= int(match[2]) <= int(match[1]):
        return dtype
    raise ValueError(f"가져오기에서 지원하지 않는 컬럼 타입: {pg_type}")


def cast_value(value, pg_type: str):
    if value is None or value == "":
        return None
    dtype = validate_type(pg_type)
    if dtype == "TEXT":
        text = str(value)
        if "\x00" in text:
            raise ValueError("널 문자는 저장할 수 없습니다.")
        return text
    if dtype in {"BIGINT", "INTEGER", "SMALLINT"}:
        number = parse_decimal(value)
        if number != number.to_integral_value():
            raise ValueError("정수 컬럼에 소수를 저장할 수 없습니다.")
        integer = int(number)
        bits = {"BIGINT": 64, "INTEGER": 32, "SMALLINT": 16}[dtype]
        if not -(2 ** (bits - 1)) <= integer < 2 ** (bits - 1):
            raise ValueError("정수 컬럼의 저장 범위를 초과했습니다.")
        return integer
    if dtype.startswith(("NUMERIC", "DECIMAL")):
        number = parse_decimal(value)
        if "(" in dtype:
            precision, scale = map(int, re.findall(r"\d+", dtype))
            integers, _ = numeric_dimensions(number)
            # normalize() could round under the default Decimal context.
            fraction = format(number, "f").partition(".")[2].rstrip("0")
            if integers > precision - scale or len(fraction) > scale:
                raise ValueError(f"{dtype}에 손실 없이 저장할 수 없습니다. 컬럼 범위를 확인해주세요.")
        return number
    if dtype == "BOOLEAN":
        text = str(value).strip().lower()
        if text in {"true", "1"}:
            return True
        if text in {"false", "0"}:
            return False
        raise ValueError("참/거짓은 true/false 또는 1/0으로 입력해주세요.")
    text = str(value).strip()
    if not re.match(r"^\d{4}-\d{2}-\d{2}(?:$|[T ])", text):
        raise ValueError("날짜는 YYYY-MM-DD, 일시는 ISO 형식으로 입력해주세요.")
    try:
        if dtype == "DATE":
            if isinstance(value, datetime):
                if value.time().isoformat() != "00:00:00" or value.tzinfo:
                    raise ValueError()
                return value.date().isoformat()
            return date.fromisoformat(text).isoformat()
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if dtype == "TIMESTAMP" and parsed.tzinfo is not None:
            raise ValueError("시간대가 있는 값은 TIMESTAMPTZ 컬럼을 사용해주세요.")
        if dtype == "TIMESTAMPTZ" and parsed.tzinfo is None:
            raise ValueError("시간대가 포함된 일시가 필요합니다.")
        return parsed.isoformat()
    except ValueError as exc:
        raise ValueError(str(exc) if "컬럼" in str(exc) or "필요" in str(exc) else "유효한 날짜·일시인지 확인해주세요.") from None
