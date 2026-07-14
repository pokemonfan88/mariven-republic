"""
archive.py — Mariven Simulation Engine
=======================================
Daily snapshot archiver: JSON snapshots + SQLite event index.

Usage:
    from archive import archive_day
    archive_day(state, state_dir="data", archive_dir="output/archive", db_path="output/events.db")
"""

import json
import os
import sqlite3
from datetime import date


def _ensure_table(cursor: sqlite3.Cursor):
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
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_events_location ON events(location)")


def archive_day(state: dict, state_dir: str = "data", archive_dir: str = "output/archive", db_path: str = "output/events.db"):
    """Archive one simulated day: JSON snapshot + SQLite rows.

    Args:
        state: The ticked state dict from engine.py
        state_dir: Where state.json lives (used to update the running state file)
        archive_dir: Where daily JSON snapshots are stored
        db_path: Path to SQLite events database
    """
    # ---- ensure directories ----
    os.makedirs(archive_dir, exist_ok=True)
    os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)

    d = state["date"]

    # ---- 1. JSON snapshot ----
    snapshot_path = os.path.join(archive_dir, f"{d}.json")
    with open(snapshot_path, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

    # ---- 2. Update running state.json ----
    state_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), state_dir, "state.json")
    with open(state_path, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

    # ---- 3. SQLite ----
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    _ensure_table(cursor)

    # ---- daily summary row ----
    w = state.get("weather", {})
    e = state.get("economy", {})
    deaths = state.get("deaths_today", {})
    events_list = state.get("events_today", [])

    cursor.execute("""
        INSERT OR REPLACE INTO daily_summary VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (
        d,
        w.get("condition", ""),
        w.get("temp_high", 0),
        w.get("temp_low", 0),
        w.get("rainfall_mm", 0.0),
        e.get("inflation_pct", 0),
        e.get("unemployment_pct", 0),
        e.get("exchange_rate_mvl_per_usd", 0),
        e.get("fuel_95_price_mvl", 0),
        deaths.get("total", 0),
        deaths.get("traffic", 0),
        deaths.get("drowning", 0),
        deaths.get("suicide", 0),
        deaths.get("murder", 0),
        deaths.get("workplace", 0),
        deaths.get("lightning", 0),
        len(events_list),
    ))

    # ---- individual event rows ----
    for ev in events_list:
        headline = ev.get("text", "")
        tags_list = [ev.get("type", "")]
        if ev.get("severity"):
            tags_list.append(ev["severity"])

        # auto-tag from headline text
        if "维多利亚大道" in headline:
            tags_list.append("维多利亚大道")
            location = "维多利亚大道"
        elif "卡托拉" in headline:
            tags_list.append("卡托拉市")
            location = "卡托拉市"
        elif "马卡迪" in headline:
            tags_list.append("马卡迪港")
            location = "马卡迪港"
        elif "佩拉" in headline:
            tags_list.append("佩拉岛")
            location = "佩拉岛"
        elif "蒂莫" in headline:
            tags_list.append("蒂莫岛")
            location = "蒂莫岛"
        elif "鲁瓦" in headline:
            tags_list.append("鲁瓦岛")
            location = "鲁瓦岛"
        else:
            location = ""

        cursor.execute("""
            INSERT INTO events (date, type, severity, location, headline, tags)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            d,
            ev.get("type", "misc"),
            ev.get("severity", "info"),
            location,
            headline,
            ",".join(tags_list),
        ))

    conn.commit()
    conn.close()
