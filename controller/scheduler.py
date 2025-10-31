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
from odds_client.catalog import get_bookmaker_info
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
class RescanResult:
    """Outcome from a manual opportunity rescan."""

    event_id: str
    sport_key: str
    market_key: str
    event_name: str
    commence_time: Optional[datetime]
    within_window: bool
    quotes_considered: int
    opportunity: Optional[ArbitrageOpportunity]
    status: str


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
    deep_market_map: Dict[str, List[str]] = field(default_factory=dict)
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
        self._market_catalog: Dict[str, set[str]] = {}
        self._invalid_deep_markets: Dict[str, set[str]] = {}

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

    def rescan_opportunity(
        self,
        config: ScanConfig,
        event_id: str,
        sport_key: str,
        market_key: str,
    ) -> RescanResult:
        """Re-evaluate a previously detected opportunity."""

        window_start = _to_utc_naive(config.window_start)
        window_end = _to_utc_naive(config.window_end)
        try:
            response = self._client.get_odds(
                sport_key=sport_key,
                regions=config.regions,
                bookmakers=config.bookmakers,
                markets=config.markets,
            )
        except Exception as exc:
            self._db.log(
                "error",
                "Rescan odds fetch failed",
                {"event_id": event_id, "sport": sport_key, "error": str(exc)},
            )
            raise

        self._db.log_api_usage(response.remaining_requests, response.reset_time)
        events = response.data or []
        if isinstance(events, dict):
            events = [events]

        target_event: Optional[dict] = None
        for event in events:
            if isinstance(event, dict) and event.get("id") == event_id:
                target_event = event
                break

        if not target_event:
            self._db.log(
                "info",
                "Rescan event not returned",
                {"event_id": event_id, "sport": sport_key},
            )
            return RescanResult(
                event_id=event_id,
                sport_key=sport_key,
                market_key=market_key,
                event_name=event_id,
                commence_time=None,
                within_window=False,
                quotes_considered=0,
                opportunity=None,
                status="event_not_found",
            )

        commence_time_raw = _parse_time(target_event.get("commence_time"))
        commence_time = _to_utc_naive(commence_time_raw) if commence_time_raw else None
        within_window = True
        if commence_time:
            within_window = window_start <= commence_time <= window_end

        if commence_time:
            commence_str = commence_time.isoformat()
        else:
            commence_str = target_event.get("commence_time") or ""

        self._db.record_event(event_id, sport_key, commence_str, target_event)

        allowed_deep = set(config.deep_markets)
        allowed_deep.update(config.deep_market_map.get(sport_key, []))
        if market_key not in config.markets:
            allowed_deep.add(market_key)
        allowed_deep = set(self._filter_supported_deep_markets(sport_key, allowed_deep))

        market_quotes: Dict[str, List[OutcomePrice]] = {}
        quotes_collected = self._collect_market_quotes(
            event_id,
            target_event.get("bookmakers", []),
            market_quotes,
            config,
            allowed_deep,
        )

        deep_keys = list(sorted(self._filter_supported_deep_markets(sport_key, allowed_deep)))
        if deep_keys:
            deep_data = self._fetch_deep_markets(sport_key, event_id, config, deep_keys)
            if deep_data:
                quotes_collected += self._collect_market_quotes(
                    event_id,
                    deep_data.get("bookmakers", []),
                    market_quotes,
                    config,
                    allowed_deep,
                )

        event_name = _event_title(target_event)
        quotes = market_quotes.get(market_key, [])
        if not quotes:
            self._db.log(
                "info",
                "Rescan market unavailable",
                {
                    "event_id": event_id,
                    "sport": sport_key,
                    "market": market_key,
                    "quotes_collected": quotes_collected,
                },
            )
            return RescanResult(
                event_id=event_id,
                sport_key=sport_key,
                market_key=market_key,
                event_name=event_name,
                commence_time=commence_time,
                within_window=within_window,
                quotes_considered=0,
                opportunity=None,
                status="no_quotes",
            )

        best_prices = select_best_prices(quotes)
        opportunity = detect_arbitrage(
            prices=best_prices,
            min_edge=config.min_edge,
            bankroll=config.bankroll,
            rounding=config.rounding,
            max_per_book=config.max_stake_per_book,
        )

        if opportunity:
            self._db.log(
                "info",
                "Rescan opportunity confirmed",
                {
                    "event_id": event_id,
                    "sport": sport_key,
                    "market": market_key,
                    "edge": float(opportunity.edge),
                },
            )
            return RescanResult(
                event_id=event_id,
                sport_key=sport_key,
                market_key=market_key,
                event_name=event_name,
                commence_time=commence_time,
                within_window=within_window,
                quotes_considered=len(quotes),
                opportunity=opportunity,
                status="arbitrage",
            )

        self._db.log(
            "info",
            "Rescan found no arbitrage",
            {
                "event_id": event_id,
                "sport": sport_key,
                "market": market_key,
                "quotes": len(quotes),
            },
        )
        return RescanResult(
            event_id=event_id,
            sport_key=sport_key,
            market_key=market_key,
            event_name=event_name,
            commence_time=commence_time,
            within_window=within_window,
            quotes_considered=len(quotes),
            opportunity=None,
            status="no_arbitrage",
        )

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

        allowed_deep_markets = set(config.deep_markets)
        allowed_deep_markets.update(config.deep_market_map.get(sport, []))

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
                allowed_deep_markets,
            )

            deep_market_keys = self._determine_deep_markets(sport, config)
            deep_data: Optional[dict] = None
            if deep_market_keys:
                deep_data = self._fetch_deep_markets(sport, event_id, config, deep_market_keys)
            if deep_data:
                quotes_collected += self._collect_market_quotes(
                    event_id,
                    deep_data.get("bookmakers", []),
                    market_quotes,
                    config,
                    allowed_deep_markets,
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
                    event_name = _event_title(event)
                    commence = _parse_time(event.get("commence_time"))
                    self._handle_opportunity(
                        event_id,
                        event_name,
                        sport,
                        commence,
                        market_key,
                        opportunity,
                    )
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

    def _handle_opportunity(
        self,
        event_id: str,
        event_name: str,
        sport_key: str,
        commence_time: Optional[datetime],
        market_key: str,
        opportunity: ArbitrageOpportunity,
    ) -> None:
        details = [
            {
                "label": rec.label,
                "bookmaker_key": rec.bookmaker_key,
                "bookmaker_title": rec.bookmaker_title,
                "regions": list(rec.bookmaker_regions),
                "american_odds": rec.american_odds,
                "decimal_odds": float(rec.decimal_odds),
                "stake": float(rec.stake),
                "point": rec.point,
                "url": rec.url,
            }
            for rec in opportunity.recommendations
        ]
        self._db.record_arbitrage(
            event_id=event_id,
            event_name=event_name,
            sport_key=sport_key,
            commence_time=commence_time,
            market_key=market_key,
            edge=float(opportunity.edge),
            total_stake=float(opportunity.total_stake),
            payout=float(opportunity.payout),
            stake_plan={k: float(v) for k, v in opportunity.stake_plan.items()},
            details=details,
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

    def _determine_deep_markets(self, sport: str, config: ScanConfig) -> List[str]:
        if sport in config.deep_market_map:
            requested = config.deep_market_map[sport]
        else:
            requested = config.deep_markets
        return self._filter_supported_deep_markets(sport, requested)

    def _filter_supported_deep_markets(self, sport: str, markets: Iterable[str]) -> List[str]:
        requested = [market for market in dict.fromkeys(markets) if market]
        if not requested:
            return []

        unavailable = self._invalid_deep_markets.get(sport, set())
        filtered = [market for market in requested if market not in unavailable]
        if not filtered:
            return []

        available = self._market_catalog.get(sport)
        if available is None:
            available = self._load_market_catalog(sport)
        if available:
            filtered = [market for market in filtered if market in available]
        return filtered

    def _collect_market_quotes(
        self,
        event_id: str,
        bookmakers: Iterable[dict],
        market_quotes: Dict[str, List[OutcomePrice]],
        config: ScanConfig,
        allowed_deep_markets: Iterable[str],
    ) -> int:
        collected = 0
        deep_market_set = {market for market in allowed_deep_markets}
        for bookmaker in bookmakers:
            markets = bookmaker.get("markets", [])
            for market in markets:
                market_key = market.get("key")
                if market_key not in config.markets and market_key not in deep_market_set:
                    continue
                quotes = market_quotes.setdefault(market_key, [])
                book_key = bookmaker.get("key", "unknown")
                book_title = bookmaker.get("title") or book_key
                info = get_bookmaker_info(book_key)
                regions = tuple(info.regions) if info else ()
                url = info.url if info else None
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
                            bookmaker_key=book_key,
                            bookmaker_title=book_title,
                            american_odds=american,
                            decimal_odds=decimal_odds,
                            point=point,
                            bookmaker_regions=regions,
                            bookmaker_url=url,
                        )
                    )
                    collected += 1
                self._db.record_quotes(
                    event_id=event_id,
                    market_key=market_key,
                    bookmaker=book_key,
                    data=market,
                )
        return collected

    def _fetch_deep_markets(
        self,
        sport: str,
        event_id: str,
        config: ScanConfig,
        markets: List[str],
    ) -> Optional[dict]:
        supported = self._filter_supported_deep_markets(sport, markets)
        if not supported:
            return None

        try:
            response = self._client.get_event_odds(
                sport_key=sport,
                event_id=event_id,
                regions=config.regions,
                bookmakers=config.bookmakers,
                markets=supported,
            )
        except Exception as exc:
            self._db.log(
                "warning",
                "Deep market fetch failed",
                {"event": event_id, "sport": sport, "markets": supported, "error": str(exc)},
            )
            self._mark_deep_market_unavailable(sport, supported)
            return None

        self._db.log_api_usage(response.remaining_requests, response.reset_time)
        payload: Optional[dict] = None
        if isinstance(response.data, dict):
            payload = response.data
        elif isinstance(response.data, list) and response.data:
            entry = response.data[0]
            if isinstance(entry, dict):
                payload = entry

        if not payload:
            return None

        returned_markets = {
            market.get("key")
            for bookmaker in payload.get("bookmakers", [])
            if isinstance(bookmaker, dict)
            for market in bookmaker.get("markets", [])
            if isinstance(market, dict)
        }
        missing = [market for market in supported if market not in returned_markets]
        if missing:
            self._mark_deep_market_unavailable(sport, missing)

        return payload

    def _load_market_catalog(self, sport: str) -> set[str]:
        try:
            response = self._client.list_markets(sport)
        except Exception as exc:
            self._db.log("warning", "Market list fetch failed", {"sport": sport, "error": str(exc)})
            markets: set[str] = set()
        else:
            self._db.log_api_usage(response.remaining_requests, response.reset_time)
            markets = set(_extract_market_keys(response.data))
        self._market_catalog[sport] = markets
        return markets

    def _mark_deep_market_unavailable(self, sport: str, markets: Iterable[str]) -> None:
        unavailable = self._invalid_deep_markets.setdefault(sport, set())
        for market in markets:
            if market:
                unavailable.add(market)


def _extract_market_keys(payload: object) -> List[str]:
    if isinstance(payload, list):
        results: List[str] = []
        for entry in payload:
            if isinstance(entry, dict):
                value = entry.get("key") or entry.get("name")
                if isinstance(value, str):
                    results.append(value)
            elif isinstance(entry, str):
                results.append(entry)
        return results
    if isinstance(payload, dict):
        results: List[str] = []
        value = payload.get("key") or payload.get("name")
        if isinstance(value, str):
            results.append(value)
        return results
    return []


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


def _event_title(event: dict) -> str:
    """Best-effort human readable name for an event."""

    home = event.get("home_team") if isinstance(event, dict) else None
    away = event.get("away_team") if isinstance(event, dict) else None
    if home and away:
        return f"{away} @ {home}"
    name = event.get("sport_title") if isinstance(event, dict) else None
    if name:
        return name
    return event.get("id", "Unknown event") if isinstance(event, dict) else "Unknown event"
