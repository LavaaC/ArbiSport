"""PySide6 user interface for ArbiSport."""

from __future__ import annotations

import sys
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import List, Optional

from PySide6.QtCore import QDateTime, QRunnable, Qt, QThreadPool, Signal, Slot, QTimer
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDateTimeEdit,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
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
from odds_client.client import OddsApiClient
from persistence.database import Database


class SnapshotRunnable(QRunnable):
    def __init__(self, controller: ScanController, config: ScanConfig) -> None:
        super().__init__()
        self._controller = controller
        self._config = config

    def run(self) -> None:  # pragma: no cover - executed in Qt thread pool
        self._controller.run_snapshot(self._config)


class SettingsTab(QWidget):
    config_applied = Signal(ScanConfig, OddsApiClient)

    def __init__(self, database: Database, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._db = database
        self._thread_pool = QThreadPool.globalInstance()
        self._client: Optional[OddsApiClient] = None
        self._sports: List[str] = []
        self._bookmakers: List[str] = []
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

        self.sports_box = QListWidget()
        self.sports_box.setSelectionMode(QListWidget.MultiSelection)
        form_layout.addRow("Sports", self.sports_box)

        self.books_box = QListWidget()
        self.books_box.setSelectionMode(QListWidget.MultiSelection)
        form_layout.addRow("Bookmakers", self.books_box)

        self.markets_box = QListWidget()
        self.markets_box.setSelectionMode(QListWidget.MultiSelection)
        for market in self._markets:
            item = QListWidgetItem(market)
            item.setSelected(True)
            self.markets_box.addItem(item)
        form_layout.addRow("Markets", self.markets_box)

        self.deep_markets_edit = QLineEdit()
        self.deep_markets_edit.setPlaceholderText("Comma-separated deep markets (e.g., correct_score)")
        form_layout.addRow("Deep markets", self.deep_markets_edit)

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
        self._on_preset_changed(self.window_preset_combo.currentText())

    def _selected_items(self, widget: QListWidget) -> List[str]:
        return [item.text() for item in widget.selectedItems()]

    def _on_test_api(self) -> None:
        api_key = self.api_key_edit.text().strip()
        if not api_key:
            QMessageBox.warning(self, "Missing key", "Please enter an API key first.")
            return
        try:
            client = OddsApiClient(api_key)
            regions = self._selected_items(self.region_box)
            response = client.list_sports(regions=regions)
            sports = [sport.get("key") for sport in response.data if sport.get("key")]
        except Exception as exc:
            QMessageBox.critical(self, "API error", f"Failed to validate key: {exc}")
            return

        self._client = client
        self._sports = sports
        self.sports_box.clear()
        for sport in sports:
            item = QListWidgetItem(sport)
            self.sports_box.addItem(item)

        bookmakers = set()
        for sample_sport in sports[:3]:
            try:
                odds_response = client.get_odds(
                    sport_key=sample_sport,
                    regions=regions or ["us"],
                    bookmakers=[],
                    markets=["h2h"],
                )
            except Exception:
                continue
            for event in odds_response.data:
                for bookmaker in event.get("bookmakers", []):
                    if bookmaker.get("key"):
                        bookmakers.add(bookmaker["key"])
            if bookmakers:
                break

        self.books_box.clear()
        for book in sorted(bookmakers):
            item = QListWidgetItem(book)
            item.setSelected(True)
            self.books_box.addItem(item)

        QMessageBox.information(self, "Success", f"API key validated. {len(sports)} sports available.")

    def _on_apply(self) -> None:
        api_key = self.api_key_edit.text().strip()
        if not api_key:
            QMessageBox.warning(self, "Missing key", "Enter an API key before applying settings.")
            return
        client = self._client or OddsApiClient(api_key)

        sports = self._selected_items(self.sports_box) or self._sports
        regions = self._selected_items(self.region_box) or ["us"]
        bookmakers = self._selected_items(self.books_box)
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

        self.config_applied.emit(config, client)

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
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Timestamp", "Event", "Market", "Edge %", "Stake plan"])
        layout.addWidget(self.table)

        self.export_button = QPushButton("Export CSV")
        self.export_button.clicked.connect(self._export_csv)
        layout.addWidget(self.export_button, alignment=Qt.AlignRight)

    def refresh(self) -> None:
        records = list(self._db.history(limit=100))
        self.table.setRowCount(len(records))
        for row_idx, record in enumerate(records):
            self.table.setItem(row_idx, 0, QTableWidgetItem(record.created_at.isoformat()))
            self.table.setItem(row_idx, 1, QTableWidgetItem(record.event_id))
            self.table.setItem(row_idx, 2, QTableWidgetItem(record.market_key))
            self.table.setItem(row_idx, 3, QTableWidgetItem(f"{record.edge * 100:.2f}"))
            self.table.setItem(row_idx, 4, QTableWidgetItem(str(record.stake_plan)))

    def _export_csv(self) -> None:
        path = self._db.export_history_csv(Path("arb_history.csv"))
        QMessageBox.information(self, "Export complete", f"Saved history to {path}")


class LogsTab(QWidget):
    def __init__(self, database: Database, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._db = database
        self._build_ui()
        self._last_log_id = 0
        self._timer = QTimer(self)
        self._timer.setInterval(3000)
        self._timer.timeout.connect(self._poll_logs)
        self._timer.start()
        self._poll_logs()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        layout.addWidget(self.log_view)

    def append_log(self, level: str, message: str) -> None:
        timestamp = datetime.utcnow().isoformat()
        self.log_view.append(f"[{timestamp}] {level.upper()}: {message}")

    def _poll_logs(self) -> None:
        records = self._db.fetch_logs(since_id=self._last_log_id)
        for record in records:
            context = f" {record.context}" if record.context else ""
            self.log_view.append(
                f"[{record.created_at.isoformat()}] {record.level.upper()}: {record.message}{context}"
            )
            self._last_log_id = record.id


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


def run_app() -> int:
    app = QApplication(sys.argv)
    database = Database(Path("arbisport.db"))
    window = MainWindow(database)
    window.resize(1200, 800)
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(run_app())
