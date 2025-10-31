"""SQLite persistence layer for ArbiSport."""

from __future__ import annotations

import csv
import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, Iterator, List, Optional


SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id TEXT PRIMARY KEY,
    sport_key TEXT NOT NULL,
    commence_time TEXT NOT NULL,
    data TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS quotes (
    event_id TEXT NOT NULL,
    market_key TEXT NOT NULL,
    bookmaker TEXT NOT NULL,
    data TEXT NOT NULL,
    PRIMARY KEY (event_id, market_key, bookmaker),
    FOREIGN KEY (event_id) REFERENCES events(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS arbitrage (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    event_id TEXT NOT NULL,
    event_name TEXT,
    sport_key TEXT,
    commence_time TEXT,
    market_key TEXT NOT NULL,
    edge REAL NOT NULL,
    total_stake REAL NOT NULL,
    payout REAL NOT NULL,
    stake_plan TEXT NOT NULL,
    details TEXT
);

CREATE TABLE IF NOT EXISTS api_usage (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    remaining INTEGER,
    reset_time TEXT
);

CREATE TABLE IF NOT EXISTS logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    level TEXT NOT NULL,
    message TEXT NOT NULL,
    context TEXT
);
"""


@dataclass
class ArbitrageRecord:
    created_at: datetime
    event_id: str
    event_name: str
    sport_key: Optional[str]
    commence_time: Optional[datetime]
    market_key: str
    edge: float
    total_stake: float
    payout: float
    stake_plan: Dict[str, float]
    details: List[dict]


@dataclass
class LogRecord:
    id: int
    created_at: datetime
    level: str
    message: str
    context: Optional[dict]


@dataclass
class ScanSummary:
    event_count: int
    last_event_time: Optional[datetime]
    arbitrage_count: int
    last_arbitrage_time: Optional[datetime]
    remaining_requests: Optional[int]
    reset_time: Optional[datetime]


class Database:
    def __init__(self, path: str | Path = "arbisport.db") -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(SCHEMA)
            self._ensure_arbitrage_columns(conn)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self._path)
        try:
            yield conn
        finally:
            conn.commit()
            conn.close()

    def _ensure_arbitrage_columns(self, conn: sqlite3.Connection) -> None:
        """Ensure newer arbitrage columns exist for upgraded databases."""

        existing = {row[1] for row in conn.execute("PRAGMA table_info(arbitrage)")}
        if "event_name" not in existing:
            conn.execute("ALTER TABLE arbitrage ADD COLUMN event_name TEXT")
        if "sport_key" not in existing:
            conn.execute("ALTER TABLE arbitrage ADD COLUMN sport_key TEXT")
        if "commence_time" not in existing:
            conn.execute("ALTER TABLE arbitrage ADD COLUMN commence_time TEXT")
        if "details" not in existing:
            conn.execute("ALTER TABLE arbitrage ADD COLUMN details TEXT")

    def record_event(self, event_id: str, sport_key: str, commence_time: str, data: dict) -> None:
        with self._connect() as conn:
            conn.execute(
                "REPLACE INTO events (id, sport_key, commence_time, data) VALUES (?, ?, ?, ?)",
                (event_id, sport_key, commence_time, json.dumps(data)),
            )

    def record_quotes(self, event_id: str, market_key: str, bookmaker: str, data: dict) -> None:
        with self._connect() as conn:
            conn.execute(
                "REPLACE INTO quotes (event_id, market_key, bookmaker, data) VALUES (?, ?, ?, ?)",
                (event_id, market_key, bookmaker, json.dumps(data)),
            )

    def record_arbitrage(
        self,
        event_id: str,
        event_name: str,
        sport_key: str,
        commence_time: Optional[datetime],
        market_key: str,
        edge: float,
        total_stake: float,
        payout: float,
        stake_plan: Dict[str, float],
        details: List[dict],
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO arbitrage (created_at, event_id, event_name, sport_key, commence_time, market_key, edge, total_stake, payout, stake_plan, details)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    datetime.utcnow().isoformat(),
                    event_id,
                    event_name,
                    sport_key,
                    commence_time.isoformat() if commence_time else None,
                    market_key,
                    edge,
                    total_stake,
                    payout,
                    json.dumps(stake_plan),
                    json.dumps(details),
                ),
            )

    def log_api_usage(self, remaining: Optional[int], reset_time: Optional[datetime]) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO api_usage (created_at, remaining, reset_time) VALUES (?, ?, ?)",
                (
                    datetime.utcnow().isoformat(),
                    remaining,
                    reset_time.isoformat() if reset_time else None,
                ),
            )
        self.log(
            "info",
            "API usage updated",
            {
                "remaining_requests": remaining,
                "reset_time": reset_time.isoformat() if reset_time else None,
            },
        )

    def log(self, level: str, message: str, context: Optional[dict] = None) -> int:
        with self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO logs (created_at, level, message, context) VALUES (?, ?, ?, ?)",
                (
                    datetime.utcnow().isoformat(),
                    level,
                    message,
                    json.dumps(context) if context else None,
                ),
            )
            return int(cur.lastrowid)

    def history(self, limit: int = 100) -> Iterable[ArbitrageRecord]:
        with self._connect() as conn:
            cur = conn.execute(
                "SELECT created_at, event_id, event_name, sport_key, commence_time, market_key, edge, total_stake, payout, stake_plan, details"
                " FROM arbitrage ORDER BY created_at DESC LIMIT ?",
                (limit,),
            )
            for row in cur.fetchall():
                created_at = datetime.fromisoformat(row[0])
                event_id = row[1]
                event_name = row[2]
                sport_key = row[3]
                commence_raw = row[4]
                commence_time = datetime.fromisoformat(commence_raw) if commence_raw else None
                market_key = row[5]
                edge = row[6]
                total_stake = row[7]
                payout = row[8]
                stake_plan_json = row[9]
                details_json = row[10]
                if not event_name or commence_time is None:
                    fallback = conn.execute(
                        "SELECT data FROM events WHERE id = ?",
                        (event_id,),
                    ).fetchone()
                    if fallback and fallback[0]:
                        payload = json.loads(fallback[0])
                        event_name = event_name or _derive_event_title(payload)
                        commence_time = commence_time or _derive_commence_time(payload)
                yield ArbitrageRecord(
                    created_at=created_at,
                    event_id=event_id,
                    event_name=event_name or event_id,
                    sport_key=sport_key,
                    commence_time=commence_time,
                    market_key=market_key,
                    edge=edge,
                    total_stake=total_stake,
                    payout=payout,
                    stake_plan=json.loads(stake_plan_json),
                    details=json.loads(details_json) if details_json else [],
                )

    def fetch_logs(self, since_id: Optional[int] = None, limit: int = 200) -> List[LogRecord]:
        query = "SELECT id, created_at, level, message, context FROM logs"
        params: tuple
        if since_id is not None:
            query += " WHERE id > ? ORDER BY id ASC LIMIT ?"
            params = (since_id, limit)
        else:
            query += " ORDER BY id ASC LIMIT ?"
            params = (limit,)

        with self._connect() as conn:
            cur = conn.execute(query, params)
            records: List[LogRecord] = []
            for log_id, created_at, level, message, context in cur.fetchall():
                parsed_context = json.loads(context) if context else None
                records.append(
                    LogRecord(
                        id=int(log_id),
                        created_at=datetime.fromisoformat(created_at),
                        level=level,
                        message=message,
                        context=parsed_context,
                    )
                )
            return records

    def scan_summary(self) -> ScanSummary:
        with self._connect() as conn:
            event_count, last_event = conn.execute(
                "SELECT COUNT(*), MAX(commence_time) FROM events"
            ).fetchone()
            arb_count, last_arb = conn.execute(
                "SELECT COUNT(*), MAX(created_at) FROM arbitrage"
            ).fetchone()
            latest_usage = conn.execute(
                "SELECT remaining, reset_time FROM api_usage ORDER BY id DESC LIMIT 1"
            ).fetchone()

        last_event_time = datetime.fromisoformat(last_event) if last_event else None
        last_arb_time = datetime.fromisoformat(last_arb) if last_arb else None
        remaining_requests: Optional[int] = None
        reset_time: Optional[datetime] = None
        if latest_usage:
            remaining_value, reset_value = latest_usage
            remaining_requests = int(remaining_value) if remaining_value is not None else None
            reset_time = datetime.fromisoformat(reset_value) if reset_value else None
        return ScanSummary(
            event_count=int(event_count or 0),
            last_event_time=last_event_time,
            arbitrage_count=int(arb_count or 0),
            last_arbitrage_time=last_arb_time,
            remaining_requests=remaining_requests,
            reset_time=reset_time,
        )

    def latest_api_usage(self) -> tuple[Optional[int], Optional[datetime]]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT remaining, reset_time FROM api_usage ORDER BY id DESC LIMIT 1"
            ).fetchone()
        if not row:
            return None, None
        remaining, reset = row
        remaining_value = int(remaining) if remaining is not None else None
        reset_time = datetime.fromisoformat(reset) if reset else None
        return remaining_value, reset_time

    def export_history_csv(self, output_path: str | Path) -> Path:
        output = Path(output_path)
        rows = list(self.history(limit=1000))
        with output.open("w", newline="", encoding="utf-8") as csvfile:
            writer = csv.writer(csvfile)
            writer.writerow(
                [
                    "timestamp",
                    "event_id",
                    "event_name",
                    "sport_key",
                    "commence_time",
                    "market",
                    "edge",
                    "total_stake",
                    "payout",
                    "stake_plan",
                    "recommendations",
                ]
            )
            for row in rows:
                writer.writerow(
                    [
                        row.created_at.isoformat(),
                        row.event_id,
                        row.event_name,
                        row.sport_key or "",
                        row.commence_time.isoformat() if row.commence_time else "",
                        row.market_key,
                        f"{row.edge:.4f}",
                        f"{row.total_stake:.2f}",
                        f"{row.payout:.2f}",
                        json.dumps(row.stake_plan),
                        json.dumps(row.details),
                    ]
                )
        return output


def _derive_event_title(payload: dict) -> Optional[str]:
    if not isinstance(payload, dict):
        return None
    home = payload.get("home_team")
    away = payload.get("away_team")
    if home and away:
        return f"{away} @ {home}"
    title = payload.get("sport_title") or payload.get("title")
    if isinstance(title, str):
        return title
    return None


def _derive_commence_time(payload: dict) -> Optional[datetime]:
    if not isinstance(payload, dict):
        return None
    commence_value = payload.get("commence_time")
    if not isinstance(commence_value, str):
        return None
    try:
        if commence_value.endswith("Z"):
            return datetime.fromisoformat(commence_value.replace("Z", "+00:00"))
        return datetime.fromisoformat(commence_value)
    except ValueError:
        return None
