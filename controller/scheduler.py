"""Scan scheduling and orchestration."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from enum import Enum
from typing import Dict, Iterable, List, Optional, Tuple

from arb_engine.calculations import (
    ArbitrageOpportunity,
    OutcomePrice,
    american_to_decimal,
    detect_arbitrage,
    select_best_prices,
)
from normalize.names import NameNormalizer
from persistence.database import Database

try:
    from odds_client.client import OddsApiClient, OddsResponse
except Exception as exc:  # pragma: no cover - defensive import guard
    raise RuntimeError("Failed to import OddsApiClient") from exc


class ScanMode(str, Enum):
    SNAPSHOT = "snapshot"
    CONTINUOUS = "continuous"
    BURST = "burst"


@dataclass
class ScanSchedule:
    interval_seconds: int
    burst_interval_seconds: int = 15
    burst_window_minutes: int = 10


@dataclass
class ScanConfig:
    sports: List[str]
    regions: List[str]
    bookmakers: List[str]
    markets: List[str]
    deep_markets: List[str]
    window_start: datetime
    window_end: datetime
    min_edge: Decimal
    bankroll: Decimal
    rounding: Decimal
    min_book_count: int = 2
    max_stake_per_book: Decimal | None = None
    scan_mode: ScanMode = ScanMode.SNAPSHOT
    schedule: ScanSchedule = field(default_factory=lambda: ScanSchedule(interval_seconds=60))


class ScanController:
    def __init__(
        self,
        client: OddsApiClient,
        database: Database,
        name_normalizer: Optional[NameNormalizer] = None,
    ) -> None:
        self._client = client
        self._db = database
        self._name_normalizer = name_normalizer or NameNormalizer()
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._config: Optional[ScanConfig] = None

    def run_snapshot(self, config: ScanConfig) -> None:
        self._config = config
        self._db.log("info", "Snapshot scan requested", {"mode": config.scan_mode.value})
        self._run_pass(config)

    def start(self, config: ScanConfig) -> None:
        if self._thread and self._thread.is_alive():
            raise RuntimeError("Scan already running")
        self._config = config
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_loop, name="arbisport-scanner", daemon=True)
        self._thread.start()
        self._db.log("info", "Continuous scanning started", {"mode": config.scan_mode.value})

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)
        self._thread = None
        self._db.log("info", "Scanning stopped")

    def _run_loop(self) -> None:
        assert self._config is not None
        config = self._config
        schedule = config.schedule
        while not self._stop_event.is_set():
            start_time = time.time()
            try:
                within_burst = self._run_pass(config)
            except Exception as exc:  # pragma: no cover - best effort logging
                self._db.log("error", "Scan pass failed", {"error": str(exc)})
                within_burst = False
            elapsed = time.time() - start_time
            if config.scan_mode == ScanMode.BURST and within_burst:
                interval = schedule.burst_interval_seconds
            else:
                interval = schedule.interval_seconds
            sleep_for = max(interval - elapsed, 0)
            if sleep_for:
                self._stop_event.wait(timeout=sleep_for)

    def _run_pass(self, config: ScanConfig) -> bool:
        now = _to_utc_naive(datetime.now(timezone.utc))
        window_start = _to_utc_naive(config.window_start)
        window_end = _to_utc_naive(config.window_end)
        burst_window = timedelta(minutes=config.schedule.burst_window_minutes)
        upcoming_within_burst = False
        total_events = 0
        total_opportunities = 0
        for sport in config.sports:
            try:
                response = self._client.get_odds(
                    sport_key=sport,
                    regions=config.regions,
                    bookmakers=config.bookmakers,
                    markets=config.markets,
                )
            except Exception as exc:
                self._db.log("error", "Odds fetch failed", {"sport": sport, "error": str(exc)})
                continue

            self._db.log_api_usage(response.remaining_requests, response.reset_time)
            (
                burst_flag,
                found,
                events,
                context,
            ) = self._process_sport_response(
                sport,
                response,
                config,
                now,
                window_start,
                window_end,
                burst_window,
            )
            context.update({"sport": sport})
            self._db.log("info", "Sport processed", context)
            if burst_flag:
                upcoming_within_burst = True
            total_opportunities += found
            total_events += events
        self._db.log(
            "info",
            "Scan pass completed",
            {
                "events_considered": total_events,
                "opportunities_found": total_opportunities,
                "sports": list(config.sports),
            },
        )
        return upcoming_within_burst

    def _process_sport_response(
        self,
        sport: str,
        response: OddsResponse,
        config: ScanConfig,
        now: datetime,
        window_start: datetime,
        window_end: datetime,
        burst_window: timedelta,
    ) -> Tuple[bool, int, int, Dict[str, int]]:
        upcoming_within_burst = False
        opportunities_found = 0
        events_considered = 0
        skipped_no_time = 0
        skipped_window = 0
        skipped_no_id = 0
        quotes_collected = 0
        markets_seen = 0
        events = response.data or []
        if isinstance(events, dict):
            events = [events]

        for event in events:
            if not isinstance(event, dict):
                continue
            commence_time = _parse_time(event.get("commence_time"))
            if not commence_time:
                skipped_no_time += 1
                continue
            commence_time = _to_utc_naive(commence_time)
            if commence_time < window_start or commence_time > window_end:
                skipped_window += 1
                continue
            events_considered += 1
            if commence_time - now <= burst_window:
                upcoming_within_burst = True

            event_id = event.get("id")
            if not event_id:
                skipped_no_id += 1
                continue

            self._db.record_event(event_id, sport, commence_time.isoformat(), event)
            market_quotes: Dict[str, List[OutcomePrice]] = {}

            quotes_collected += self._collect_market_quotes(
                event_id,
                event.get("bookmakers", []),
                market_quotes,
                config,
            )

            if config.deep_markets:
                deep_data = self._fetch_deep_markets(sport, event_id, config)
                if deep_data:
                    quotes_collected += self._collect_market_quotes(
                        event_id,
                        deep_data.get("bookmakers", []),
                        market_quotes,
                        config,
                    )

            for market_key, quotes in market_quotes.items():
                markets_seen += 1
                if len(quotes) < config.min_book_count:
                    continue
                best_prices = select_best_prices(quotes)
                opportunity = detect_arbitrage(
                    prices=best_prices,
                    min_edge=config.min_edge,
                    bankroll=config.bankroll,
                    rounding=config.rounding,
                    max_per_book=config.max_stake_per_book,
                )
                if opportunity:
                    self._handle_opportunity(event_id, market_key, opportunity)
                    opportunities_found += 1
        context = {
            "events_received": len(events),
            "events_in_window": events_considered,
            "skipped_no_time": skipped_no_time,
            "skipped_window": skipped_window,
            "skipped_no_id": skipped_no_id,
            "markets_evaluated": markets_seen,
            "quotes_collected": quotes_collected,
            "opportunities_found": opportunities_found,
        }
        return upcoming_within_burst, opportunities_found, events_considered, context

    def _handle_opportunity(self, event_id: str, market_key: str, opportunity: ArbitrageOpportunity) -> None:
        self._db.record_arbitrage(
            event_id=event_id,
            market_key=market_key,
            edge=float(opportunity.edge),
            total_stake=float(opportunity.total_stake),
            payout=float(opportunity.payout),
            stake_plan={k: float(v) for k, v in opportunity.stake_plan.items()},
        )
        self._db.log(
            "info",
            "Arbitrage opportunity detected",
            {
                "event_id": event_id,
                "market": market_key,
                "edge": float(opportunity.edge),
            },
        )

    def _collect_market_quotes(
        self,
        event_id: str,
        bookmakers: Iterable[dict],
        market_quotes: Dict[str, List[OutcomePrice]],
        config: ScanConfig,
    ) -> int:
        collected = 0
        for bookmaker in bookmakers:
            markets = bookmaker.get("markets", [])
            for market in markets:
                market_key = market.get("key")
                if market_key not in config.markets and market_key not in config.deep_markets:
                    continue
                quotes = market_quotes.setdefault(market_key, [])
                for outcome in market.get("outcomes", []):
                    name = outcome.get("name")
                    price = outcome.get("price")
                    if name is None or price is None:
                        continue
                    try:
                        american = int(price)
                        decimal_odds = american_to_decimal(american)
                    except Exception:
                        continue
                    canonical = self._name_normalizer.canonicalize(name)
                    point = outcome.get("point")
                    quotes.append(
                        OutcomePrice(
                            outcome_name=canonical,
                            bookmaker=bookmaker.get("title") or bookmaker.get("key", "unknown"),
                            american_odds=american,
                            decimal_odds=decimal_odds,
                            point=point,
                        )
                    )
                    collected += 1
                self._db.record_quotes(
                    event_id=event_id,
                    market_key=market_key,
                    bookmaker=bookmaker.get("key", "unknown"),
                    data=market,
                )
        return collected

    def _fetch_deep_markets(self, sport: str, event_id: str, config: ScanConfig) -> Optional[dict]:
        try:
            response = self._client.get_event_odds(
                sport_key=sport,
                event_id=event_id,
                regions=config.regions,
                bookmakers=config.bookmakers,
                markets=config.deep_markets,
            )
        except Exception as exc:
            self._db.log("warning", "Deep market fetch failed", {"event": event_id, "error": str(exc)})
            return None

        self._db.log_api_usage(response.remaining_requests, response.reset_time)
        if isinstance(response.data, dict):
            return response.data
        if isinstance(response.data, list) and response.data:
            return response.data[0]
        return None


def _parse_time(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        if value.endswith("Z"):
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _to_utc_naive(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)
