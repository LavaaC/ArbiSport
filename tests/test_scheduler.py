from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from controller.scheduler import ScanConfig, ScanController, ScanMode, ScanSchedule
from odds_client.client import OddsResponse
from persistence.database import Database


class DummyClientWithEvent:
    def __init__(self, event):
        self.event = event

    def get_odds(self, sport_key, regions, bookmakers, markets, odds_format="american", date_format="iso"):
        return OddsResponse([self.event], None, None)

    def get_event_odds(
        self,
        sport_key,
        event_id,
        regions,
        bookmakers,
        markets,
        odds_format="american",
        date_format="iso",
    ):
        return OddsResponse(self.event, None, None)


class DummyClientEmpty:
    def get_odds(self, sport_key, regions, bookmakers, markets, odds_format="american", date_format="iso"):
        return OddsResponse([], None, None)

    def get_event_odds(
        self,
        sport_key,
        event_id,
        regions,
        bookmakers,
        markets,
        odds_format="american",
        date_format="iso",
    ):
        return OddsResponse({}, None, None)


@pytest.fixture
def scan_config():
    now = datetime.now(timezone.utc)
    return ScanConfig(
        sports=["basketball_nba"],
        regions=["us"],
        bookmakers=["book_a", "book_b"],
        markets=["h2h"],
        deep_markets=[],
        window_start=now - timedelta(hours=1),
        window_end=now + timedelta(hours=4),
        min_edge=Decimal("0.01"),
        bankroll=Decimal("100"),
        rounding=Decimal("1"),
        min_book_count=2,
        max_stake_per_book=None,
        scan_mode=ScanMode.SNAPSHOT,
        schedule=ScanSchedule(interval_seconds=60),
    )


def test_rescan_confirms_opportunity(tmp_path, scan_config):
    event = {
        "id": "evt-1",
        "commence_time": (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat(),
        "home_team": "Home",
        "away_team": "Away",
        "bookmakers": [
            {
                "key": "book_a",
                "title": "Book A",
                "markets": [
                    {
                        "key": "h2h",
                        "outcomes": [
                            {"name": "Home", "price": 110},
                            {"name": "Away", "price": -105},
                        ],
                    }
                ],
            },
            {
                "key": "book_b",
                "title": "Book B",
                "markets": [
                    {
                        "key": "h2h",
                        "outcomes": [
                            {"name": "Away", "price": 120},
                            {"name": "Home", "price": -110},
                        ],
                    }
                ],
            },
        ],
    }
    db = Database(tmp_path / "test.db")
    controller = ScanController(DummyClientWithEvent(event), db)

    result = controller.rescan_opportunity(scan_config, "evt-1", "basketball_nba", "h2h")

    assert result.status == "arbitrage"
    assert result.opportunity is not None
    assert float(result.opportunity.edge) > 0
    assert result.quotes_considered >= 2
    assert result.within_window is True


def test_rescan_handles_missing_event(tmp_path, scan_config):
    db = Database(tmp_path / "test-missing.db")
    controller = ScanController(DummyClientEmpty(), db)

    result = controller.rescan_opportunity(scan_config, "missing", "basketball_nba", "h2h")

    assert result.status == "event_not_found"
    assert result.opportunity is None
    assert result.quotes_considered == 0
