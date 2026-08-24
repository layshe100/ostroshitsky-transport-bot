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
    calendar = load_data().get("calendar", {})
    if day.isoformat() in calendar.get("holidays", []):
        return "weekend"
    return "weekend" if day.weekday() >= 5 else "weekday"


def _parse_hhmm(value: str) -> time:
    hour, minute = map(int, value.split(":"))
    return time(hour=hour % 24, minute=minute)


def _minutes_from_hhmm(value: str) -> int:
    hour, minute = map(int, value.split(":"))
    return hour * 60 + minute


def _departure_datetime(day: date, value: str, tz: ZoneInfo) -> datetime:
    total_minutes = _minutes_from_hhmm(value)
    departure_day = day + timedelta(days=total_minutes // (24 * 60))
    departure_time = time(hour=(total_minutes // 60) % 24, minute=total_minutes % 60)
    return datetime.combine(departure_day, departure_time, tzinfo=tz)


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
    return sorted(result, key=_minutes_from_hhmm)


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
                departure = _departure_datetime(day, value, tz)
                if departure < start:
                    continue
                wait = max(0, round((departure - start).total_seconds() / 60))
                found.append(Departure(route["number"], route["kind"], route["label"], route["source"], departure, wait))

    found.sort(key=lambda item: item.when)
    return found[:limit]


def format_departures(items: list[Departure], direction: str, requested_at: datetime) -> str:
    if direction == "to_ostroshitsky":
        title = "🚌 Восток → Острошицкий городок"
    else:
        title = "🚌 Острошицкий городок → Восток"
    if not items:
        return f"{title}\n\nНа ближайшие 7 дней рейсов в сохранённом расписании нет."

    def wait_text(minutes: int) -> str:
        if minutes == 0:
            return "сейчас"
        if minutes < 60:
            word = "минута" if minutes == 1 else "минуты" if minutes % 10 in (2, 3, 4) and minutes % 100 not in (12, 13, 14) else "минут"
            return f"{minutes} {word}"
        hours, remainder = divmod(minutes, 60)
        hour_word = "час" if hours == 1 else "часа" if hours % 10 in (2, 3, 4) and hours % 100 not in (12, 13, 14) else "часов"
        if remainder == 0:
            return f"{hours} {hour_word}"
        minute_word = "минута" if remainder == 1 else "минуты" if remainder % 10 in (2, 3, 4) and remainder % 100 not in (12, 13, 14) else "минут"
        return f"{hours} {hour_word} {remainder} {minute_word}"

    data = load_data()
    lines = [title, ""]
    for index, item in enumerate(items):
        if item.when.date() == requested_at.date():
            day_suffix = ""
        elif item.when.date() == (requested_at + timedelta(days=1)).date():
            day_suffix = " (завтра)"
        else:
            day_suffix = f" ({item.when:%d.%m})"
        marker = "🟢 " if index == 0 else ""
        timing = f"отправление через {wait_text(item.wait_minutes)} по расписанию" if index == 0 else f"через {wait_text(item.wait_minutes)}"
        lines.append(f"{marker}{item.when:%H:%M}{day_suffix} — {timing}")
        lines.append(f"{item.kind.capitalize()} №{item.route}")
        if index != len(items) - 1:
            lines.append("")
    lines.extend([
        "",
        "Время указано по расписанию.",
        "Фактическое время прибытия может отличаться.",
        "",
        f"Расписание обновлено {data.get('updated_at', 'не указано')}.",
        f"Источник: {data.get('source', 'фотографии расписания')}.",
    ])
    return "\n".join(lines)
