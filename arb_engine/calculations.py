"""Arbitrage detection and stake allocation helpers."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_DOWN
from typing import Dict, Iterable, List, Optional, Tuple


class OddsConversionError(ValueError):
    """Raised when an odds value cannot be converted."""


@dataclass
class OutcomePrice:
    """Represents the best price for a single outcome."""

    outcome_name: str
    bookmaker_key: str
    bookmaker_title: str
    american_odds: int
    decimal_odds: Decimal
    point: float | None = None
    bookmaker_regions: Tuple[str, ...] = ()
    bookmaker_url: str | None = None


@dataclass
class OutcomeRecommendation:
    """Instruction for staking on a specific outcome."""

    label: str
    bookmaker_key: str
    bookmaker_title: str
    bookmaker_regions: Tuple[str, ...]
    american_odds: int
    decimal_odds: Decimal
    stake: Decimal
    point: float | None = None
    url: str | None = None


@dataclass
class ArbitrageOpportunity:
    """Calculated arbitrage result."""

    edge: Decimal
    payout: Decimal
    total_stake: Decimal
    stake_plan: Dict[str, Decimal]
    recommendations: List[OutcomeRecommendation]


def american_to_decimal(american: int) -> Decimal:
    if american == 0:
        raise OddsConversionError("American odds cannot be zero")
    if american > 0:
        return Decimal(american) / Decimal(100) + Decimal(1)
    return Decimal(100) / Decimal(abs(american)) + Decimal(1)


def american_to_probability(american: int) -> Decimal:
    decimal_odds = american_to_decimal(american)
    return Decimal(1) / decimal_odds


def select_best_prices(quotes: Iterable[OutcomePrice]) -> Dict[str, OutcomePrice]:
    best: Dict[str, OutcomePrice] = {}
    for quote in quotes:
        key = _make_key(quote.outcome_name, quote.point)
        current = best.get(key)
        if current is None or quote.decimal_odds > current.decimal_odds:
            best[key] = quote
    return best


def _make_key(name: str, point: float | None) -> str:
    return f"{name}|{point}" if point is not None else name


def detect_arbitrage(
    prices: Dict[str, OutcomePrice],
    min_edge: Decimal,
    bankroll: Decimal,
    rounding: Decimal,
    max_per_book: Decimal | None = None,
) -> Optional[ArbitrageOpportunity]:
    if not prices:
        return None

    inverse_sum = sum((Decimal(1) / outcome.decimal_odds for outcome in prices.values()), start=Decimal(0))
    edge = Decimal(1) - inverse_sum
    if edge < min_edge:
        return None

    theoretical_payout = bankroll / inverse_sum
    stake_plan: Dict[str, Decimal] = {}
    total_stake = Decimal(0)
    payout_candidates: List[Tuple[str, Decimal, OutcomePrice]] = []

    recommendations: List[OutcomeRecommendation] = []

    for key, outcome in prices.items():
        raw_stake = theoretical_payout / outcome.decimal_odds
        if max_per_book is not None and raw_stake > max_per_book:
            return None

        rounded = (raw_stake / rounding).to_integral_value(rounding=ROUND_DOWN) * rounding
        if rounded <= 0:
            return None

        label = outcome.outcome_name if outcome.point is None else f"{outcome.outcome_name} ({outcome.point})"
        stake_plan[label] = rounded
        total_stake += rounded
        payout_candidates.append((label, rounded, outcome))
        recommendations.append(
            OutcomeRecommendation(
                label=label,
                bookmaker_key=outcome.bookmaker_key,
                bookmaker_title=outcome.bookmaker_title,
                bookmaker_regions=tuple(outcome.bookmaker_regions),
                american_odds=outcome.american_odds,
                decimal_odds=outcome.decimal_odds,
                stake=rounded,
                point=outcome.point,
                url=outcome.bookmaker_url,
            )
        )

    if total_stake == 0:
        return None

    actual_payout = min((stake * outcome.decimal_odds for _, stake, outcome in payout_candidates))
    if actual_payout <= total_stake:
        return None

    actual_edge = (actual_payout - total_stake) / total_stake
    if actual_edge < min_edge:
        return None

    return ArbitrageOpportunity(
        edge=actual_edge,
        payout=actual_payout,
        total_stake=total_stake,
        stake_plan=stake_plan,
        recommendations=recommendations,
    )
