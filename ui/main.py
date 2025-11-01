"""PySide6 user interface for ArbiSport."""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from functools import partial
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence

from PySide6.QtCore import (
    QDateTime,
    QRunnable,
    Qt,
    QThreadPool,
    Signal,
    Slot,
    QTimer,
    QObject,
)
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
    QInputDialog,
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
    clear_cache_requested = Signal()
    catalog_updated = Signal(object, object)

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

        profile_group = QGroupBox("Saved presets")
        profile_layout = QHBoxLayout(profile_group)
        self.profile_combo = QComboBox()
        self.profile_combo.setMinimumWidth(200)
        self.profile_combo.addItem("Select preset…", userData=None)
        self.load_profile_button = QPushButton("Load")
        self.save_profile_button = QPushButton("Save current…")
        self.delete_profile_button = QPushButton("Delete")
        profile_layout.addWidget(self.profile_combo, 1)
        profile_layout.addWidget(self.load_profile_button)
        profile_layout.addWidget(self.save_profile_button)
        profile_layout.addWidget(self.delete_profile_button)

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
        self.clear_deep_overrides_button = QPushButton("Clear sport overrides")
        deep_market_row.addWidget(self.deep_markets_edit)
        deep_market_row.addWidget(self.deep_market_browser)
        deep_market_row.addWidget(self.clear_deep_overrides_button)
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
        self.clear_cache_button = QPushButton("Clear cached events")

        button_layout = QHBoxLayout()
        button_layout.addWidget(self.test_button)
        button_layout.addWidget(self.apply_button)

        layout.addWidget(profile_group)
        layout.addWidget(form_group)
        layout.addLayout(button_layout)
        layout.addWidget(self.clear_cache_button, alignment=Qt.AlignLeft)
        layout.addStretch()

        self.profile_combo.currentIndexChanged.connect(self._update_profile_buttons)
        self.load_profile_button.clicked.connect(self._load_selected_profile)
        self.save_profile_button.clicked.connect(self._prompt_save_profile)
        self.delete_profile_button.clicked.connect(self._delete_selected_profile)
        self._update_profile_buttons()

        self.test_button.clicked.connect(self._on_test_api)
        self.apply_button.clicked.connect(self._on_apply)
        self.clear_cache_button.clicked.connect(self._on_clear_cache)
        self.window_preset_combo.currentTextChanged.connect(self._on_preset_changed)
        self.deep_market_browser.clicked.connect(self._open_deep_market_browser)
        self.clear_deep_overrides_button.clicked.connect(self._clear_deep_market_overrides)
        self.sports_browse_button.clicked.connect(self._open_sport_browser)
        self.bookmakers_browse_button.clicked.connect(self._open_bookmaker_browser)
        self._on_preset_changed(self.window_preset_combo.currentText())
        self._refresh_sport_summary()
        self._refresh_bookmaker_summary()
        self._refresh_deep_market_summary()
        self._reload_profiles()

    def _on_clear_cache(self) -> None:
        reply = QMessageBox.question(
            self,
            "Clear cached events",
            "Remove all stored events and quotes? This will not delete arbitrage history.",
        )
        if reply == QMessageBox.Yes:
            self.clear_cache_requested.emit()

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

    def _clear_deep_market_overrides(self) -> None:
        if not self._per_sport_deep_markets:
            QMessageBox.information(self, "No overrides", "There are no sport-specific deep market overrides to clear.")
            return
        reply = QMessageBox.question(
            self,
            "Clear overrides",
            "Remove all sport-specific deep market selections?",
        )
        if reply != QMessageBox.Yes:
            return
        self._per_sport_deep_markets.clear()
        self._refresh_deep_market_summary()

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

        self.catalog_updated.emit(self._available_sports, self._available_bookmakers)

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

        window_start = self._as_utc_datetime(self.window_start)
        window_end = self._as_utc_datetime(self.window_end)
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

    def _as_utc_datetime(self, widget: QDateTimeEdit) -> datetime:
        dt = widget.dateTime().toUTC().toPython()
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)

    def _collect_profile_payload(self) -> dict:
        window_start = self._as_utc_datetime(self.window_start)
        window_end = self._as_utc_datetime(self.window_end)
        return {
            "api_key": self.api_key_edit.text(),
            "regions": self._selected_items(self.region_box) or ["us"],
            "sports": list(self._selected_sports),
            "bookmakers": list(self._selected_bookmakers),
            "markets": self._selected_items(self.markets_box) or ["h2h"],
            "deep_markets": self.deep_markets_edit.text(),
            "per_sport_deep_markets": {
                key: list(values) for key, values in self._per_sport_deep_markets.items()
            },
            "window_start": window_start.isoformat(),
            "window_end": window_end.isoformat(),
            "window_preset": self.window_preset_combo.currentText(),
            "min_edge": self.edge_spin.value(),
            "bankroll": self.bankroll_spin.value(),
            "rounding": self.rounding_spin.value(),
            "max_per_book": self.max_per_book_spin.value(),
            "min_books": self.min_books_spin.value(),
            "scan_mode": self.scan_mode_combo.currentText(),
            "interval": self.interval_spin.value(),
            "burst_interval": self.burst_interval_spin.value(),
            "burst_window": self.burst_window_spin.value(),
        }

    def _prompt_save_profile(self) -> None:
        name, ok = QInputDialog.getText(self, "Save preset", "Preset name:")
        if not ok:
            return
        preset_name = name.strip()
        if not preset_name:
            QMessageBox.warning(self, "Invalid name", "Preset name cannot be empty.")
            return
        payload = self._collect_profile_payload()
        self._db.save_profile(preset_name, payload)
        self._reload_profiles(select=preset_name)

    def _load_selected_profile(self) -> None:
        name = self.profile_combo.currentData()
        if not name:
            QMessageBox.information(self, "No preset", "Select a preset to load.")
            return
        profile = self._db.get_profile(name)
        if not profile:
            QMessageBox.warning(self, "Missing preset", "The selected preset could not be loaded.")
            self._reload_profiles()
            return
        self._apply_profile(profile)
        QMessageBox.information(self, "Preset loaded", f"Applied preset '{name}'.")

    def _delete_selected_profile(self) -> None:
        name = self.profile_combo.currentData()
        if not name:
            QMessageBox.information(self, "No preset", "Select a preset to delete.")
            return
        if QMessageBox.question(self, "Delete preset", f"Remove preset '{name}'?") != QMessageBox.Yes:
            return
        self._db.delete_profile(name)
        self._reload_profiles()

    def _reload_profiles(self, select: Optional[str] = None) -> None:
        profiles = self._db.list_profiles()
        current = select or self.profile_combo.currentData()
        self.profile_combo.blockSignals(True)
        self.profile_combo.clear()
        self.profile_combo.addItem("Select preset…", userData=None)
        for name in profiles:
            self.profile_combo.addItem(name, userData=name)
        if current and current in profiles:
            index = self.profile_combo.findData(current)
            if index >= 0:
                self.profile_combo.setCurrentIndex(index)
        else:
            self.profile_combo.setCurrentIndex(0)
        self.profile_combo.blockSignals(False)
        self._update_profile_buttons()

    def _update_profile_buttons(self) -> None:
        has_selection = bool(self.profile_combo.currentData())
        self.load_profile_button.setEnabled(has_selection)
        self.delete_profile_button.setEnabled(has_selection)

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

    def _apply_profile(self, profile: dict) -> None:
        api_key = profile.get("api_key", "")
        self.api_key_edit.setText(api_key)

        regions = profile.get("regions") or ["us"]
        for index in range(self.region_box.count()):
            item = self.region_box.item(index)
            item.setSelected(item.text() in regions)

        self._set_selected_sports(profile.get("sports") or [])
        self._set_selected_bookmakers(profile.get("bookmakers") or [])

        markets = profile.get("markets") or []
        selected_markets = set(markets) if markets else {item.text() for item in self._iter_items(self.markets_box)}
        for item in self._iter_items(self.markets_box):
            item.setSelected(item.text() in selected_markets)

        self.deep_markets_edit.setText(profile.get("deep_markets", ""))
        self._per_sport_deep_markets = {
            key: list(values) for key, values in (profile.get("per_sport_deep_markets") or {}).items()
        }
        self._refresh_deep_market_summary()

        start = _parse_iso_datetime(profile.get("window_start"))
        end = _parse_iso_datetime(profile.get("window_end"))
        preset = profile.get("window_preset")
        if preset in self._window_presets:
            self.window_preset_combo.setCurrentText(preset)
        else:
            self.window_preset_combo.setCurrentText("Custom range")
            self.window_start.setEnabled(True)
            self.window_end.setEnabled(True)
        if start:
            self.window_start.setDateTime(QDateTime(start).toLocalTime())
        if end:
            self.window_end.setDateTime(QDateTime(end).toLocalTime())

        self.edge_spin.setValue(float(profile.get("min_edge", self.edge_spin.value())))
        self.bankroll_spin.setValue(float(profile.get("bankroll", self.bankroll_spin.value())))
        self.rounding_spin.setValue(float(profile.get("rounding", self.rounding_spin.value())))
        self.max_per_book_spin.setValue(float(profile.get("max_per_book", self.max_per_book_spin.value())))
        self.min_books_spin.setValue(int(profile.get("min_books", self.min_books_spin.value())))

        scan_mode = profile.get("scan_mode")
        if scan_mode in [mode.value for mode in ScanMode]:
            self.scan_mode_combo.setCurrentText(scan_mode)

        self.interval_spin.setValue(int(profile.get("interval", self.interval_spin.value())))
        self.burst_interval_spin.setValue(int(profile.get("burst_interval", self.burst_interval_spin.value())))
        self.burst_window_spin.setValue(int(profile.get("burst_window", self.burst_window_spin.value())))

    def _set_selected_sports(self, sports: List[str]) -> None:
        available = {sport.key for sport in self._available_sports}
        filtered = [sport for sport in sports if sport in available]
        if not filtered:
            filtered = list(available)
        self._selected_sports = filtered
        self._refresh_sport_summary()

    def _set_selected_bookmakers(self, bookmakers: List[str]) -> None:
        available = {book.key for book in self._available_bookmakers}
        filtered = [book for book in bookmakers if book in available]
        if not filtered:
            filtered = list(available)
        self._selected_bookmakers = filtered
        self._refresh_bookmaker_summary()

    @staticmethod
    def _iter_items(widget: QListWidget) -> Iterable[QListWidgetItem]:
        for index in range(widget.count()):
            yield widget.item(index)

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
    delete_requested = Signal(int)

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
            actions_widget = self._make_actions_widget(record)
            self.table.setCellWidget(row_idx, 7, actions_widget)
        self.table.resizeRowsToContents()

    def _make_actions_widget(self, record: ArbitrageRecord) -> QWidget:
        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        rescan_button = QPushButton("Rescan")
        if record.sport_key:
            callback = partial(
                self.rescan_requested.emit,
                record.event_id,
                record.sport_key,
                record.market_key,
            )
            rescan_button.clicked.connect(callback)
        else:
            rescan_button.setEnabled(False)
            rescan_button.setToolTip("Sport information unavailable for this record.")
        delete_button = QPushButton("Delete")
        delete_button.clicked.connect(partial(self.delete_requested.emit, record.id))
        layout.addWidget(rescan_button)
        layout.addWidget(delete_button)
        layout.addStretch()
        return container

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


