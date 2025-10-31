"""Odds API client utilities.

This module provides a thin wrapper around The Odds API endpoints used by
ArbiSport.  The wrapper keeps the HTTP handling in one place so the rest of the
application can focus on scheduling and arbitrage processing.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Iterable, Mapping, MutableMapping, Optional

import requests


class OddsApiError(RuntimeError):
    """Raised when the Odds API returns a non-success status code."""


@dataclass
class OddsResponse:
    """Container for Odds API payloads and headers."""

    data: Any
    remaining_requests: Optional[int]
    reset_time: Optional[datetime]


class OddsApiClient:
    """Simple client that talks to The Odds API."""

    BASE_URL = "https://api.the-odds-api.com/v4"

    def __init__(self, api_key: str, session: Optional[requests.Session] = None) -> None:
        if not api_key:
            raise ValueError("An Odds API key must be supplied")
        self._api_key = api_key
        self._session = session or requests.Session()

    def list_sports(self, regions: Optional[Iterable[str]] = None) -> OddsResponse:
        """Return the list of supported sports.

        Parameters mirror https://the-odds-api.com/ documentation.
        """

        params: MutableMapping[str, str] = {"apiKey": self._api_key}
        if regions:
            params["regions"] = ",".join(sorted(regions))

        return self._get("/sports", params)

    def get_odds(
        self,
        sport_key: str,
        regions: Iterable[str],
        bookmakers: Iterable[str],
        markets: Iterable[str],
        odds_format: str = "american",
        date_format: str = "iso",
    ) -> OddsResponse:
        """Fetch odds for all events of a sport.

        `regions`, `bookmakers`, and `markets` are sequences that will be
        converted to the comma-delimited format required by the API.
        """

        params: MutableMapping[str, str] = {
            "apiKey": self._api_key,
            "regions": ",".join(sorted(regions)),
            "markets": ",".join(sorted(markets)),
            "oddsFormat": odds_format,
            "dateFormat": date_format,
        }
        if bookmakers:
            params["bookmakers"] = ",".join(sorted(bookmakers))

        return self._get(f"/sports/{sport_key}/odds", params)

    def get_event_odds(
        self,
        sport_key: str,
        event_id: str,
        regions: Iterable[str],
        bookmakers: Iterable[str],
        markets: Iterable[str],
        odds_format: str = "american",
        date_format: str = "iso",
    ) -> OddsResponse:
        """Fetch deep market odds for a specific event."""

        params: MutableMapping[str, str] = {
            "apiKey": self._api_key,
            "regions": ",".join(sorted(regions)),
            "markets": ",".join(sorted(markets)),
            "oddsFormat": odds_format,
            "dateFormat": date_format,
        }
        if bookmakers:
            params["bookmakers"] = ",".join(sorted(bookmakers))

        return self._get(f"/sports/{sport_key}/events/{event_id}/odds", params)

    def _get(self, path: str, params: Mapping[str, str]) -> OddsResponse:
        url = f"{self.BASE_URL}{path}"
        response = self._session.get(url, params=params, timeout=15)
        if response.status_code != 200:
            raise OddsApiError(
                f"Odds API request failed with status {response.status_code}: {response.text}"
            )

        headers = response.headers
        remaining = _safe_int(headers.get("x-requests-remaining"))
        reset_time = _parse_reset(headers)

        return OddsResponse(response.json(), remaining, reset_time)


def _safe_int(value: Optional[str]) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _parse_reset(headers: Mapping[str, str]) -> Optional[datetime]:
    reset_timestamp = headers.get("x-requests-reset")
    if reset_timestamp:
        try:
            return datetime.fromtimestamp(int(reset_timestamp))
        except (TypeError, ValueError):
            pass

    reset_remaining = headers.get("x-requests-remaining-time")
    if reset_remaining:
        try:
            seconds = int(reset_remaining)
        except (TypeError, ValueError):
            return None
        return datetime.utcnow() if seconds <= 0 else datetime.utcnow() + timedelta(seconds=seconds)

    return None
