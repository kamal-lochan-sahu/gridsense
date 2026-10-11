"""Walk-forward day-ahead track record: GridSense vs the TSO's own forecast vs seasonal naive.

For each of the last days D the *current champion model* forecasts the 24 hours of D using only
data up to ORIGIN_HOUR_UTC - 1 hours on the day before (about when TSOs publish their day-ahead
forecast; exact times differ per TSO). The same is done for the seasonal-naive baseline. All are
compared with what the grid actually did, on exactly the same hours. The champion is today's
model applied to the past, so this is a walk-forward evaluation, not an archive of old live runs.
"""
import numpy as np
import pandas as pd

from pipeline.champion import HOUR, predict_origin

ORIGIN_HOUR_UTC = 11
TRACK_DAYS = 14
HOURLY_DAYS = 3
MIN_HOURS_PER_DAY = 18
SUMMARY_WINDOWS = (7, 14)
ALL_SOURCES = ("gridsense", "tso", "naive")

METHOD = (
    "Walk-forward: for each past day the current model forecasts the 24 hours using only data up to "
    "10:00 UTC the day before (about when the TSO publishes its day-ahead forecast); error = mean "
    "absolute percentage error against the realised load, on the same hours for every source."
)


def target_days(series: pd.Series, n_days: int) -> list:
    """The last ``n_days`` UTC days whose 24 hours are all observed (oldest first)."""
    last_day = (series.index[-1] - 23 * HOUR).floor("D")
    return [last_day - pd.Timedelta(days=i) for i in range(n_days)][::-1]


def _mape(frame: pd.DataFrame, source: str) -> float:
    return float((frame[source] - frame["actual"]).abs().div(frame["actual"]).mean() * 100)


def _number(value):
    return None if pd.isna(value) else round(float(value), 1)


def build_track_record(series, champion, country, weather=None, tso=None, n_days: int = TRACK_DAYS):
    """Dict for forecast.json, or None when not enough days could be evaluated."""
    horizon = (24 - ORIGIN_HOUR_UTC) + 24
    memo, parts = {}, []
    for day in target_days(series, n_days):
        origin = day - pd.Timedelta(hours=24 - ORIGIN_HOUR_UTC)
        try:
            ours = predict_origin(series, champion, origin, country, horizon, weather, memo)
            naive = predict_origin(series, "seasonal_naive", origin, country, horizon, None, memo)
        except Exception:  # a day that cannot be evaluated is skipped, not fatal
            continue
        if ours is None or naive is None:
            continue
        ours, naive = ours.set_index("ds").loc[day : day + 23 * HOUR], naive.set_index("ds")["yhat"]
        parts.append(
            pd.DataFrame({"actual": ours["actual"], "gridsense": ours["yhat"], "naive": naive.reindex(ours.index)})
        )
    if not parts:
        return None

    frame = pd.concat(parts)
    frame["tso"] = tso.reindex(frame.index) if tso is not None else np.nan
    sources = [s for s in ALL_SOURCES if frame[s].notna().any()]
    frame = frame.dropna(subset=["actual", *sources])  # the same hours for every source
    if frame.empty:
        return None

    day_of = frame.index.floor("D")
    days = sorted(set(day_of))
    summary = {}
    for k in SUMMARY_WINDOWS:
        window = days[-k:]
        sub = frame[day_of.isin(window)]
        summary[f"{k}d"] = {
            "days": len(window),
            "hours": int(len(sub)),
            **{s: round(_mape(sub, s), 2) for s in sources},
        }

    daily = []
    for day in days:
        sub = frame[day_of == day]
        if len(sub) >= MIN_HOURS_PER_DAY:
            daily.append({"date": day.strftime("%Y-%m-%d"), **{s: round(_mape(sub, s), 2) for s in sources}})

    recent = frame[day_of.isin(days[-HOURLY_DAYS:])]
    hourly = [
        {"ds": ts.strftime("%Y-%m-%d %H:%M:%S"), **{c: _number(row[c]) for c in ["actual", *sources]}}
        for ts, row in recent.iterrows()
    ]
    return {
        "method": METHOD,
        "model": champion,
        "origin_hour_utc": ORIGIN_HOUR_UTC,
        "sources": sources,
        "summary": summary,
        "daily": daily,
        "hourly": hourly,
    }
