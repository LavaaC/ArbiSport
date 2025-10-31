"""PySide6 user interface for ArbiSport."""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from functools import partial
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence

from PySide6.QtCore import QDateTime, QRunnable, Qt, QThreadPool, Signal, Slot, QTimer
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDateTimeEdit,
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)
from controller.scheduler import ScanConfig, ScanController, ScanMode, ScanSchedule
from normalize.names import NameNormalizer
from odds_client.catalog import (
    ALL_BOOKMAKERS,
    ALL_SPORTS,
    BookmakerInfo,
    SportInfo,
    filter_bookmakers_by_regions,
)
from odds_client.deep_markets import get_deep_markets_for_sport
from odds_client.client import OddsApiClient
from persistence.database import ArbitrageRecord, Database, LogRecord


class SnapshotRunnable(QRunnable):
    def __init__(self, controller: ScanController, config: ScanConfig) -> None:
        super().__init__()
        self._controller = controller
        self._config = config

    def run(self) -> None:  # pragma: no cover - executed in Qt thread pool
        self._controller.run_snapshot(self._config)


@dataclass
class SelectionItem:
    key: str
    label: str
    description: str = ""


class MultiSelectDialog(QDialog):
    def __init__(
        self,
        title: str,
        items: Sequence[SelectionItem],
        selected: Sequence[str],
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self._items = list(items)
        self.selected_keys: List[str] = list(selected)
        self._build_ui(selected)

    def _build_ui(self, selected: Sequence[str]) -> None:
        layout = QVBoxLayout(self)

        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Filter…")
        layout.addWidget(self.search_edit)

        self.list_widget = QListWidget()
        self.list_widget.setSelectionMode(QListWidget.MultiSelection)
        selected_set = set(selected)
        for item in self._items:
            entry = QListWidgetItem(item.label)
            entry.setData(Qt.UserRole, item.key)
            if item.description:
                entry.setToolTip(item.description)
            if item.key in selected_set:
                entry.setSelected(True)
            self.list_widget.addItem(entry)
        layout.addWidget(self.list_widget)

        button_row = QHBoxLayout()
        self.select_all_button = QPushButton("Select all")
        self.clear_button = QPushButton("Clear")
        self.ok_button = QPushButton("OK")
        self.cancel_button = QPushButton("Cancel")
        button_row.addWidget(self.select_all_button)
        button_row.addWidget(self.clear_button)
        button_row.addStretch()
        button_row.addWidget(self.ok_button)
        button_row.addWidget(self.cancel_button)
        layout.addLayout(button_row)

        self.search_edit.textChanged.connect(self._filter_items)
        self.select_all_button.clicked.connect(self._select_all)
        self.clear_button.clicked.connect(self._clear_selection)
        self.ok_button.clicked.connect(self._accept)
        self.cancel_button.clicked.connect(self.reject)

    def _filter_items(self, text: str) -> None:
        query = text.casefold()
        for index in range(self.list_widget.count()):
            item = self.list_widget.item(index)
            item.setHidden(bool(query and query not in item.text().casefold()))

    def _select_all(self) -> None:
        for index in range(self.list_widget.count()):
            self.list_widget.item(index).setSelected(True)

    def _clear_selection(self) -> None:
        self.list_widget.clearSelection()

    def _accept(self) -> None:
        self.selected_keys = [item.data(Qt.UserRole) for item in self.list_widget.selectedItems()]
        self.accept()

class SettingsTab(QWidget):
    config_applied = Signal(ScanConfig, OddsApiClient)

    def __init__(self, database: Database, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._db = database
        self._thread_pool = QThreadPool.globalInstance()
        self._client: Optional[OddsApiClient] = None
        self._available_sports: List[SportInfo] = list(ALL_SPORTS)
        self._available_bookmakers: List[BookmakerInfo] = list(ALL_BOOKMAKERS)
        self._selected_sports: List[str] = [sport.key for sport in self._available_sports]
        self._selected_bookmakers: List[str] = [book.key for book in self._available_bookmakers]
        self._per_sport_deep_markets: Dict[str, List[str]] = {}
        self._markets = ["h2h", "spreads", "totals"]
        self._regions = ["us", "uk", "eu", "au"]
        self._window_presets = {
            "Next 2 hours": 2,
            "Next 6 hours": 6,
            "Next 24 hours": 24,
        }
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        form_group = QGroupBox("API Settings")
        form_layout = QFormLayout(form_group)

        self.api_key_edit = QLineEdit()
        self.api_key_edit.setEchoMode(QLineEdit.Password)
        form_layout.addRow("API Key", self.api_key_edit)

        self.region_box = QListWidget()
        self.region_box.setSelectionMode(QListWidget.MultiSelection)
        for region in self._regions:
            item = QListWidgetItem(region)
            item.setSelected(region == "us")
            self.region_box.addItem(item)
        form_layout.addRow("Regions", self.region_box)

        sports_row = QHBoxLayout()
        self.sports_summary = QLabel()
        self.sports_summary.setWordWrap(True)
        self.sports_summary.setMinimumWidth(300)
        self.sports_browse_button = QPushButton("Browse…")
        sports_row.addWidget(self.sports_summary, 1)
        sports_row.addWidget(self.sports_browse_button)
        sports_widget = QWidget()
        sports_widget.setLayout(sports_row)
        form_layout.addRow("Sports", sports_widget)

        books_row = QHBoxLayout()
        self.bookmakers_summary = QLabel()
        self.bookmakers_summary.setWordWrap(True)
        self.bookmakers_summary.setMinimumWidth(300)
        self.bookmakers_browse_button = QPushButton("Browse…")
        books_row.addWidget(self.bookmakers_summary, 1)
        books_row.addWidget(self.bookmakers_browse_button)
        books_widget = QWidget()
        books_widget.setLayout(books_row)
        form_layout.addRow("Bookmakers", books_widget)

        self.markets_box = QListWidget()
        self.markets_box.setSelectionMode(QListWidget.MultiSelection)
        for market in self._markets:
            item = QListWidgetItem(market)
            item.setSelected(True)
            self.markets_box.addItem(item)
        form_layout.addRow("Markets", self.markets_box)

        deep_market_row = QHBoxLayout()
        self.deep_markets_edit = QLineEdit()
        self.deep_markets_edit.setPlaceholderText("Comma-separated deep markets (e.g., correct_score)")
        self.deep_market_browser = QPushButton("Browse…")
        deep_market_row.addWidget(self.deep_markets_edit)
        deep_market_row.addWidget(self.deep_market_browser)
        deep_market_widget = QWidget()
        deep_market_widget.setLayout(deep_market_row)
        form_layout.addRow("Deep markets", deep_market_widget)

        self.deep_market_summary = QLabel("Applies to all selected sports")
        self.deep_market_summary.setWordWrap(True)
        form_layout.addRow("Overrides", self.deep_market_summary)

        self.window_preset_combo = QComboBox()
        self.window_preset_combo.addItems(["Custom range", *self._window_presets.keys()])
        form_layout.addRow("Time preset", self.window_preset_combo)

        self.window_start = QDateTimeEdit(QDateTime.currentDateTime())
        self.window_end = QDateTimeEdit(QDateTime.currentDateTime().addDays(1))
        self.window_start.setCalendarPopup(True)
        self.window_end.setCalendarPopup(True)
        form_layout.addRow("Window start", self.window_start)
        form_layout.addRow("Window end", self.window_end)

        self.edge_spin = QDoubleSpinBox()
        self.edge_spin.setRange(0.0, 100.0)
        self.edge_spin.setSingleStep(0.1)
        self.edge_spin.setValue(0.5)
        form_layout.addRow("Min edge (%)", self.edge_spin)

        self.bankroll_spin = QDoubleSpinBox()
        self.bankroll_spin.setRange(1.0, 1_000_000.0)
        self.bankroll_spin.setValue(100.0)
        form_layout.addRow("Bankroll", self.bankroll_spin)

        self.rounding_spin = QDoubleSpinBox()
        self.rounding_spin.setRange(0.01, 100.0)
        self.rounding_spin.setValue(1.0)
        form_layout.addRow("Stake rounding", self.rounding_spin)

        self.max_per_book_spin = QDoubleSpinBox()
        self.max_per_book_spin.setRange(0.0, 1_000_000.0)
        self.max_per_book_spin.setSpecialValueText("No limit")
        self.max_per_book_spin.setValue(0.0)
        form_layout.addRow("Max stake per book", self.max_per_book_spin)

        self.min_books_spin = QSpinBox()
        self.min_books_spin.setRange(1, 10)
        self.min_books_spin.setValue(2)
        form_layout.addRow("Min books per market", self.min_books_spin)

        self.scan_mode_combo = QComboBox()
        self.scan_mode_combo.addItems([mode.value for mode in ScanMode])
        form_layout.addRow("Scan mode", self.scan_mode_combo)

        self.interval_spin = QSpinBox()
        self.interval_spin.setRange(5, 3600)
        self.interval_spin.setValue(60)
        form_layout.addRow("Interval (s)", self.interval_spin)

        self.burst_interval_spin = QSpinBox()
        self.burst_interval_spin.setRange(5, 3600)
        self.burst_interval_spin.setValue(15)
        form_layout.addRow("Burst interval (s)", self.burst_interval_spin)

        self.burst_window_spin = QSpinBox()
        self.burst_window_spin.setRange(1, 180)
        self.burst_window_spin.setValue(10)
        form_layout.addRow("Burst window (min)", self.burst_window_spin)

        self.test_button = QPushButton("Test API")
        self.apply_button = QPushButton("Save & Apply")

        button_layout = QHBoxLayout()
        button_layout.addWidget(self.test_button)
        button_layout.addWidget(self.apply_button)

        layout.addWidget(form_group)
        layout.addLayout(button_layout)
        layout.addStretch()

        self.test_button.clicked.connect(self._on_test_api)
        self.apply_button.clicked.connect(self._on_apply)
        self.window_preset_combo.currentTextChanged.connect(self._on_preset_changed)
        self.deep_market_browser.clicked.connect(self._open_deep_market_browser)
        self.sports_browse_button.clicked.connect(self._open_sport_browser)
        self.bookmakers_browse_button.clicked.connect(self._open_bookmaker_browser)
        self._on_preset_changed(self.window_preset_combo.currentText())
        self._refresh_sport_summary()
        self._refresh_bookmaker_summary()
        self._refresh_deep_market_summary()

    def _selected_items(self, widget: QListWidget) -> List[str]:
        selections: List[str] = []
        for item in widget.selectedItems():
            key = item.data(Qt.UserRole)
            selections.append(key if key else item.text())
        return selections

    def _refresh_sport_summary(self) -> None:
        label_map = {sport.key: f"{sport.title} ({sport.group})" for sport in self._available_sports}
        summary = self._format_selection_summary(self._selected_sports, label_map, len(self._available_sports))
        self.sports_summary.setText(summary)

    def _refresh_bookmaker_summary(self) -> None:
        label_map = {
            book.key: f"{book.title} [{'/'.join(book.regions)}]"
            for book in self._available_bookmakers
        }
        summary = self._format_selection_summary(self._selected_bookmakers, label_map, len(self._available_bookmakers))
        self.bookmakers_summary.setText(summary)

    def _format_selection_summary(
        self,
        selected_keys: Sequence[str],
        label_map: Dict[str, str],
        total_available: int,
    ) -> str:
        if not selected_keys or set(selected_keys) == set(label_map.keys()):
            return f"All ({total_available})"
        names = [label_map[key] for key in selected_keys if key in label_map]
        if not names:
            return "None selected"
        if len(names) > 5:
            return ", ".join(names[:5]) + f" … (+{len(names) - 5} more)"
        return ", ".join(names)

    def _open_sport_browser(self) -> None:
        items = [
            SelectionItem(key=sport.key, label=f"{sport.title} ({sport.group})", description=sport.key)
            for sport in self._available_sports
        ]
        dialog = MultiSelectDialog("Select sports", items, self._selected_sports, self)
        if dialog.exec() == QDialog.Accepted:
            self._selected_sports = dialog.selected_keys or [sport.key for sport in self._available_sports]
            self._refresh_sport_summary()

    def _open_bookmaker_browser(self) -> None:
        items = [
            SelectionItem(
                key=book.key,
                label=f"{book.title} ({'/'.join(book.regions)})",
                description=(book.url or book.key),
            )
            for book in self._available_bookmakers
        ]
        dialog = MultiSelectDialog("Select bookmakers", items, self._selected_bookmakers, self)
        if dialog.exec() == QDialog.Accepted:
            self._selected_bookmakers = dialog.selected_keys or [book.key for book in self._available_bookmakers]
            self._refresh_bookmaker_summary()

    def _refresh_deep_market_summary(self) -> None:
        if not self._per_sport_deep_markets:
            self.deep_market_summary.setText("Applies to all selected sports")
            return
        parts: List[str] = []
        title_map = {sport.key: sport.title for sport in self._available_sports}
        for sport_key, markets in sorted(self._per_sport_deep_markets.items()):
            if not markets:
                continue
            preview = list(dict.fromkeys(markets))
            display = ", ".join(preview[:4])
            if len(preview) > 4:
                display += f" … (+{len(preview) - 4})"
            parts.append(f"{title_map.get(sport_key, sport_key)}: {display}")
        self.deep_market_summary.setText("; ".join(parts) if parts else "Applies to all selected sports")

    def _on_test_api(self) -> None:
        api_key = self.api_key_edit.text().strip()
        if not api_key:
            QMessageBox.warning(self, "Missing key", "Please enter an API key first.")
            return
        regions = self._selected_items(self.region_box)
        try:
            client = OddsApiClient(api_key)
            response = client.list_sports(regions=regions, include_all=True)
            sports: List[SportInfo] = []
            known_by_key = {sport.key: sport for sport in ALL_SPORTS}
            for entry in response.data or []:
                key = entry.get("key") if isinstance(entry, dict) else None
                if not key:
                    continue
                if key in known_by_key:
                    sports.append(known_by_key[key])
                    continue
                title = entry.get("title") if isinstance(entry, dict) else None
                group = entry.get("group") if isinstance(entry, dict) else None
                sports.append(
                    SportInfo(
                        key=key,
                        title=title or key,
                        group=group or "Other",
                    )
                )
            if not sports:
                sports = ALL_SPORTS
        except Exception as exc:
            QMessageBox.critical(self, "API error", f"Failed to validate key: {exc}")
            return

        self._client = client
        self._available_sports = sports
        available_sport_keys = [sport.key for sport in sports]
        self._selected_sports = [key for key in self._selected_sports if key in available_sport_keys]
        if not self._selected_sports:
            self._selected_sports = list(available_sport_keys)
        self._per_sport_deep_markets = {
            sport_key: markets
            for sport_key, markets in self._per_sport_deep_markets.items()
            if sport_key in available_sport_keys
        }
        self._refresh_sport_summary()

        try:
            bookmaker_response = client.list_bookmakers(regions=regions)
            bookmaker_keys: List[BookmakerInfo] = []
            known_books = {book.key: book for book in ALL_BOOKMAKERS}
            for entry in bookmaker_response.data or []:
                if not isinstance(entry, dict):
                    continue
                key = entry.get("key")
                if not key:
                    continue
                if key in known_books:
                    bookmaker_keys.append(known_books[key])
                    continue
                title = entry.get("title") or key
                regions_meta = entry.get("regions")
                if isinstance(regions_meta, str):
                    regions_tuple = tuple(part.strip().lower() for part in regions_meta.split(",") if part.strip())
                elif isinstance(regions_meta, list):
                    regions_tuple = tuple(str(part).lower() for part in regions_meta if str(part))
                else:
                    regions_tuple = tuple()
                bookmaker_keys.append(
                    BookmakerInfo(key=key, title=title, regions=regions_tuple or ("global",))
                )
        except Exception:
            bookmaker_keys = []

        if bookmaker_keys:
            bookmakers = bookmaker_keys
        else:
            bookmakers = filter_bookmakers_by_regions(regions or [])

        self._available_bookmakers = bookmakers
        available_book_keys = [book.key for book in bookmakers]
        self._selected_bookmakers = [key for key in self._selected_bookmakers if key in available_book_keys]
        if not self._selected_bookmakers:
            self._selected_bookmakers = list(available_book_keys)
        self._refresh_bookmaker_summary()
        self._refresh_deep_market_summary()

        QMessageBox.information(
            self,
            "Success",
            f"API key validated. {len(self._available_sports)} sports available.",
        )

    def _on_apply(self) -> None:
        api_key = self.api_key_edit.text().strip()
        if not api_key:
            QMessageBox.warning(self, "Missing key", "Enter an API key before applying settings.")
            return
        client = self._client or OddsApiClient(api_key)

        sports = self._selected_sports or [sport.key for sport in self._available_sports]
        regions = self._selected_items(self.region_box) or ["us"]
        bookmakers = self._selected_bookmakers or [book.key for book in self._available_bookmakers]
        markets = self._selected_items(self.markets_box) or ["h2h"]
        deep_markets = [segment.strip() for segment in self.deep_markets_edit.text().split(",") if segment.strip()]

        window_start = self.window_start.dateTime().toPython()
        window_end = self.window_end.dateTime().toPython()
        max_per_book_value = Decimal(str(self.max_per_book_spin.value()))
        max_per_book = None if self.max_per_book_spin.value() == 0.0 else max_per_book_value

        config = ScanConfig(
            sports=sports,
            regions=regions,
            bookmakers=bookmakers,
            markets=markets,
            deep_markets=deep_markets,
            deep_market_map={key: list(values) for key, values in self._per_sport_deep_markets.items()},
            window_start=window_start,
            window_end=window_end,
            min_edge=Decimal(str(self.edge_spin.value() / 100)),
            bankroll=Decimal(str(self.bankroll_spin.value())),
            rounding=Decimal(str(self.rounding_spin.value())),
            min_book_count=self.min_books_spin.value(),
            max_stake_per_book=max_per_book,
            scan_mode=ScanMode(self.scan_mode_combo.currentText()),
            schedule=ScanSchedule(
                interval_seconds=self.interval_spin.value(),
                burst_interval_seconds=self.burst_interval_spin.value(),
                burst_window_minutes=self.burst_window_spin.value(),
            ),
        )

        self._client = client
        self.config_applied.emit(config, client)

    def _open_deep_market_browser(self) -> None:
        api_key = self.api_key_edit.text().strip()
        if not api_key:
            QMessageBox.warning(
                self,
                "API key required",
                "Enter your Odds API key and test it before browsing deep markets.",
            )
            return

        client = self._client or OddsApiClient(api_key)
        self._client = client
        dialog = DeepMarketExplorerDialog(
            client,
            self._available_sports,
            existing=self._per_sport_deep_markets,
            parent=self,
        )
        if dialog.exec() == QDialog.Accepted:
            if dialog.global_markets:
                self.deep_markets_edit.setText(",".join(dialog.global_markets))
            self._per_sport_deep_markets = dialog.sport_overrides
            self._refresh_deep_market_summary()

    def _on_preset_changed(self, preset: str) -> None:
        if preset == "Custom range":
            self.window_start.setEnabled(True)
            self.window_end.setEnabled(True)
            return

        hours = self._window_presets.get(preset)
        if hours is None:
            return

        now = QDateTime.currentDateTime()
        self.window_start.setDateTime(now)
        self.window_end.setDateTime(now.addSecs(hours * 3600))
        self.window_start.setEnabled(False)
        self.window_end.setEnabled(False)


class ArbitrageTab(QWidget):
    rescan_requested = Signal(str, str, str)

    def __init__(self, database: Database, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._db = database
        self._build_ui()
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setInterval(10_000)
        self._refresh_timer.timeout.connect(self.refresh)
        self._refresh_timer.start()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        self.table = QTableWidget(0, 8)
        self.table.setHorizontalHeaderLabels(
            [
                "Timestamp",
                "Event",
                "Market",
                "Edge %",
                "Total stake",
                "Payout",
                "Recommendations",
                "Actions",
            ]
        )
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(5, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(6, QHeaderView.Stretch)
        header.setSectionResizeMode(7, QHeaderView.ResizeToContents)
        self.table.verticalHeader().setVisible(False)
        self.table.setWordWrap(True)
        layout.addWidget(self.table)

        self.export_button = QPushButton("Export CSV")
        self.export_button.clicked.connect(self._export_csv)
        layout.addWidget(self.export_button, alignment=Qt.AlignRight)

    def refresh(self) -> None:
        records = list(self._db.history(limit=100))
        self.table.setRowCount(len(records))
        for row_idx, record in enumerate(records):
            self.table.setItem(row_idx, 0, QTableWidgetItem(record.created_at.isoformat()))
            event_parts = [record.event_name]
            if record.commence_time:
                event_parts.append(record.commence_time.strftime("%Y-%m-%d %H:%M"))
            if record.sport_key:
                event_parts.append(record.sport_key)
            self.table.setItem(row_idx, 1, QTableWidgetItem("\n".join(event_parts)))
            self.table.setItem(row_idx, 2, QTableWidgetItem(record.market_key))
            self.table.setItem(row_idx, 3, QTableWidgetItem(f"{record.edge * 100:.2f}"))
            self.table.setItem(row_idx, 4, QTableWidgetItem(f"${record.total_stake:.2f}"))
            self.table.setItem(row_idx, 5, QTableWidgetItem(f"${record.payout:.2f}"))
            recommendation_text = self._format_recommendations(record.details)
            rec_item = QTableWidgetItem(recommendation_text)
            rec_item.setToolTip(recommendation_text)
            self.table.setItem(row_idx, 6, rec_item)
            button = self._make_rescan_button(record)
            self.table.setCellWidget(row_idx, 7, button)
        self.table.resizeRowsToContents()

    def _make_rescan_button(self, record: ArbitrageRecord) -> QPushButton:
        button = QPushButton("Rescan")
        if record.sport_key:
            callback = partial(
                self.rescan_requested.emit,
                record.event_id,
                record.sport_key,
                record.market_key,
            )
            button.clicked.connect(callback)
        else:
            button.setEnabled(False)
            button.setToolTip("Sport information unavailable for this record.")
        return button

    @staticmethod
    def _format_recommendations(details: List[dict]) -> str:
        if not details:
            return ""
        parts: List[str] = []
        for entry in details:
            if isinstance(entry, dict):
                stake_raw = entry.get("stake")
                bookmaker = entry.get("bookmaker_title") or entry.get("bookmaker_key", "?")
                odds = entry.get("american_odds")
                outcome = entry.get("label")
                regions_value = entry.get("regions", [])
                url = entry.get("url")
            else:
                stake_raw = getattr(entry, "stake", 0)
                bookmaker = getattr(entry, "bookmaker_title", None) or getattr(
                    entry, "bookmaker_key", "?"
                )
                odds = getattr(entry, "american_odds", None)
                outcome = getattr(entry, "label", "")
                regions_value = getattr(entry, "bookmaker_regions", ())
                url = getattr(entry, "url", None)
            try:
                stake_value = float(stake_raw)
            except (TypeError, ValueError):
                stake_value = 0.0
            if isinstance(regions_value, (list, tuple)):
                regions = "/".join(str(region) for region in regions_value if region)
            elif regions_value:
                regions = str(regions_value)
            else:
                regions = ""
            piece = f"Stake ${stake_value:.2f} on {outcome} @ {odds} with {bookmaker}"
            if regions:
                piece += f" [{regions}]"
            if url:
                piece += f" — {url}"
            parts.append(piece)
        return "\n".join(parts)

    def _export_csv(self) -> None:
        path = self._db.export_history_csv(Path("arb_history.csv"))
        QMessageBox.information(self, "Export complete", f"Saved history to {path}")


class LogsTab(QWidget):
    def __init__(self, database: Database, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._db = database
        self._entries: List[LogRecord] = []
        self._build_ui()
        self._last_log_id = 0
        self._timer = QTimer(self)
        self._timer.setInterval(3000)
        self._timer.timeout.connect(self._poll_logs)
        self._timer.start()
        self._poll_logs()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        self.tabs = QTabWidget()

        readable = QWidget()
        readable_layout = QVBoxLayout(readable)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Time", "Level", "Message", "Details"])
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.Stretch)
        header.setSectionResizeMode(3, QHeaderView.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        readable_layout.addWidget(self.table)
        self.tabs.addTab(readable, "Readable")

        self.raw_view = QTextEdit()
        self.raw_view.setReadOnly(True)
        self.tabs.addTab(self.raw_view, "Raw feed")

        layout.addWidget(self.tabs)

    def append_log(self, level: str, message: str) -> None:
        timestamp = datetime.utcnow().isoformat()
        record = LogRecord(
            id=self._last_log_id + 1,
            created_at=datetime.fromisoformat(timestamp),
            level=level,
            message=message,
            context=None,
        )
        self._append_entry(record)

    def _poll_logs(self) -> None:
        records = self._db.fetch_logs(since_id=self._last_log_id)
        for record in records:
            self._append_entry(record)
            self._last_log_id = record.id

    def _append_entry(self, record: LogRecord) -> None:
        context_text = self._format_context(record.context)
        self.raw_view.append(
            f"[{record.created_at.isoformat()}] {record.level.upper()}: {record.message}{(' ' + context_text) if context_text else ''}"
        )
        self._entries.append(record)
        if len(self._entries) > 500:
            self._entries = self._entries[-500:]
        self._render_table()

    def _render_table(self) -> None:
        rows = self._entries[-500:]
        self.table.setRowCount(len(rows))
        for row_idx, record in enumerate(rows):
            self.table.setItem(row_idx, 0, QTableWidgetItem(record.created_at.strftime("%Y-%m-%d %H:%M:%S")))
            self.table.setItem(row_idx, 1, QTableWidgetItem(record.level.upper()))
            self.table.setItem(row_idx, 2, QTableWidgetItem(record.message))
            details = self._format_context(record.context)
            details_item = QTableWidgetItem(details)
            details_item.setToolTip(details)
            self.table.setItem(row_idx, 3, details_item)
        self.table.scrollToBottom()

    @staticmethod
    def _format_context(context: Optional[dict]) -> str:
        if not context:
            return ""
        if isinstance(context, dict):
            parts = []
            for key in sorted(context.keys()):
                value = context[key]
                if isinstance(value, (list, dict)):
                    parts.append(f"{key}={json.dumps(value)}")
                else:
                    parts.append(f"{key}={value}")
            return ", ".join(parts)
        return str(context)


class DashboardTab(QWidget):
    def __init__(self, database: Database, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._db = database
        self._build_ui()
        self._timer = QTimer(self)
        self._timer.setInterval(5000)
        self._timer.timeout.connect(self.refresh)
        self._timer.start()
        self.refresh()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        self.status_label = QLabel("No scans run yet")
        layout.addWidget(self.status_label)

    def update_status(self, message: str) -> None:
        self.status_label.setText(message)

    def refresh(self) -> None:
        summary = self._db.scan_summary()
        parts = [
            f"Events tracked: {summary.event_count}",
            f"Last event time: {self._format_time(summary.last_event_time)}",
            f"Arbs found: {summary.arbitrage_count}",
            f"Last arb time: {self._format_time(summary.last_arbitrage_time)}",
            f"API credits remaining: {summary.remaining_requests if summary.remaining_requests is not None else '—'}",
            f"API reset time: {self._format_time(summary.reset_time)}",
        ]
        self.status_label.setText("\n".join(parts))

    @staticmethod
    def _format_time(value: Optional[datetime]) -> str:
        if not value:
            return "—"
        return value.strftime("%Y-%m-%d %H:%M:%S")


class MainWindow(QMainWindow):
    def __init__(self, database: Database, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("ArbiSport")
        self._db = database
        self._name_normalizer = NameNormalizer()
        self._controller: Optional[ScanController] = None
        self._config: Optional[ScanConfig] = None
        self._client: Optional[OddsApiClient] = None

        self.tabs = QTabWidget()
        self.settings_tab = SettingsTab(database)
        self.dashboard_tab = DashboardTab(database)
        self.arbitrage_tab = ArbitrageTab(database)
        self.logs_tab = LogsTab(database)

        self.tabs.addTab(self.settings_tab, "Settings")
        self.tabs.addTab(self.dashboard_tab, "Dashboard")
        self.tabs.addTab(self.arbitrage_tab, "Arbitrage")
        self.tabs.addTab(self.logs_tab, "Logs")
        self.setCentralWidget(self.tabs)

        self.settings_tab.config_applied.connect(self._on_config_applied)
        self.arbitrage_tab.rescan_requested.connect(self._handle_rescan_request)

        toolbar = self.addToolBar("Controls")
        self.snapshot_action = QAction("Run Snapshot", self)
        self.start_action = QAction("Start", self)
        self.stop_action = QAction("Stop", self)
        toolbar.addAction(self.snapshot_action)
        toolbar.addAction(self.start_action)
        toolbar.addAction(self.stop_action)

        self.snapshot_action.triggered.connect(self._run_snapshot)
        self.start_action.triggered.connect(self._start_scanning)
        self.stop_action.triggered.connect(self._stop_scanning)

    @Slot(ScanConfig, OddsApiClient)
    def _on_config_applied(self, config: ScanConfig, client: OddsApiClient) -> None:
        self._config = config
        self._client = client
        self._controller = ScanController(client, self._db, self._name_normalizer)
        self.dashboard_tab.update_status("Configuration applied. Ready to scan.")

    def _ensure_config(self) -> bool:
        if not self._config or not self._controller:
            QMessageBox.warning(self, "Missing configuration", "Apply settings before scanning.")
            return False
        return True

    def _run_snapshot(self) -> None:
        if not self._ensure_config():
            return
        runnable = SnapshotRunnable(self._controller, self._config)
        QThreadPool.globalInstance().start(runnable)
        self.dashboard_tab.update_status("Snapshot scan queued.")

    def _start_scanning(self) -> None:
        if not self._ensure_config():
            return
        try:
            self._controller.start(self._config)
        except Exception as exc:
            QMessageBox.critical(self, "Error", str(exc))
            return
        self.dashboard_tab.update_status("Continuous scanning started.")

    def _stop_scanning(self) -> None:
        if self._controller:
            self._controller.stop()
            self.dashboard_tab.update_status("Scanning stopped.")

    @Slot(str, str, str)
    def _handle_rescan_request(self, event_id: str, sport_key: str, market_key: str) -> None:
        if not self._ensure_config():
            return
        assert self._controller and self._config
        try:
            result = self._controller.rescan_opportunity(
                self._config, event_id, sport_key, market_key
            )
        except Exception as exc:
            QMessageBox.critical(self, "Rescan failed", str(exc))
            return

        details = [f"Event: {result.event_name}", f"Market: {result.market_key}"]
        if result.commence_time:
            details.append(result.commence_time.strftime("Commence: %Y-%m-%d %H:%M"))
        if not result.within_window:
            details.append("Note: event is outside the configured scan window.")
        details.append(f"Quotes evaluated: {result.quotes_considered}")

        if result.status == "event_not_found":
            details.append("Event was not returned by the Odds API during rescan.")
            QMessageBox.information(self, "Rescan result", "\n".join(details))
            return

        if result.opportunity:
            edge_pct = float(result.opportunity.edge * Decimal(100))
            details.extend(
                [
                    f"Edge: {edge_pct:.2f}%",
                    f"Total stake: ${float(result.opportunity.total_stake):.2f}",
                    f"Payout: ${float(result.opportunity.payout):.2f}",
                ]
            )
            recommendation_text = ArbitrageTab._format_recommendations(
                result.opportunity.recommendations
            )
            message = "\n".join(details)
            if recommendation_text:
                message += "\n\nRecommendations:\n" + recommendation_text
            QMessageBox.information(self, "Opportunity confirmed", message)
            return

        status_map = {
            "no_quotes": "No quotes were available for the selected market.",
            "no_arbitrage": "The current odds no longer form an arbitrage opportunity.",
        }
        details.append(status_map.get(result.status, "No arbitrage opportunity detected."))
        QMessageBox.information(self, "Rescan result", "\n".join(details))


class DeepMarketExplorerDialog(QDialog):
    def __init__(
        self,
        client: OddsApiClient,
        sports: Sequence[SportInfo],
        existing: Optional[Dict[str, List[str]]] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Deep Market Explorer")
        self._client = client
        self._sports = list(sports)
        self._sport_map = {sport.key: sport for sport in self._sports}
        self._sport_market_cache: Dict[str, List[str]] = {}
        self.sport_overrides: Dict[str, List[str]] = {
            key: list(values) for key, values in (existing or {}).items()
        }
        self.global_markets: List[str] = sorted(
            {market for values in self.sport_overrides.values() for market in values}
        )
        self._all_markets: List[str] = []
        self._build_ui()
        if self._sports:
            self._load_markets_for_sport(self._sports[0].key)

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        form = QFormLayout()
        self.sport_combo = QComboBox()
        for sport in self._sports:
            self.sport_combo.addItem(f"{sport.title} ({sport.key})", userData=sport.key)
        form.addRow("Sport", self.sport_combo)

        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Filter deep markets")
        form.addRow("Filter", self.search_edit)

        self.use_all_checkbox = QCheckBox("Use all deep markets")
        form.addRow("", self.use_all_checkbox)

        layout.addLayout(form)

        self.market_list = QListWidget()
        self.market_list.setSelectionMode(QListWidget.MultiSelection)
        layout.addWidget(self.market_list)

        button_row = QHBoxLayout()
        self.refresh_button = QPushButton("Scan markets")
        self.select_all_button = QPushButton("Select all")
        self.clear_button = QPushButton("Clear")
        self.save_button = QPushButton("Save sport selection")
        self.done_button = QPushButton("Done")
        button_row.addWidget(self.refresh_button)
        button_row.addWidget(self.select_all_button)
        button_row.addWidget(self.clear_button)
        button_row.addStretch()
        button_row.addWidget(self.save_button)
        button_row.addWidget(self.done_button)
        layout.addLayout(button_row)

        self.status_label = QLabel("Ready")
        layout.addWidget(self.status_label)

        self.sport_combo.currentTextChanged.connect(self._on_sport_changed)
        self.refresh_button.clicked.connect(lambda: self._load_markets_for_sport(self._current_sport_key()))
        self.select_all_button.clicked.connect(self._select_all)
        self.clear_button.clicked.connect(self._clear_selection)
        self.save_button.clicked.connect(self._save_current_selection)
        self.done_button.clicked.connect(self._finish)
        self.search_edit.textChanged.connect(self._filter_markets)
        self.use_all_checkbox.stateChanged.connect(self._toggle_all_state)

    def _current_sport_key(self) -> str:
        return self.sport_combo.currentData() or ""

    def _on_sport_changed(self, _: str) -> None:
        self._load_markets_for_sport(self._current_sport_key())

    def _load_markets_for_sport(self, sport_key: str) -> None:
        if not sport_key:
            return
        self.status_label.setText("Scanning markets…")
        QApplication.processEvents()
        markets = self._sport_market_cache.get(sport_key, [])
        if not markets:
            try:
                response = self._client.list_markets(sport_key)
                markets = _extract_market_keys(response.data)
            except Exception as exc:
                self.status_label.setText(f"Falling back to catalogue ({exc})")
            if not markets:
                markets = get_deep_markets_for_sport(sport_key)
            self._sport_market_cache[sport_key] = list(markets)
        self.market_list.clear()
        if not markets:
            self._all_markets = []
            self.status_label.setText("No deep markets available for this sport.")
            return
        self._all_markets = sorted(dict.fromkeys(markets))
        for market in self._all_markets:
            item = QListWidgetItem(market)
            item.setSelected(False)
            self.market_list.addItem(item)

        saved = self.sport_overrides.get(sport_key, [])
        if saved and set(saved) >= set(self._all_markets):
            self.use_all_checkbox.setChecked(True)
        else:
            self.use_all_checkbox.setChecked(False)
            saved_set = set(saved)
            for index in range(self.market_list.count()):
                item = self.market_list.item(index)
                item.setSelected(item.text() in saved_set)
        self._filter_markets(self.search_edit.text())
        saved_msg = f"Saved {len(saved)}" if saved else "Unsaved"
        self.status_label.setText(f"Loaded {len(self._all_markets)} markets. {saved_msg} selection.")

    def _select_all(self) -> None:
        for index in range(self.market_list.count()):
            self.market_list.item(index).setSelected(True)

    def _clear_selection(self) -> None:
        self.market_list.clearSelection()
        self.use_all_checkbox.setChecked(False)

    def _save_current_selection(self, silent: bool = False) -> None:
        sport_key = self._current_sport_key()
        if not sport_key:
            return
        if self.use_all_checkbox.isChecked():
            markets = list(self._all_markets)
        else:
            markets = [item.text() for item in self.market_list.selectedItems()]
        markets = list(dict.fromkeys(markets))
        if markets:
            self.sport_overrides[sport_key] = markets
        elif sport_key in self.sport_overrides:
            del self.sport_overrides[sport_key]
        if not silent:
            self.status_label.setText(f"Saved {len(markets)} markets for {sport_key}.")
        self.global_markets = sorted(
            {market for values in self.sport_overrides.values() for market in values}
        )

    def _finish(self) -> None:
        self._save_current_selection(silent=True)
        self.accept()

    def _filter_markets(self, text: str) -> None:
        query = text.strip().casefold()
        for index in range(self.market_list.count()):
            item = self.market_list.item(index)
            item.setHidden(bool(query and query not in item.text().casefold()))

    def _toggle_all_state(self, state: int) -> None:
        disabled = state == Qt.Checked
        self.market_list.setEnabled(not disabled)
        self.select_all_button.setEnabled(not disabled)
        self.clear_button.setEnabled(not disabled)


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


def run_app() -> int:
    app = QApplication(sys.argv)
    database = Database(Path("arbisport.db"))
    window = MainWindow(database)
    window.resize(1200, 800)
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(run_app())
