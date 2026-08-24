from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone as dt_timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


BASE_DIR = Path(__file__).resolve().parent
DATA_FILE = BASE_DIR / "schedule_data.json"


@dataclass(frozen=True)
class Departure:
    route: str
    kind: str
    label: str
    source: str
    when: datetime
    wait_minutes: int


def load_data() -> dict[str, Any]:
    return json.loads(DATA_FILE.read_text(encoding="utf-8"))


def timezone() -> ZoneInfo:
    try:
        return ZoneInfo(load_data()["timezone"])
    except ZoneInfoNotFoundError:
        # Minsk is UTC+3 year-round; this keeps local Windows checks working
        # even when the system has no IANA tzdata package installed.
        return dt_timezone(timedelta(hours=3), name="Europe/Minsk")


def season_for(day: date) -> str:
    # На табличке указаны сезоны, но границы перехода не указаны.
    # Переключатель можно переопределить в запросе: «лето» или «зима».
    return "summer" if 4 <= day.month <= 10 else "winter"


def _day_group(day: date) -> str:
    return "weekend" if day.weekday() >= 5 else "weekday"


def _parse_hhmm(value: str) -> time:
    hour, minute = map(int, value.split(":"))
    return time(hour=hour, minute=minute)


def _times_for(route: dict[str, Any], day: date, season_override: str | None) -> list[str]:
    season = season_override or season_for(day)
    schedule = route["schedule"]
    period = schedule.get(season) or schedule.get("all")
    if not period:
        return []
    block = period.get(_day_group(day)) or period.get("all")
    if not block:
        return []

    weekday = day.weekday()
    result = set(block.get("regular", []))
    for value, allowed_days in block.get("only", {}).items():
        if weekday in allowed_days:
            result.add(value)
        else:
            result.discard(value)
    for value, excluded_days in block.get("except", {}).items():
        if weekday in excluded_days:
            result.discard(value)
    return sorted(result, key=lambda value: _parse_hhmm(value))


def next_departures(
    direction: str,
    start: datetime,
    limit: int = 5,
    season_override: str | None = None,
    route_filter: str | None = None,
) -> list[Departure]:
    data = load_data()
    tz = timezone()
    if start.tzinfo is None:
        start = start.replace(tzinfo=tz)
    routes = data["routes"].get(direction, [])
    if route_filter:
        routes = [route for route in routes if route["number"] == route_filter]

    found: list[Departure] = []
    for offset in range(0, 8):
        day = (start + timedelta(days=offset)).date()
        for route in routes:
            for value in _times_for(route, day, season_override):
                departure = datetime.combine(day, _parse_hhmm(value), tzinfo=tz)
                if departure < start:
                    continue
                wait = max(0, round((departure - start).total_seconds() / 60))
                found.append(Departure(route["number"], route["kind"], route["label"], route["source"], departure, wait))

    found.sort(key=lambda item: item.when)
    return found[:limit]


def format_departures(items: list[Departure], direction: str, requested_at: datetime) -> str:
    if direction == "to_ostroshitsky":
        title = "Восток — Острошицкий городок"
    else:
        title = "Острошицкий городок — Восток"
    if not items:
        return f"{title}\n\nНа ближайшие 7 дней рейсов в сохранённом расписании нет."

    lines = [f"{title}", f"Отсчёт от {requested_at.strftime('%d.%m %H:%M')} (Минск)", ""]
    for item in items:
        day_label = "сегодня" if item.when.date() == requested_at.date() else item.when.strftime("%d.%m")
        lines.append(f"{item.when:%H:%M} ({day_label}) — №{item.route} {item.kind}, ждать примерно {item.wait_minutes} мин.")
    return "\n".join(lines)
