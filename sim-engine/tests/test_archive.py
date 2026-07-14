import json
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "engine"))

from archive import archive_day


class ArchiveTests(unittest.TestCase):
    def test_archive_writes_json_and_sqlite_atomically(self):
        state = {
            "schema_version": 2,
            "date": "2026-08-12",
            "weather": {
                "condition": "晴",
                "temp_high": 28,
                "temp_low": 21,
                "rainfall_mm": 0.0,
            },
            "economy": {
                "inflation_pct": 2.4,
                "unemployment_pct": 5.8,
                "exchange_rate_mvl_per_usd": 2.18,
                "fuel_95_price_mvl": 2.85,
            },
            "deaths_today": {"total": 0},
            "events_today": [
                {
                    "type": "weather",
                    "severity": "info",
                    "text": "A calm day across the islands",
                }
            ],
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            archive_day(
                state,
                state_path=root / "state.json",
                archive_dir=root / "archive",
                db_path=root / "events.db",
            )

            loaded = json.loads(
                (root / "state.json").read_text(encoding="utf-8")
            )
            snapshot = json.loads(
                (root / "archive" / "2026-08-12.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(loaded, state)
            self.assertEqual(snapshot, state)
            self.assertFalse(list(root.rglob("*.tmp")))
            with closing(sqlite3.connect(root / "events.db")) as conn:
                summary_count = conn.execute(
                    "SELECT COUNT(*) FROM daily_summary"
                ).fetchone()[0]
                event_count = conn.execute(
                    "SELECT COUNT(*) FROM events"
                ).fetchone()[0]
            self.assertEqual(summary_count, 1)
            self.assertEqual(event_count, 1)


if __name__ == "__main__":
    unittest.main()
