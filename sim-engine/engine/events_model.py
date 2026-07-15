"""Deterministic non-P0 daily event rules."""

import math
import random
from collections.abc import Callable, Mapping
from datetime import date
from typing import Any


ANNUAL_DEATH_RATES = {
    "traffic": 52 / 365,
    "drowning": 28 / 365,
    "suicide": 58 / 365,
    "murder": 22 / 365,
    "workplace": 8 / 365,
    "lightning": 1.5 / 365,
    "other": 1.5 / 365,
}

_NOTABLE_EVENTS = (
    "塔普山火山监测站记录到3次微震——预警等级维持绿色。",
    "马里文航空MV301航班因机械故障延误2小时——佩拉岛旅客滞留机场。",
    "卡托拉市公交1路在维多利亚大道抛锚——早高峰拥堵40分钟。",
    "蒂莫岛卡瓦田报告根腐病斑——农业部已派专家前往。",
    "佩拉岛蓝湖度假村宣布明年将扩建水下餐厅座位。",
    "《马里文时报》刊登读者来信——批评卡托拉港卫生状况。",
)


def events_step(
    d: date,
    state: Mapping[str, Any],
    weather: Mapping[str, Any],
    rng_factory: Callable[[str], random.Random],
) -> tuple[dict, list[dict]]:
    """Return deterministic daily deaths and legacy general events."""
    del state, weather
    deaths = {
        category: _poisson(mean, rng_factory(f"deaths:{category}"))
        for category, mean in ANNUAL_DEATH_RATES.items()
    }
    deaths["total"] = sum(deaths.values())

    events: list[dict] = []
    for category, event_type, text in (
        ("traffic", "accident", "交通事故"),
        ("drowning", "accident", "溺水"),
        ("murder", "crime", "谋杀案"),
    ):
        count = deaths[category]
        if count > 0:
            events.append({
                "type": event_type,
                "severity": "fatal",
                "deaths": count,
                "text": f"{text}——{count}人死亡",
            })

    for stream, probability, text in (
        ("politics:minister", 0.03,
         "内政部长塞缪尔·瓦卡就近期警务改革发表声明。"),
        ("politics:opposition", 0.05,
         'DPA影子财长批评政府预算案——"穷人在哪一页？"'),
        ("politics:icac", 0.01,
         "ICAC发言人确认：鲁瓦矿难安全检查报告调查仍在进行。"),
    ):
        if rng_factory(stream).random() < probability:
            events.append({
                "type": "politics",
                "severity": "info",
                "text": text,
            })

    if rng_factory("notable:chance").random() < 0.005:
        events.append({
            "type": "misc",
            "severity": "notable",
            "text": rng_factory("notable:choice").choice(_NOTABLE_EVENTS),
        })

    event_date = d.isoformat()
    for event in events:
        event["_date"] = event_date
    return deaths, events


def _poisson(lam: float, rng: random.Random) -> int:
    if lam < 0.01:
        return 1 if rng.random() < lam else 0
    limit = math.exp(-lam)
    count = 0
    product = 1.0
    while product > limit:
        count += 1
        product *= rng.random()
    return count - 1
