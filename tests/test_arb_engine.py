from decimal import Decimal

from arb_engine.calculations import (
    OutcomePrice,
    american_to_decimal,
    detect_arbitrage,
    select_best_prices,
)


def test_american_to_decimal_positive():
    assert american_to_decimal(110) == Decimal("2.1")


def test_detect_arbitrage_identifies_opportunity():
    prices = select_best_prices(
        [
            OutcomePrice("Team A", "book1", -110, american_to_decimal(-110)),
            OutcomePrice("Team B", "book2", 120, american_to_decimal(120)),
        ]
    )
    opportunity = detect_arbitrage(prices, min_edge=Decimal("0.001"), bankroll=Decimal("100"), rounding=Decimal("0.01"))
    assert opportunity is not None
    assert opportunity.edge > 0


def test_detect_arbitrage_honors_max_per_book_filter():
    prices = select_best_prices(
        [
            OutcomePrice("Team A", "book1", -110, american_to_decimal(-110)),
            OutcomePrice("Team B", "book2", 120, american_to_decimal(120)),
        ]
    )
    opportunity = detect_arbitrage(
        prices,
        min_edge=Decimal("0.001"),
        bankroll=Decimal("100"),
        rounding=Decimal("0.01"),
        max_per_book=Decimal("10"),
    )
    assert opportunity is None


def test_detect_arbitrage_uses_actual_payout_after_rounding():
    prices = select_best_prices(
        [
            OutcomePrice("Team A", "book1", -101, american_to_decimal(-101)),
            OutcomePrice("Team B", "book2", 102, american_to_decimal(102)),
        ]
    )
    opportunity = detect_arbitrage(
        prices,
        min_edge=Decimal("0.0001"),
        bankroll=Decimal("200"),
        rounding=Decimal("0.10"),
    )
    assert opportunity is not None
    label_map = {}
    for outcome in prices.values():
        label = outcome.outcome_name if outcome.point is None else f"{outcome.outcome_name} ({outcome.point})"
        label_map[label] = outcome

    min_return = min(
        stake * label_map[label].decimal_odds for label, stake in opportunity.stake_plan.items()
    )
    assert opportunity.payout == min_return
    assert opportunity.edge == (opportunity.payout - opportunity.total_stake) / opportunity.total_stake
