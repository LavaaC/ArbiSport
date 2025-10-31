"""Market normalization helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Tuple


@dataclass(frozen=True)
class OutcomeKey:
    """Canonical identifier for an outcome."""

    name: str
    points: float | None = None


@dataclass
class NormalizedMarket:
    """Normalized market representation used by the arbitrage engine."""

    market_key: str
    outcome_order: List[OutcomeKey]


class MarketNormalizer:
    """Ensures outcome ordering is stable across bookmakers."""

    def __init__(self) -> None:
        self._known_orders: Dict[str, List[OutcomeKey]] = {}

    def register(self, market_key: str, outcomes: Iterable[OutcomeKey]) -> None:
        self._known_orders[market_key] = list(outcomes)

    def normalize(self, market_key: str, raw_outcomes: Iterable[dict]) -> NormalizedMarket:
        normalized = []
        order = self._known_orders.get(market_key)
        if order:
            order_lookup = {o.name.casefold(): o for o in order}
        else:
            order_lookup = {}

        for outcome in raw_outcomes:
            name = outcome.get("name", "").strip()
            points = outcome.get("point")
            key = name.casefold()
            if key in order_lookup:
                normalized.append(order_lookup[key])
            else:
                normalized.append(OutcomeKey(name=name, points=points))

        if not order:
            self._known_orders[market_key] = normalized

        return NormalizedMarket(market_key, normalized)
