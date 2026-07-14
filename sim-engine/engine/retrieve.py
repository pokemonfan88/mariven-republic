"""
retrieve.py — Mariven Simulation Engine
========================================
History + worldbuilding retrieval for LLM prompt building.

Usage:
    from retrieve import retrieve_context
    context = retrieve_context(event, db_path="output/events.db", world_dir="worldbuilding")
    # context -> dict with 'history', 'worldbuilding', 'stats' keys — ready to embed in LLM prompt
"""

import json
import os
import sqlite3
import glob


def _safe_fetch(cursor, sql, params=()):
    """Fetch all rows, return empty list on any error."""
    try:
        cursor.execute(sql, params)
        return cursor.fetchall()
    except Exception:
        return []


def retrieve_history(cursor: sqlite3.Cursor, event: dict) -> dict:
    """Query SQLite for historically relevant context.

    Returns dict with:
        - recent_similar: similar events in last 30 days
        - same_day_last_year: events on the same date last year
        - this_month_stats: monthly aggregated stats
    """
    d = event.get("_date", "")
    ev_type = event.get("type", "")
    headline = event.get("text", "")

    result = {}

    # ---- recent similar events (same type, last 30 days) ----
    if ev_type:
        rows = _safe_fetch(cursor, """
            SELECT date, headline FROM events
            WHERE type = ? AND date < ? AND date >= date(?, '-30 days')
            ORDER BY date DESC LIMIT 5
        """, (ev_type, d, d))
        result["recent_similar"] = [{"date": r[0], "headline": r[1]} for r in rows]

    # ---- same day last year ----
    last_year = f"{int(d[:4]) - 1}{d[4:]}"
    rows = _safe_fetch(cursor, """
        SELECT type, headline FROM events
        WHERE date = ? LIMIT 5
    """, (last_year,))
    result["same_day_last_year"] = [{"type": r[0], "headline": r[1]} for r in rows]

    # ---- this month stats ----
    month = d[:7]
    rows = _safe_fetch(cursor, """
        SELECT
            SUM(deaths_traffic), SUM(deaths_drowning), SUM(deaths_suicide),
            SUM(deaths_murder), SUM(deaths_workplace), SUM(deaths_total),
            COUNT(*)
        FROM daily_summary
        WHERE date LIKE ?
    """, (month + "%",))
    if rows and rows[0]:
        r = rows[0]
        result["this_month_stats"] = {
            "days_elapsed": r[6] or 0,
            "deaths_traffic": r[0] or 0,
            "deaths_drowning": r[1] or 0,
            "deaths_suicide": r[2] or 0,
            "deaths_murder": r[3] or 0,
            "deaths_workplace": r[4] or 0,
            "deaths_total": r[5] or 0,
        }

    # ---- all-time top events of same type ----
    if ev_type:
        rows = _safe_fetch(cursor, """
            SELECT date, headline FROM events
            WHERE type = ? AND date < ?
            ORDER BY date DESC LIMIT 3
        """, (ev_type, d))
        result["all_time_recent"] = [{"date": r[0], "headline": r[1]} for r in rows]

    return result


def retrieve_worldbuilding(headline: str, ev_type: str, world_dir: str = "worldbuilding") -> list:
    """Search worldbuilding docs for content relevant to this event.

    Returns list of dicts: [{"file": "city-directory.md", "snippet": "..."}, ...]
    """
    snippets = []
    keywords = _extract_keywords(headline, ev_type)

    md_files = glob.glob(os.path.join(world_dir, "*.md"))

    for filepath in md_files:
        filename = os.path.basename(filepath)
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read()
        except Exception:
            continue

        for kw in keywords:
            if kw.lower() in content.lower():
                # extract a snippet around the match
                idx = content.lower().find(kw.lower())
                start = max(0, idx - 150)
                end = min(len(content), idx + 400)
                snippet = content[start:end].strip()
                # truncate to reasonable length
                if len(snippet) > 500:
                    snippet = snippet[:500] + "..."
                snippets.append({"file": filename, "keyword": kw, "snippet": snippet})
                break  # one snippet per file

    return snippets[:8]  # limit to avoid overwhelming the LLM


def _extract_keywords(headline: str, ev_type: str) -> list:
    """Extract search keywords from the event headline and type."""
    kw = []

    type_keyword_map = {
        "traffic": ["交通事故", "维多利亚大道", "港口路", "机场高速", "酒驾", "车祸"],
        "drowning": ["溺水", "渔民", "潜水", "翻船", "海域"],
        "suicide": ["自杀", "Lifeline", "心理健康"],
        "murder": ["谋杀", "警察", "凶杀", "犯罪"],
        "weather": ["暴雨", "气旋", "洪水", "干旱", "天气", "预报"],
        "politics": ["总理", "部长", "议会", "选举", "DPA", "MUP", "马卡里", "反对党"],
        "crime": ["警局", "犯罪", "逮捕", "监狱"],
        "accident": ["矿难", "火灾", "倒塌", "受伤"],
    }

    if ev_type in type_keyword_map:
        kw.extend(type_keyword_map[ev_type])

    # location keywords from headline
    location_map = {
        "卡托拉": ["卡托拉市", "Katora", "维多利亚大道", "共和国大道", "硬币街"],
        "马卡迪": ["马卡迪港", "Makadi", "蔗田", "港口"],
        "佩拉": ["佩拉岛", "Pela", "蓝湖", "度假村"],
        "蒂莫": ["蒂莫岛", "Timo", "卡瓦"],
        "鲁瓦": ["鲁瓦岛", "Ruwa", "金矿", "矿"],
        "西部平原": ["蔗田", "平原"],
    }

    for loc, loc_kw in location_map.items():
        if loc in headline:
            kw.extend(loc_kw)

    return kw[:10]


def retrieve_context(event: dict, db_path: str = "output/events.db", world_dir: str = "worldbuilding") -> dict:
    """Main entry point: given an engine event, return all contextual data for LLM prompt.

    Args:
        event: dict with at least 'type' and 'text' keys. Should also have '_date' from the state.
        db_path: path to SQLite events database
        world_dir: path to worldbuilding markdown docs

    Returns:
        dict with 'history' (SQLite results) and 'worldbuilding' (doc snippets)
    """
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    history = retrieve_history(cursor, event)
    worldbuilding_snippets = retrieve_worldbuilding(
        event.get("text", ""),
        event.get("type", ""),
        world_dir=world_dir,
    )

    conn.close()

    return {
        "history": history,
        "worldbuilding": worldbuilding_snippets,
    }