class EventSearchSignals(QObject):
    finished = Signal(object, object, object, object)


class EventSearchRunnable(QRunnable):
    def __init__(
        self,
        client: OddsApiClient,
        sports: Sequence[str],
        regions: Sequence[str],
        bookmakers: Sequence[str],
        window_start: datetime,
        window_end: datetime,
        include_live: bool,
        sport_lookup: Dict[str, str],
    ) -> None:
        super().__init__()
        self._client = client
        self._sports = list(dict.fromkeys(sports))
        self._regions = list(dict.fromkeys(regions)) or ["us"]
        self._bookmakers = list(dict.fromkeys(bookmakers))
        self._window_start = window_start
        self._window_end = window_end
        self._include_live = include_live
        self._sport_lookup = dict(sport_lookup)
        self._markets = ["h2h"]
        self.signals = EventSearchSignals()

    def run(self) -> None:  # pragma: no cover - executed in background thread
        results: List[dict] = []
        errors: List[str] = []
        remaining: Optional[int] = None
        reset: Optional[datetime] = None
        now = datetime.now(timezone.utc)
        seen_ids: set[str] = set()

        for sport in self._sports:
            try:
                response = self._client.get_odds(
                    sport_key=sport,
                    regions=self._regions,
                    bookmakers=self._bookmakers,
                    markets=self._markets,
                )
            except Exception as exc:  # pragma: no cover - API failures routed to UI
                errors.append(f"{sport}: {exc}")
                continue

            if response.remaining_requests is not None:
                remaining = response.remaining_requests
            if response.reset_time is not None:
                reset = response.reset_time

            for event in response.data or []:
                if not isinstance(event, dict):
                    continue
                event_id = event.get("id")
                if event_id and event_id in seen_ids:
                    continue
                commence = _parse_commence_time(event.get("commence_time"))
                if not commence:
                    continue
                commence_utc = _ensure_utc(commence)
                if commence_utc > self._window_end:
                    continue
                if commence_utc < self._window_start:
                    if not (self._include_live and commence_utc <= now <= self._window_end):
                        continue
                if event_id:
                    seen_ids.add(event_id)
                bookmakers = _extract_bookmakers(event)
                results.append(
                    {
                        "sport_key": sport,
                        "sport_title": self._sport_lookup.get(sport, sport),
                        "event_id": event_id or f"{sport}-{len(results)}",
                        "event_name": _format_event_name(event),
                        "commence": commence_utc,
                        "bookmakers": bookmakers,
                        "is_live": commence_utc <= now,
                    }
                )

        results.sort(key=lambda entry: entry["commence"])
        self.signals.finished.emit(results, errors, remaining, reset)


