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


def day_ahead_frame(series, names, country, weather=None, n_days: int = TRACK_DAYS) -> pd.DataFrame:
    """Walk-forward day-ahead forecasts of several models next to the realised load.

    One row per hour (UTC) of the last ``n_days`` complete days; columns ``actual`` and one per
    model that could run. For each day D the models see only data up to ORIGIN_HOUR_UTC - 1 hours
    on the day before. Forecasts that could not be produced are NaN.
    """
    horizon = (24 - ORIGIN_HOUR_UTC) + 24
    memo, forecasts, actuals = {}, {name: [] for name in names}, []
    for day in target_days(series, n_days):
        origin = day - pd.Timedelta(hours=24 - ORIGIN_HOUR_UTC)
        actual_added = False
        for name in names:
            try:
                pred = predict_origin(series, name, origin, country, horizon, weather, memo)
            except Exception:  # a model that cannot run on a day is skipped, not fatal
                continue
            if pred is None:
                continue
            window = pred.set_index("ds").loc[day : day + 23 * HOUR]
            forecasts[name].append(window["yhat"])
            if not actual_added:
                actuals.append(window["actual"])
                actual_added = True
    if not actuals:
        return pd.DataFrame(columns=["actual"])
    frame = pd.DataFrame({"actual": pd.concat(actuals)})
    for name in names:
        if forecasts[name]:
            frame[name] = pd.concat(forecasts[name]).reindex(frame.index)
    return frame


def build_track_record(series, champion, country, weather=None, tso=None, n_days: int = TRACK_DAYS):
    """Dict for forecast.json, or None when not enough days could be evaluated."""
    names = list(dict.fromkeys([champion, "seasonal_naive"]))
    raw = day_ahead_frame(series, names, country, weather, n_days)
    if raw.empty or champion not in raw or "seasonal_naive" not in raw:
        return None
    frame = pd.DataFrame({"actual": raw["actual"], "gridsense": raw[champion], "naive": raw["seasonal_naive"]})
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
