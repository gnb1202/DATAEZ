from decimal import Decimal

from app.event_review import normalize, summarize, digest, event_key


def test_decimal_summary_preserves_extreme_integer_and_fraction_together():
    tiny = "0." + "0" * 999 + "1" * 1000
    huge = "1" + "0" * 1000
    rows = [{"classification": "new", "row_number": i + 2,
             "normalized": {"amount": amount}} for i, amount in enumerate([huge, tiny])]
    result = summarize(rows)
    assert result["amount"] == huge + "." + "0" * 999 + "1" * 1000


def test_equivalent_money_and_instants_normalize_without_rounding_or_id_changes():
    first = normalize(("001", "P01", "refund", Decimal("-20000.00"), "2026-09-01T00:00:00+09:00", "KRW"))
    second = normalize(("001", "P01", "refund", Decimal("-2e4"), "2026-08-31T15:00:00Z", "KRW"))
    assert digest(first) == digest(second)
    assert event_key(first) == ("refund", "001")
    assert digest(first) != digest({**second, "original_event_id": "P02"})