class EventSearchTab(QWidget):
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._thread_pool = QThreadPool.globalInstance()
        self._client: Optional[OddsApiClient] = None
        self._regions: List[str] = ["us"]
        self._bookmakers: List[str] = []
        self._available_sports: List[SportInfo] = list(ALL_SPORTS)
        self._sport_lookup: Dict[str, str] = {sport.key: sport.title for sport in self._available_sports}
        self._selected_sports: List[str] = [sport.key for sport in self._available_sports]
        self._results: List[dict] = []
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        description = QLabel("Search across sports for live and upcoming events within a custom window.")
        description.setWordWrap(True)
        layout.addWidget(description)

        form = QFormLayout()

        sports_row = QHBoxLayout()
        self.sport_summary = QLabel()
        self.sport_summary.setWordWrap(True)
        self.sport_summary.setMinimumWidth(300)
        self.sport_browse_button = QPushButton("Browse…")
        sports_row.addWidget(self.sport_summary, 1)
        sports_row.addWidget(self.sport_browse_button)
        sports_widget = QWidget()
        sports_widget.setLayout(sports_row)
        form.addRow("Sports", sports_widget)

        self.window_start_edit = QDateTimeEdit(QDateTime.currentDateTime())
        self.window_start_edit.setCalendarPopup(True)
        self.window_start_edit.setDisplayFormat("yyyy-MM-dd HH:mm")
        form.addRow("Window start", self.window_start_edit)

        self.hours_ahead_spin = QSpinBox()
        self.hours_ahead_spin.setRange(1, 72)
        self.hours_ahead_spin.setValue(6)
        form.addRow("Hours ahead", self.hours_ahead_spin)

        self.include_live_checkbox = QCheckBox("Include events that have already started")
        form.addRow("", self.include_live_checkbox)

        self.filter_edit = QLineEdit()
        self.filter_edit.setPlaceholderText("Filter results…")
        form.addRow("Filter", self.filter_edit)

        layout.addLayout(form)

        button_row = QHBoxLayout()
        button_row.addStretch()
        self.search_button = QPushButton("Search")
        self.clear_button = QPushButton("Clear results")
        self.clear_button.setEnabled(False)
        button_row.addWidget(self.search_button)
        button_row.addWidget(self.clear_button)
        layout.addLayout(button_row)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Sport", "Event", "Start (local)", "Status", "Bookmakers"])
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        layout.addWidget(self.table)

        self.status_label = QLabel("Enter an API key and apply settings to search.")
        layout.addWidget(self.status_label)

        self.sport_browse_button.clicked.connect(self._open_sport_browser)
        self.search_button.clicked.connect(self._run_search)
        self.clear_button.clicked.connect(self._clear_results)
        self.filter_edit.textChanged.connect(self._apply_filter)

        self._refresh_sport_summary()

    def update_catalog(self, sports: Sequence[SportInfo]) -> None:
        self._available_sports = list(sports) if sports else list(ALL_SPORTS)
        self._sport_lookup = {sport.key: sport.title for sport in self._available_sports}
        available_keys = [sport.key for sport in self._available_sports]
        self._selected_sports = [key for key in self._selected_sports if key in available_keys]
        if not self._selected_sports:
            self._selected_sports = list(available_keys)
        self._refresh_sport_summary()

    def apply_config(self, config: ScanConfig, client: OddsApiClient) -> None:
        self._client = client
        self._regions = list(config.regions)
        self._bookmakers = list(config.bookmakers)
        if config.sports:
            self._selected_sports = list(dict.fromkeys(config.sports))
        self._refresh_sport_summary()
        self.status_label.setText("Ready to search.")

    def _open_sport_browser(self) -> None:
        items = [
            SelectionItem(key=sport.key, label=f"{sport.title} ({sport.group})", description=sport.key)
            for sport in self._available_sports
        ]
        dialog = MultiSelectDialog("Select sports", items, self._selected_sports, self)
        if dialog.exec() == QDialog.Accepted:
            self._selected_sports = dialog.selected_keys or [sport.key for sport in self._available_sports]
            self._refresh_sport_summary()

    def _refresh_sport_summary(self) -> None:
        label_map = {sport.key: f"{sport.title} ({sport.group})" for sport in self._available_sports}
        summary = self._format_selection_summary(self._selected_sports, label_map, len(self._available_sports))
        self.sport_summary.setText(summary)

    def _run_search(self) -> None:
        if not self._client:
            QMessageBox.warning(self, "Configuration required", "Apply settings with a valid API key before searching.")
            return
        sports = self._selected_sports or [sport.key for sport in self._available_sports]
        if not sports:
            QMessageBox.warning(self, "No sports", "Select at least one sport to search.")
            return

        start_dt = self.window_start_edit.dateTime().toUTC().toPyDateTime().replace(tzinfo=timezone.utc)
        window_end = start_dt + timedelta(hours=self.hours_ahead_spin.value())
        include_live = self.include_live_checkbox.isChecked()

        runnable = EventSearchRunnable(
            self._client,
            sports,
            self._regions,
            self._bookmakers,
            start_dt,
            window_end,
            include_live,
            self._sport_lookup,
        )
        runnable.signals.finished.connect(self._on_search_finished)
        self.status_label.setText("Searching…")
        self.search_button.setEnabled(False)
        self.clear_button.setEnabled(False)
        self._thread_pool.start(runnable)

    def _on_search_finished(
        self,
        results: List[dict],
        errors: List[str],
        remaining: Optional[int],
        reset: Optional[datetime],
    ) -> None:
        self.search_button.setEnabled(True)
        self._results = results or []
        self.clear_button.setEnabled(bool(self._results))
        self._apply_filter()

        parts = [f"Found {len(self._results)} events."]
        if remaining is not None:
            parts.append(f"API credits remaining: {remaining}")
        if reset is not None:
            parts.append(f"Reset at {reset.strftime('%Y-%m-%d %H:%M:%S')} UTC")
        if errors:
            preview = "; ".join(errors[:3])
            if len(errors) > 3:
                preview += f" … (+{len(errors) - 3} more)"
            parts.append(f"Errors: {preview}")
        self.status_label.setText(" ".join(parts))

    def _apply_filter(self) -> None:
        query = self.filter_edit.text().strip().casefold()
        if not query:
            filtered = list(self._results)
        else:
            filtered = []
            for entry in self._results:
                haystack = " ".join(
                    [
                        entry.get("sport_title", ""),
                        entry.get("event_name", ""),
                        " ".join(entry.get("bookmakers", [])),
                    ]
                ).casefold()
                if query in haystack:
                    filtered.append(entry)
        self._populate_table(filtered)

    def _populate_table(self, entries: Sequence[dict]) -> None:
        self.table.setRowCount(len(entries))
        for row, entry in enumerate(entries):
            self.table.setItem(row, 0, QTableWidgetItem(entry.get("sport_title", entry.get("sport_key", ""))))
            self.table.setItem(row, 1, QTableWidgetItem(entry.get("event_name", "")))
            commence: Optional[datetime] = entry.get("commence")
            self.table.setItem(row, 2, QTableWidgetItem(_format_local_time(commence)))
            status = "Live" if entry.get("is_live") else "Upcoming"
            self.table.setItem(row, 3, QTableWidgetItem(status))
            self.table.setItem(row, 4, QTableWidgetItem(_format_bookmakers(entry.get("bookmakers", []))))
        if entries:
            self.table.scrollToTop()

    def _clear_results(self) -> None:
        self._results = []
        self.table.setRowCount(0)
        self.filter_edit.clear()
        self.clear_button.setEnabled(False)
        self.status_label.setText("Results cleared.")

    @staticmethod
    def _format_selection_summary(
        selected_keys: Sequence[str],
        label_map: Dict[str, str],
        total_available: int,
    ) -> str:
        if not selected_keys or set(selected_keys) == set(label_map.keys()):
            return f"All ({total_available})"
        names = [label_map.get(key, "") for key in selected_keys if label_map.get(key, "")]
        if not names:
            return "None selected"
        if len(names) > 5:
            return ", ".join(names[:5]) + f" … (+{len(names) - 5})"
        return ", ".join(names)


