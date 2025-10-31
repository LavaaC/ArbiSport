from decimal import Decimal
from datetime import datetime, timezone

from persistence.database import Database


def test_log_serialization_handles_decimal(tmp_path):
    db = Database(tmp_path / "test.db")
    db.log("info", "decimal test", {"value": Decimal("1.23"), "time": datetime.now(timezone.utc)})

    records = db.fetch_logs()
    assert records
    context = records[-1].context
    assert isinstance(context, dict)
    assert context["value"] == 1.23


def test_profile_round_trip(tmp_path):
    db = Database(tmp_path / "profiles.db")
    payload = {
        "api_key": "abc",
        "regions": ["us", "uk"],
        "sports": ["soccer_epl"],
        "window_start": datetime(2025, 1, 1, tzinfo=timezone.utc).isoformat(),
    }
    db.save_profile("Test preset", payload)

    names = db.list_profiles()
    assert "Test preset" in names

    restored = db.get_profile("Test preset")
    assert restored is not None
    assert restored["regions"] == payload["regions"]
    assert restored["sports"] == payload["sports"]
