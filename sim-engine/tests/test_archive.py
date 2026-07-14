import json
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "engine"))

from archive import archive_day


def sample_state(*, events=None):
    return {
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
        "events_today": [] if events is None else events,
    }


class ArchiveTests(unittest.TestCase):
    def test_archive_writes_json_and_sqlite_atomically(self):
        state = sample_state(
            events=[
                {
                    "type": "weather",
                    "severity": "info",
                    "text": "A calm day across the islands",
                }
            ]
        )
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

    def test_json_failure_preserves_existing_targets_and_cleans_temp(self):
        state = sample_state()
        state["not_json_serializable"] = object()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            archive_dir = root / "archive"
            archive_dir.mkdir()
            state_path = root / "state.json"
            snapshot_path = archive_dir / "2026-08-12.json"
            original_state = b"existing running state\n"
            original_snapshot = b"existing daily snapshot\n"
            state_path.write_bytes(original_state)
            snapshot_path.write_bytes(original_snapshot)

            with self.assertRaises(TypeError):
                archive_day(
                    state,
                    state_path=state_path,
                    archive_dir=archive_dir,
                    db_path=root / "events.db",
                )

            self.assertEqual(state_path.read_bytes(), original_state)
            self.assertEqual(snapshot_path.read_bytes(), original_snapshot)
            self.assertFalse(list(root.rglob("*.tmp")))

    def test_sqlite_failure_rolls_back_summary_and_all_events(self):
        state = sample_state(
            events=[
                {
                    "type": "weather",
                    "severity": "info",
                    "text": "inserted before failure",
                },
                {
                    "type": "weather",
                    "severity": "warning",
                    "text": "FORCE_ROLLBACK",
                },
            ]
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_path = root / "state.json"
            archive_dir = root / "archive"
            db_path = root / "events.db"
            archive_day(
                sample_state(),
                state_path=state_path,
                archive_dir=archive_dir,
                db_path=db_path,
            )
            with closing(sqlite3.connect(db_path)) as connection, connection:
                connection.execute("DELETE FROM daily_summary")
                connection.execute("DELETE FROM events")
                connection.execute("""
                    CREATE TRIGGER abort_later_event
                    BEFORE INSERT ON events
                    WHEN NEW.headline = 'FORCE_ROLLBACK'
                    BEGIN
                        SELECT RAISE(ABORT, 'forced event failure');
                    END
                """)

            with self.assertRaisesRegex(
                sqlite3.IntegrityError, "forced event failure"
            ):
                archive_day(
                    state,
                    state_path=state_path,
                    archive_dir=archive_dir,
                    db_path=db_path,
                )

            with closing(sqlite3.connect(db_path)) as connection:
                summary_count = connection.execute(
                    "SELECT COUNT(*) FROM daily_summary"
                ).fetchone()[0]
                event_count = connection.execute(
                    "SELECT COUNT(*) FROM events"
                ).fetchone()[0]
            self.assertEqual(summary_count, 0)
            self.assertEqual(event_count, 0)

            renamed_path = root / "events-renamed.db"
            db_path.rename(renamed_path)
            renamed_path.rename(db_path)


if __name__ == "__main__":
    unittest.main()
