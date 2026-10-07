"""Hourly, population-weighted air temperature per country from Open-Meteo.

One request returns the recent past (modelled analysis) *and* the next days (forecast) for all
cities of a country, so history and future come from the same source. No API key is needed.
Weights are rough metro-area populations in millions; they only need to be roughly right.
"""
import time

import numpy as np
import pandas as pd
import requests

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"
MAX_PAST_DAYS = 92  # Open-Meteo limit
FORECAST_DAYS = 3

CITIES = {  # (latitude, longitude, weight)
    "germany": [(52.52, 13.41, 4.5), (53.55, 9.99, 3.3), (48.14, 11.58, 2.9), (50.94, 6.96, 3.5), (50.11, 8.68, 2.3)],
    "france": [(48.86, 2.35, 12.0), (45.76, 4.84, 2.3), (43.30, 5.37, 1.9), (43.60, 1.44, 1.4), (50.63, 3.06, 1.2)],
    "spain": [(40.42, -3.70, 6.7), (41.39, 2.17, 5.6), (39.47, -0.38, 1.6), (37.39, -5.98, 1.5), (43.26, -2.93, 1.0)],
    "poland": [(52.23, 21.01, 3.1), (50.06, 19.94, 1.4), (51.76, 19.46, 1.1), (51.11, 17.04, 1.2), (52.41, 16.93, 1.0)],
}


class WeatherError(Exception):
    """Temperature data could not be loaded."""


def _weighted_mean(results: list, weights: np.ndarray) -> pd.Series:
    columns = []
    for item in results:
        hourly = item["hourly"]
        index = pd.to_datetime(hourly["time"], utc=True)
        values = pd.Series(hourly["temperature_2m"], index=index, dtype="float64")  # None -> NaN
        columns.append(values)
    table = pd.concat(columns, axis=1)
    present = table.notna().to_numpy()
    total_weight = (present * weights).sum(axis=1)
    weighted = (table.fillna(0.0).to_numpy() * weights).sum(axis=1)
    with np.errstate(invalid="ignore", divide="ignore"):
        mean = np.where(total_weight > 0, weighted / total_weight, np.nan)
    series = pd.Series(mean, index=table.index, name="temp_c")
    series.index.name = "ds"
    return series.sort_index()


def load_weather(country: str, history_days: int = 90, forecast_days: int = FORECAST_DAYS) -> pd.Series:
    """Hourly temperature (deg C, UTC index) covering the last days and the next ``forecast_days``."""
    cities = CITIES.get(country)
    if not cities:
        raise WeatherError(f"no cities configured for {country}")
    params = {
        "latitude": ",".join(str(c[0]) for c in cities),
        "longitude": ",".join(str(c[1]) for c in cities),
        "hourly": "temperature_2m",
        "past_days": min(history_days + 2, MAX_PAST_DAYS),
        "forecast_days": forecast_days,
        "timezone": "UTC",
    }
    last_error = "unknown"
    for attempt in range(3):
        try:
            response = requests.get(OPEN_METEO_URL, params=params, timeout=(5, 30))
        except requests.RequestException as exc:
            last_error = type(exc).__name__
            time.sleep(1 + attempt)
            continue
        if response.status_code == 200:
            break
        last_error = f"HTTP {response.status_code}"
        if response.status_code not in (429, 500, 502, 503, 504):
            raise WeatherError(f"Open-Meteo request failed ({last_error})")
        time.sleep(1 + attempt)
    else:
        raise WeatherError(f"Open-Meteo request failed ({last_error})")

    try:
        payload = response.json()
        results = payload if isinstance(payload, list) else [payload]
        if len(results) != len(cities):
            raise ValueError("unexpected number of locations")
        series = _weighted_mean(results, np.array([c[2] for c in cities], dtype=float))
    except (ValueError, KeyError, TypeError) as exc:
        raise WeatherError(f"Open-Meteo returned unusable data ({type(exc).__name__})") from None
    if series.isna().all():
        raise WeatherError("Open-Meteo returned no temperatures")
    return series


def synthetic_weather(history: pd.Series, extra_hours: int = 72, seed: int = 0) -> pd.Series:
    """Fake temperature covering ``history`` plus the next hours (for tests and offline runs)."""
    rng = np.random.default_rng(seed)
    idx = pd.date_range(history.index[0], history.index[-1] + pd.Timedelta(hours=extra_hours), freq="1h", name="ds")
    hour = idx.hour.to_numpy()
    drift = np.linspace(14.0, 9.0, len(idx))
    temp = drift + 5 * np.sin((hour - 9) / 24 * 2 * np.pi) + rng.normal(0, 0.7, len(idx))
    return pd.Series(temp, index=idx, name="temp_c")
