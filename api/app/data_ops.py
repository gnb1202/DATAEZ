from typing import Any


def build_chart_data(
    chart_type: str, title: str, x_column: str, y_column: str, data: list[dict[str, Any]]
) -> dict[str, Any] | None:
    """Return Recharts-compatible chart data (raw data + metadata)."""
    if not data or not x_column or not y_column:
        return None
    return {
        "chart_type": chart_type,
        "title": title,
        "x_key": x_column,
        "y_key": y_column,
        "data": data,
    }