def _parse_commence_time(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        if value.endswith("Z"):
            value = value.replace("Z", "+00:00")
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _format_event_name(event: dict) -> str:
    home = event.get("home_team") if isinstance(event, dict) else None
    away = event.get("away_team") if isinstance(event, dict) else None
    if isinstance(home, str) and isinstance(away, str) and home and away:
        return f"{away} @ {home}"
    name = event.get("sport_title") if isinstance(event, dict) else None
    if isinstance(name, str) and name:
        return name
    event_id = event.get("id") if isinstance(event, dict) else None
    return event_id or "Unknown event"


def _extract_bookmakers(event: dict) -> List[str]:
    bookmakers: List[str] = []
    raw = event.get("bookmakers") if isinstance(event, dict) else None
    if isinstance(raw, list):
        for entry in raw:
            if not isinstance(entry, dict):
                continue
            title = entry.get("title") or entry.get("key")
            if not title:
                continue
            bookmakers.append(str(title))
    return list(dict.fromkeys(bookmakers))


def _format_local_time(value: Optional[datetime]) -> str:
    if not value:
        return "—"
    local = value.astimezone()
    return local.strftime("%Y-%m-%d %H:%M")


def _format_bookmakers(bookmakers: Sequence[str]) -> str:
    unique = [book for book in dict.fromkeys(bookmakers) if book]
    if not unique:
        return "—"
    if len(unique) <= 3:
        return ", ".join(unique)
    return ", ".join(unique[:3]) + f" … (+{len(unique) - 3})"


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
        self._table_timer = QTimer(self)
        self._table_timer.setInterval(1000)
        self._table_timer.timeout.connect(self._render_table_if_needed)
        self._table_timer.start()
        self._table_dirty = False
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
        try:
            records = self._db.fetch_logs(since_id=self._last_log_id)
        except Exception as exc:  # pragma: no cover - defensive UI guard
            timestamp = datetime.utcnow().isoformat()
            self.raw_view.append(f"[{timestamp}] ERROR: Log fetch failed ({exc})")
            return
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
        self._table_dirty = True
        if self.isVisible():
            self._render_table_if_needed()

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
        self._table_dirty = False

    def _render_table_if_needed(self) -> None:
        if not self._table_dirty:
            return
        if not self.isVisible():
            return
        if self.tabs.currentWidget() is not self.tabs.widget(0):
            return
        self._render_table()

    def showEvent(self, event) -> None:  # pragma: no cover - Qt runtime hook
        super().showEvent(event)
        self._render_table_if_needed()

    @staticmethod
    def _format_context(context: Optional[dict]) -> str:
        if not context:
            return ""
        if isinstance(context, dict):
            parts = []
            for key in sorted(context.keys()):
                value = context[key]
                parts.append(f"{key}={_stringify(value)}")
            return ", ".join(parts)
        return _stringify(context)


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
            f"Opportunities tested: {summary.opportunities_tested}",
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
        self.events_tab = EventSearchTab()
        self.logs_tab = LogsTab(database)

        self.tabs.addTab(self.settings_tab, "Settings")
        self.tabs.addTab(self.dashboard_tab, "Dashboard")
        self.tabs.addTab(self.arbitrage_tab, "Arbitrage")
        self.tabs.addTab(self.events_tab, "Events")
        self.tabs.addTab(self.logs_tab, "Logs")
        self.setCentralWidget(self.tabs)

        self.settings_tab.config_applied.connect(self._on_config_applied)
        self.settings_tab.clear_cache_requested.connect(self._clear_event_cache)
        self.settings_tab.catalog_updated.connect(self._on_catalog_updated)
        self.arbitrage_tab.rescan_requested.connect(self._handle_rescan_request)
        self.arbitrage_tab.delete_requested.connect(self._handle_delete_request)

        self.events_tab.update_catalog(list(ALL_SPORTS))

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
        if self._controller:
            try:
                self._controller.stop()
            except Exception:
                pass
        self._config = config
        self._client = client
        self._controller = ScanController(client, self._db, self._name_normalizer)
        self.dashboard_tab.update_status("Configuration applied. Ready to scan.")
        self.events_tab.apply_config(config, client)

    @Slot(object, object)
    def _on_catalog_updated(self, sports: object, _: object) -> None:
        if isinstance(sports, list):
            self.events_tab.update_catalog(sports)

    def _clear_event_cache(self) -> None:
        if QMessageBox.question(
            self,
            "Clear cached events",
            "Are you sure you want to delete all stored events and quotes?",
        ) != QMessageBox.Yes:
            return
        self._db.clear_event_cache()
        if self._controller:
            self._controller.reset_runtime_state()
        self.dashboard_tab.refresh()
        QMessageBox.information(self, "Cache cleared", "Stored events removed.")

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
            "no_bookmakers": "Configured bookmakers were rejected by the Odds API.",
        }
        details.append(status_map.get(result.status, "No arbitrage opportunity detected."))
        QMessageBox.information(self, "Rescan result", "\n".join(details))

    @Slot(int)
    def _handle_delete_request(self, record_id: int) -> None:
        if QMessageBox.question(
            self,
            "Delete opportunity",
            "Remove this arbitrage record from history?",
        ) != QMessageBox.Yes:
            return
        self._db.delete_arbitrage(record_id)
        self.arbitrage_tab.refresh()
        self.dashboard_tab.refresh()
        QMessageBox.information(self, "Deleted", "Arbitrage record removed.")

    def closeEvent(self, event) -> None:  # pragma: no cover - UI shutdown handling
        try:
            self._stop_scanning()
        finally:
            super().closeEvent(event)


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
        self.remove_button = QPushButton("Remove override")
        self.save_button = QPushButton("Save sport selection")
        self.done_button = QPushButton("Done")
        button_row.addWidget(self.refresh_button)
        button_row.addWidget(self.select_all_button)
        button_row.addWidget(self.clear_button)
        button_row.addStretch()
        button_row.addWidget(self.remove_button)
        button_row.addWidget(self.save_button)
        button_row.addWidget(self.done_button)
        layout.addLayout(button_row)

        self.status_label = QLabel("Ready")
        layout.addWidget(self.status_label)

        self.sport_combo.currentTextChanged.connect(self._on_sport_changed)
        self.refresh_button.clicked.connect(lambda: self._load_markets_for_sport(self._current_sport_key()))
        self.select_all_button.clicked.connect(self._select_all)
        self.clear_button.clicked.connect(self._clear_selection)
        self.remove_button.clicked.connect(self._remove_current_override)
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

    def _remove_current_override(self) -> None:
        sport_key = self._current_sport_key()
        if not sport_key:
            return
        if sport_key in self.sport_overrides:
            del self.sport_overrides[sport_key]
            self.status_label.setText(f"Removed saved markets for {sport_key}.")
        self.use_all_checkbox.setChecked(False)
        for index in range(self.market_list.count()):
            self.market_list.item(index).setSelected(False)
        self.global_markets = sorted(
            {market for values in self.sport_overrides.values() for market in values}
        )

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


def _parse_iso_datetime(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _stringify(value: object) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, (list, dict)):
        try:
            return json.dumps(value, default=_json_default)
        except TypeError:
            return str(value)
    return str(value)


def _json_default(value: object) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Decimal):
        return format(value, "f")
    return str(value)


def run_app() -> int:
    app = QApplication(sys.argv)
    database = Database(Path("arbisport.db"))
    window = MainWindow(database)
    window.resize(1200, 800)
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(run_app())
