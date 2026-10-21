import numpy as np
import pandas as pd
import pytest
import requests

from pipeline import weather as weather_module
from pipeline.trackrecord import day_ahead_frame
from pipeline.history import synthetic_history
from pipeline.weather import ARCHIVE_URL, CITIES, OPEN_METEO_URL, WeatherError, load_weather

N_CITIES = len(CITIES["germany"])


def payload(values_by_hour: dict) -> list:
    """Open-Meteo style response for all cities: ``{"2026-10-01T03:00": 12.0 or None, ...}``."""
    hourly = {"time": list(values_by_hour), "temperature_2m": list(values_by_hour.values())}
    return [{"hourly": hourly} for _ in range(N_CITIES)]


class Reply:
    def __init__(self, status=200, body=None):
        self.status_code, self._body = status, body

    def json(self):
        return self._body


@pytest.fixture
def router(monkeypatch):
    """Route requests.get by URL; every call is recorded as (url, params)."""
    state = {"calls": [], "recent": None, "archive": None, "long": None}

    def fake_get(url, params, timeout):
        state["calls"].append((url, dict(params)))
        if url == ARCHIVE_URL:
            return state["archive"]
        if params.get("past_days") == 14:
            return state["recent"]
        return state["long"] or state["recent"]

    monkeypatch.setattr(requests, "get", fake_get)
    monkeypatch.setattr(weather_module.time, "sleep", lambda s: None)
    return state


HOURS = [f"2026-10-01T{h:02d}:00" for h in range(10)]


def test_archive_wins_where_it_has_values_and_the_forecast_api_fills_the_rest(router):
    router["archive"] = Reply(200, payload({t: (None if i == 4 else 10.0) for i, t in enumerate(HOURS[:6])}))
    router["recent"] = Reply(200, payload({t: 20.0 for t in HOURS}))
    series = load_weather("germany", 90)
    values = series.to_numpy()
    assert len(series) == 10
    assert list(values[:4]) == [10.0] * 4 and values[4] == 20.0 and values[5] == 10.0  # archive, gap filled, archive
    assert list(values[6:]) == [20.0] * 4  # only the forecast API reaches this far


def test_requests_ask_for_the_right_ranges(router):
    router["archive"] = Reply(200, payload({t: 10.0 for t in HOURS}))
    router["recent"] = Reply(200, payload({t: 20.0 for t in HOURS}))
    load_weather("germany", 90, forecast_days=3)
    (recent_url, recent), (archive_url, archive) = router["calls"][:2]
    assert recent_url == OPEN_METEO_URL and recent["past_days"] == 14 and recent["forecast_days"] == 3
    assert archive_url == ARCHIVE_URL and "past_days" not in archive
    start, end = pd.Timestamp(archive["start_date"]), pd.Timestamp(archive["end_date"])
    assert (end - start).days == 90 + 2 - weather_module.ARCHIVE_LAG_DAYS
    assert len(recent["latitude"].split(",")) == N_CITIES  # all cities in one request


def test_falls_back_to_the_long_forecast_call_when_the_archive_fails(router):
    router["archive"] = Reply(500, None)
    router["recent"] = Reply(200, payload({t: 20.0 for t in HOURS[:5]}))
    router["long"] = Reply(200, payload({t: 15.0 for t in HOURS}))
    series = load_weather("germany", 90)
    assert len(series) == 10 and set(series) == {15.0}
    long_call = [p for url, p in router["calls"] if url == OPEN_METEO_URL and p.get("past_days") != 14]
    assert long_call and long_call[0]["past_days"] == 92


def test_a_failing_forecast_api_is_fatal_even_if_the_archive_works(router):
    router["archive"] = Reply(200, payload({t: 10.0 for t in HOURS}))
    router["recent"] = Reply(500, None)
    with pytest.raises(WeatherError):
        load_weather("germany", 90)


def test_day_ahead_frame_reports_why_a_model_could_not_run():
    s = synthetic_history(days=60, seed=1)
    reasons = {}
    frame = day_ahead_frame(s, ["seasonal_naive", "ridge_temp"], "germany", weather=None, n_days=4, failures=reasons)
    assert "ridge_temp" not in frame and "seasonal_naive" in frame
    assert reasons["ridge_temp"].startswith("MissingWeather: no temperature series supplied") and "(4 days)" in reasons["ridge_temp"]
    assert "seasonal_naive" not in reasons


def test_compare_prints_the_reason_when_a_model_cannot_run(monkeypatch, capsys):
    from pipeline import compare

    monkeypatch.setattr(compare, "synthetic_weather", lambda series, seed=0: pd.Series([5.0] * 10, index=series.index[:10]))
    assert compare.main(["--synthetic", "--countries", "spain", "--models", "ridge_temp", "--days", "5"]) == 0
    out = capsys.readouterr().out
    assert "could not run: ridge_temp - MissingWeather" in out and "(5 days)" in out
