from datetime import datetime

from schedule import next_departures, timezone


def test_451_summer_monday_special_times():
    monday = datetime(2026, 8, 24, 8, 20, tzinfo=timezone())
    items = next_departures("to_ostroshitsky", monday, limit=3, season_override="summer", route_filter="451")
    assert [item.when.strftime("%H:%M") for item in items] == ["08:25", "10:15", "10:45"]


def test_451_from_minsk_to_ostroshitsky_is_present():
    monday = datetime(2026, 8, 24, 18, 0, tzinfo=timezone())
    items = next_departures("to_ostroshitsky", monday, limit=2, season_override="summer", route_filter="451")
    assert [item.when.strftime("%H:%M") for item in items] == ["18:05", "18:45"]


def test_2198_return_schedule():
    start = datetime(2026, 8, 21, 7, 30, tzinfo=timezone())
    items = next_departures("to_vostok", start, limit=2, route_filter="2198")
    assert [item.when.strftime("%H:%M") for item in items] == ["07:42", "08:01"]


def test_2198_minsk_schedule_matches_photo():
    start = datetime(2026, 8, 21, 10, 0, tzinfo=timezone())
    items = next_departures("to_ostroshitsky", start, limit=4, route_filter="2198")
    assert [item.when.strftime("%H:%M") for item in items] == ["10:15", "11:15", "12:00", "12:15"]


def test_2198_full_ostroshitsky_to_minsk_schedule():
    start = datetime(2026, 8, 21, 0, 0, tzinfo=timezone())
    items = next_departures("to_vostok", start, limit=21, route_filter="2198")
    assert [item.when.strftime("%H:%M") for item in items] == [
        "07:29", "07:42", "08:01", "08:13", "09:53", "10:33", "11:13", "11:53",
        "12:53", "13:53", "14:13", "14:48", "16:18", "16:53", "17:28", "18:03",
        "18:58", "19:19", "20:13", "20:38", "21:33",
    ]


def test_451_from_ostroshitsky_to_minsk():
    start = datetime(2026, 8, 21, 18, 0, tzinfo=timezone())
    items = next_departures("to_vostok", start, limit=3, season_override="summer", route_filter="451")
    assert [item.when.strftime("%H:%M") for item in items] == ["18:41", "19:21", "20:16"]
