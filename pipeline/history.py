"""Load a long hourly ENTSO-E load history for one country.

The security token is read from the environment (ENTSOE_API_KEY) or backend/.env
and is never printed or included in error messages.
"""
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))  # allow `backend.*` imports when run from anywhere
load_dotenv(ROOT / "backend" / ".env")

from backend.core.config import COUNTRY_CODES  # noqa: E402
from backend.data.parser import parse_energy_xml  # noqa: E402
from pipeline.anomaly import STEP_LIMIT, step_limit  # noqa: E402

ENTSOE_BASE_URL = "https://web-api.tp.entsoe.eu/api"
CHUNK_DAYS = 30  # keep each request small; ENTSO-E limits very long ranges


class HistoryError(Exception):
    """History could not be loaded."""


def _fetch_chunk(country_code: str, start: datetime, end: datetime, token: str, process: str = "A16") -> str:
    """process A16 = realised load, A01 = the TSO's day-ahead forecast."""
    params = {
        "securityToken": token,
        "documentType": "A65",
        "processType": process,
        "outBiddingZone_Domain": country_code,
        "periodStart": start.strftime("%Y%m%d%H00"),
        "periodEnd": end.strftime("%Y%m%d%H00"),
    }
    last_error = "unknown"
    for attempt in range(3):
        try:
            response = requests.get(ENTSOE_BASE_URL, params=params, timeout=(5, 60))
        except requests.RequestException as exc:
            last_error = type(exc).__name__  # never include the URL (it has the token)
            continue
        if response.status_code == 200:
            return response.text
        last_error = f"HTTP {response.status_code}"
        if response.status_code not in (429, 500, 502, 503, 504):
            break
    raise HistoryError(f"ENTSO-E request failed ({last_error})")


def suspect_hours(quarter_hours: pd.Series, limit: float = STEP_LIMIT) -> pd.DatetimeIndex:
    """UTC hours touched by an implausible jump between two consecutive 15-minute values.

    Both sides of a jump count (the hour of the earlier and of the later value). Steep but steady
    ramps are not jumps: a big step is only a jump when the steps right before and after it are
    not big steps in the same direction (Italy's morning ramp has several +8% quarter-hours in a
    row, a source glitch such as 65.5 -> 52.8 GW stands alone). Series that are not in 15-minute
    steps are not checked: their steps are naturally larger.
    """
    empty = pd.DatetimeIndex([], tz="UTC")
    if len(quarter_hours) < 2:
        return empty
    if quarter_hours.index.to_series().diff().median() != pd.Timedelta(minutes=15):
        return empty
    grid = quarter_hours.asfreq("15min")
    previous = grid.shift(1)
    step = (grid - previous) / ((grid + previous) / 2)  # signed change into each value
    size = step.abs()
    before, after = step.shift(1), step.shift(-1)  # the steps into the previous value and out of this one
    ramp = (
        (np.sign(before) == np.sign(step))
        & (np.sign(after) == np.sign(step))
        & (before.abs() >= size / 2)
        & (after.abs() >= size / 2)
    )
    jumps = step.index[((size > limit) & ~ramp).to_numpy()]
    if len(jumps) == 0:
        return empty
    both_sides = jumps.floor("h").append((jumps - pd.Timedelta(minutes=15)).floor("h"))
    return both_sides.unique().sort_values()


def to_hourly(series_points: list, limit: float = STEP_LIMIT) -> pd.Series:
    """Convert parser output ([{time, load_mw}, ...]) to a clean hourly UTC series.

    The hours with implausible 15-minute jumps (steps above ``limit``) are kept in
    ``series.attrs["suspect_hours"]``, the limit itself in ``series.attrs["step_limit"]``.
    """
    df = pd.DataFrame(series_points)
    if df.empty:
        raise HistoryError("no points to convert")
    df["time"] = pd.to_datetime(df["time"], utc=True)
    s = df.drop_duplicates("time").set_index("time")["load_mw"].astype(float).sort_index()
    s = s.replace(0.0, np.nan)  # a zero national load is a data glitch, not a real value
    suspect = suspect_hours(s, limit)
    hourly = s.resample("1h").mean()
    hourly = hourly.interpolate(limit=3)  # fill short gaps only
    hourly = hourly.dropna()
    hourly.index.name = "ds"
    hourly.attrs["suspect_hours"] = suspect
    hourly.attrs["step_limit"] = limit
    return hourly


def load_history(country: str, days: int = 90, process: str = "A16") -> pd.Series:
    """Hourly load (MW) for the last ``days`` days, UTC index (process A16 = realised, A01 = TSO day-ahead)."""
    token = os.getenv("ENTSOE_API_KEY")
    if not token:
        raise HistoryError("ENTSOE_API_KEY is not configured")
    code = COUNTRY_CODES[country]

    end = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    start = end - timedelta(days=days)
    points = {}
    cursor = start
    while cursor < end:
        chunk_end = min(cursor + timedelta(days=CHUNK_DAYS), end)
        parsed = parse_energy_xml(_fetch_chunk(code, cursor, chunk_end, token, process), country)
        if parsed["status"] == "success":
            for p in parsed["series"]:
                if p["load_mw"] is not None:
                    points[p["time"]] = p["load_mw"]
        elif parsed["status"] == "error":
            raise HistoryError(f"parse error for {country}: {parsed['message']}")
        cursor = chunk_end

    if not points:
        raise HistoryError(f"no data returned for {country}")
    return to_hourly([{"time": t, "load_mw": v} for t, v in points.items()], limit=step_limit(country))


def load_tso_forecast(country: str, days: int = 90) -> pd.Series:
    """The TSO's own published day-ahead load forecast (MW, hourly, UTC)."""
    return load_history(country, days, process="A01")


def synthetic_tso(actual: pd.Series, seed: int = 0) -> pd.Series:
    """A plausible fake TSO forecast: the actual load with ~1.5% error (tests / offline runs)."""
    rng = np.random.default_rng(seed + 1000)
    return actual * (1 + rng.normal(0, 0.015, len(actual)))


def synthetic_history(days: int = 90, seed: int = 0, base: float = 50000.0) -> pd.Series:
    """Fake hourly load with daily + weekly seasonality (for tests and offline runs)."""
    rng = np.random.default_rng(seed)
    end = pd.Timestamp.now(tz="UTC").floor("h")
    idx = pd.date_range(end=end, periods=days * 24, freq="1h", name="ds")
    hour = idx.hour.to_numpy()
    dow = idx.dayofweek.to_numpy()
    daily = 0.18 * np.sin((hour - 8) / 24 * 2 * np.pi) + 0.08 * np.sin((hour - 17) / 12 * 2 * np.pi)
    weekly = np.where(dow >= 5, -0.12, 0.0)
    noise = rng.normal(0, 0.01, len(idx))
    return pd.Series(base * (1 + daily + weekly + noise), index=idx)
