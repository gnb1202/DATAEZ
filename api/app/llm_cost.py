"""Token pricing table and cost arithmetic for LLM calls.

Prices are USD per 1M tokens and are configuration, not constants: they
change whenever a vendor reprices. `LLM_PRICING` is the single place to
update, and `estimate_cost_usd` falls back to a zero-cost entry for
unknown models rather than guessing.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class ModelPrice:
    """USD per 1M tokens."""

    input_per_1m: float
    output_per_1m: float


# Keys are matched by longest prefix, so "gpt-5.4-nano-2026-01" resolves to
# the "gpt-5.4-nano" entry without needing a row per dated snapshot.
LLM_PRICING: dict[str, ModelPrice] = {
    "gpt-5.4-nano": ModelPrice(input_per_1m=0.05, output_per_1m=0.40),
    "gpt-5.4": ModelPrice(input_per_1m=1.25, output_per_1m=10.00),
    "gpt-4o-mini": ModelPrice(input_per_1m=0.15, output_per_1m=0.60),
    "gpt-4o": ModelPrice(input_per_1m=2.50, output_per_1m=10.00),
    "text-embedding-3-small": ModelPrice(input_per_1m=0.02, output_per_1m=0.0),
    "text-embedding-3-large": ModelPrice(input_per_1m=0.13, output_per_1m=0.0),
}

_UNKNOWN = ModelPrice(input_per_1m=0.0, output_per_1m=0.0)


def resolve_price(model: str) -> ModelPrice:
    """Return pricing for a model, matching the longest configured prefix."""
    if not model:
        return _UNKNOWN
    best: tuple[int, ModelPrice] | None = None
    for prefix, price in LLM_PRICING.items():
        if model.startswith(prefix) and (best is None or len(prefix) > best[0]):
            best = (len(prefix), price)
    return best[1] if best else _UNKNOWN


def estimate_cost_usd(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    """Cost in USD for one call. Unknown models cost 0 rather than a guess."""
    price = resolve_price(model)
    return (
        prompt_tokens * price.input_per_1m / 1_000_000
        + completion_tokens * price.output_per_1m / 1_000_000
    )


def is_priced(model: str) -> bool:
    """Whether this model has a pricing row — used to flag blind spots."""
    return resolve_price(model) is not _UNKNOWN
