"""Daily snapshot archiver: atomic JSON snapshots and SQLite event index."""

import json
import os
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path


def _ensure_table(cursor: sqlite3.Cursor) -> None:
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            type TEXT NOT NULL,
            severity TEXT DEFAULT 'info',
            location TEXT,
            people TEXT,
            headline TEXT NOT NULL,
            article TEXT,
            tags TEXT
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS daily_summary (
            date TEXT PRIMARY KEY,
            weather_condition TEXT,
            temp_high INTEGER,
            temp_low INTEGER,
            rainfall_mm REAL,
            inflation_pct REAL,
            unemployment_pct REAL,
            exchange_rate REAL,
            fuel_95_price REAL,
            deaths_total INTEGER,
            deaths_traffic INTEGER,
            deaths_drowning INTEGER,
            deaths_suicide INTEGER,
            deaths_murder INTEGER,
            deaths_workplace INTEGER,
            deaths_lightning INTEGER,
            event_count INTEGER
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_events_date ON events(date)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_events_type ON events(type)")
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_events_location ON events(location)"
    )


def _write_json_atomic(target: Path, value: dict) -> None:
    """Write JSON through a flushed temporary file in the target directory."""
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            delete=False,
            dir=target.parent,
            suffix=".tmp",
        ) as temporary:
            temporary_path = Path(temporary.name)
            json.dump(value, temporary, ensure_ascii=False, indent=2)
            temporary.flush()
            os.fsync(temporary.fileno())
        os.replace(temporary_path, target)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def archive_day(
    state: dict,
    *,
    state_path: Path,
    archive_dir: Path,
    db_path: Path,
) -> None:
    """Archive one simulated day to JSON and SQLite."""
    state_path = Path(state_path)
    archive_dir = Path(archive_dir)
    db_path = Path(db_path)
    archive_dir.mkdir(parents=True, exist_ok=True)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    day = state["date"]
    _write_json_atomic(archive_dir / f"{day}.json", state)
    _write_json_atomic(state_path, state)

    weather = state.get("weather", {})
    economy = state.get("economy", {})
    deaths = state.get("deaths_today", {})
    events = state.get("events_today", [])

    with closing(sqlite3.connect(db_path)) as connection, connection:
        cursor = connection.cursor()
        _ensure_table(cursor)
        cursor.execute("""
            INSERT OR REPLACE INTO daily_summary VALUES (
                ?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?
            )
        """, (
            day,
            weather.get("condition", ""),
            weather.get("temp_high", 0),
            weather.get("temp_low", 0),
            weather.get("rainfall_mm", 0.0),
            economy.get("inflation_pct", 0),
            economy.get("unemployment_pct", 0),
            economy.get("exchange_rate_mvl_per_usd", 0),
            economy.get("fuel_95_price_mvl", 0),
            deaths.get("total", 0),
            deaths.get("traffic", 0),
            deaths.get("drowning", 0),
            deaths.get("suicide", 0),
            deaths.get("murder", 0),
            deaths.get("workplace", 0),
            deaths.get("lightning", 0),
            len(events),
        ))

        for event in events:
            headline = event.get("text", "")
            tags = [event.get("type", "")]
            if event.get("severity"):
                tags.append(event["severity"])

            if "维多利亚大道" in headline:
                tags.append("维多利亚大道")
                location = "维多利亚大道"
            elif "卡托拉" in headline:
                tags.append("卡托拉市")
                location = "卡托拉市"
            elif "马卡迪" in headline:
                tags.append("马卡迪港")
                location = "马卡迪港"
            elif "佩拉" in headline:
                tags.append("佩拉岛")
                location = "佩拉岛"
            elif "蒂莫" in headline:
                tags.append("蒂莫岛")
                location = "蒂莫岛"
            elif "鲁瓦" in headline:
                tags.append("鲁瓦岛")
                location = "鲁瓦岛"
            else:
                location = ""

            cursor.execute("""
                INSERT INTO events (
                    date, type, severity, location, headline, tags
                ) VALUES (?, ?, ?, ?, ?, ?)
            """, (
                day,
                event.get("type", "misc"),
                event.get("severity", "info"),
                location,
                headline,
                ",".join(tags),
            ))
