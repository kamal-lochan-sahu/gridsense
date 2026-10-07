"""Forecast models. Each takes an hourly UTC load Series and returns the next ``horizon`` hours.

Signature: ``model(train, horizon=24, country=None, weather=None)``. ``weather`` is an hourly UTC
temperature Series covering the training period and the forecast hours; only the temperature
models use it. Return value: DataFrame indexed by ``ds`` (UTC) with columns yhat, yhat_lower,
yhat_upper (the bounds are NaN for models without prediction intervals).
"""
import logging
import warnings
from datetime import timedelta

import numpy as np
import pandas as pd

from pipeline.daytype import day_class

warnings.filterwarnings("ignore", message=".*Optimization failed to converge.*")

HORIZON = 24
DEFAULT_TZ = "Europe/Berlin"
COUNTRY_TZ = {
    "germany": "Europe/Berlin",
    "france": "Europe/Paris",
    "spain": "Europe/Madrid",
    "poland": "Europe/Warsaw",
}
LEVEL_HOURS = 24 * 7  # window used to measure the current load level
LEVEL_CLIP = (0.9, 1.1)  # never rescale by more than +-10%
PROPHET_TEMP_DAYS = 56  # shorter window for the temperature model: ignore the summer
HDD_BASE, CDD_BASE = 16.0, 22.0  # heating / cooling degree-day thresholds (deg C)


class MissingWeather(Exception):
    """A temperature model was asked to run without (enough) temperature data."""


def _quiet_prophet() -> None:
    """Prophet/cmdstanpy configure their own loggers on import, so silence them afterwards."""
    for name in ("cmdstanpy", "prophet", "prophet.plot"):
        logging.getLogger(name).setLevel(logging.CRITICAL)


def tz_of(country) -> str:
    return COUNTRY_TZ.get(country, DEFAULT_TZ)


def shift_local(idx: pd.DatetimeIndex, days: int, tz: str) -> pd.DatetimeIndex:
    """Timestamps ``days`` earlier on the *local wall clock* (same local hour, DST-safe).

    A plain ``idx - 7 days`` in UTC points at the wrong local hour for a week after the
    clocks change. Hours that are ambiguous or do not exist locally become NaT (-> NaN).
    """
    local = idx.tz_convert(tz).tz_localize(None) - pd.Timedelta(days=days)
    return local.tz_localize(tz, ambiguous="NaT", nonexistent="shift_forward").tz_convert("UTC")


def local_naive(idx: pd.DatetimeIndex, tz: str) -> pd.DatetimeIndex:
    """UTC index -> local wall-clock time without tz info (what Prophet should see)."""
    return idx.tz_convert(tz).tz_localize(None)


def future_index(train: pd.Series, horizon: int = HORIZON) -> pd.DatetimeIndex:
    return pd.date_range(
        train.index[-1] + pd.Timedelta(hours=1), periods=horizon, freq="1h", name="ds"
    )


def _frame(idx, yhat, lower=None, upper=None) -> pd.DataFrame:
    nan = np.full(len(idx), np.nan)
    return pd.DataFrame(
        {
            "yhat": np.asarray(yhat, dtype=float),
            "yhat_lower": nan if lower is None else np.asarray(lower, dtype=float),
            "yhat_upper": nan if upper is None else np.asarray(upper, dtype=float),
        },
        index=idx,
    )


# ----------------------------------------------------------------------------- naive family


def seasonal_naive(train, horizon=HORIZON, country=None, weather=None) -> pd.DataFrame:
    """Same hour one week ago (falls back to one day ago). The baseline every model must beat."""
    idx = future_index(train, horizon)
    tz = tz_of(country)
    weekly = train.reindex(shift_local(idx, 7, tz)).to_numpy(dtype=float)
    daily = train.reindex(shift_local(idx, 1, tz)).to_numpy(dtype=float)
    return _frame(idx, np.where(np.isnan(weekly), daily, weekly))


def naive_avg3(train, horizon=HORIZON, country=None, weather=None) -> pd.DataFrame:
    """Mean of the same hour 1, 2 and 3 weeks ago: seasonal-naive with less noise."""
    idx = future_index(train, horizon)
    tz = tz_of(country)
    stack = np.vstack(
        [train.reindex(shift_local(idx, 7 * k, tz)).to_numpy(dtype=float) for k in (1, 2, 3)]
    )
    count = (~np.isnan(stack)).sum(axis=0)
    mean = np.where(count > 0, np.nansum(stack, axis=0) / np.maximum(count, 1), np.nan)
    fallback = train.reindex(shift_local(idx, 1, tz)).to_numpy(dtype=float)
    return _frame(idx, np.where(np.isnan(mean), fallback, mean))


def _train_by_local_time(train: pd.Series, tz: str) -> pd.Series:
    lookup = pd.Series(train.to_numpy(dtype=float), index=local_naive(train.index, tz))
    return lookup[~lookup.index.duplicated(keep="first")]  # the repeated hour when clocks go back


def _reference_dates(day, cls: str, country, weeks: int, max_back: int) -> list:
    """Up to ``weeks`` earlier dates of the same class as ``day`` (see pipeline.daytype).

    Weekdays and Saturdays look back in steps of one week. A Sunday does too. A public holiday
    on Monday-Friday behaves like a Sunday, so it looks back day by day for the last Sundays and
    holidays. Dates of another class (e.g. a holiday one week ago) are skipped.
    """
    step = 1 if (cls == "sun" and day.weekday() != 6) else 7
    found, current = [], day
    while len(found) < weeks and (day - current).days < max_back * 7:
        current -= timedelta(days=step)
        if day_class(current, country) == cls:
            found.append(current)
    return found


def daytype_reference(train: pd.Series, idx: pd.DatetimeIndex, country, weeks=3, max_back=6) -> np.ndarray:
    """Holiday-aware 'same hour on comparable days' mean for every timestamp of ``idx`` (UTC)."""
    tz = tz_of(country)
    lookup = _train_by_local_time(train, tz)
    local = idx.tz_convert(tz).tz_localize(None)
    dates = local.normalize()
    out = np.full(len(local), np.nan)
    for day_stamp in pd.unique(dates):
        stamp = pd.Timestamp(day_stamp)
        day = stamp.date()
        refs = _reference_dates(day, day_class(day, country), country, weeks, max_back)
        if not refs:
            continue
        mask = np.asarray(dates == stamp)
        times = local[mask]
        stack = np.vstack(
            [lookup.reindex(times - pd.Timedelta(days=(day - ref).days)).to_numpy() for ref in refs]
        )
        count = (~np.isnan(stack)).sum(axis=0)
        out[mask] = np.where(count > 0, np.nansum(stack, axis=0) / np.maximum(count, 1), np.nan)
    return out


def naive_daytype(train, horizon=HORIZON, country=None, weather=None) -> pd.DataFrame:
    """Like naive_avg3 but holiday-aware: a public holiday is predicted from past Sundays/holidays
    and a holiday in a reference week is skipped instead of copied."""
    idx = future_index(train, horizon)
    ref = daytype_reference(train, idx, country)
    fallback = seasonal_naive(train, horizon, country)["yhat"].to_numpy()
    return _frame(idx, np.where(np.isnan(ref), fallback, ref))


def level_factor(train: pd.Series, country, hours: int = LEVEL_HOURS) -> float:
    """How far the last ``hours`` of actual load sit above/below their holiday-aware reference.

    The references use data at least a week older than each hour, so there is no leakage.
    """
    recent = train.index[-hours:]
    ref = daytype_reference(train, recent, country)
    actual = train.reindex(recent).to_numpy(dtype=float)
    ok = np.isfinite(ref) & np.isfinite(actual)
    if ok.sum() < hours // 2:
        return 1.0
    return float(np.clip(actual[ok].sum() / ref[ok].sum(), *LEVEL_CLIP))


def naive_level(train, horizon=HORIZON, country=None, weather=None) -> pd.DataFrame:
    """naive_daytype rescaled by the load level of the last 7 days (catches autumn/spring drift)."""
    base = naive_daytype(train, horizon, country)
    return _frame(base.index, base["yhat"].to_numpy() * level_factor(train, country))


# ----------------------------------------------------------------------------- Holt-Winters


def ets(train, horizon=HORIZON, country=None, weather=None) -> pd.DataFrame:
    """Holt-Winters with a 24h seasonal cycle on the last 4 weeks."""
    from statsmodels.tsa.holtwinters import ExponentialSmoothing

    values = train.tail(24 * 28).to_numpy(dtype=float)
    fit = ExponentialSmoothing(
        values, trend="add", damped_trend=True, seasonal="add", seasonal_periods=24
    ).fit()
    return _frame(future_index(train, horizon), fit.forecast(horizon))


# ----------------------------------------------------------------------------- Prophet family


def _prophet_input(train: pd.Series, country):
    """Training frame on the local wall clock (so the daily curve survives DST changes).

    Returns ``(frame, tz, utc_index)``; ``utc_index`` are the UTC timestamps of the frame's rows.
    """
    tz = tz_of(country)
    local = local_naive(train.index, tz)
    keep = ~local.duplicated(keep="first")  # the repeated hour when clocks go back
    frame = pd.DataFrame({"ds": local[keep], "y": train.to_numpy(dtype=float)[keep]})
    return frame.reset_index(drop=True), tz, train.index[keep]


def _prophet_future(train: pd.Series, horizon: int, tz: str):
    idx = future_index(train, horizon)
    return idx, pd.DataFrame({"ds": local_naive(idx, tz)})


def _offday_flags(ds: pd.Series, country) -> np.ndarray:
    """True for weekends and public holidays (local calendar dates)."""
    dates = ds.dt.normalize()
    lookup = {stamp: day_class(stamp.date(), country) != "wd" for stamp in dates.unique()}
    return dates.map(lookup).to_numpy(dtype=bool)


def prophet(train, horizon=HORIZON, country=None, weather=None) -> pd.DataFrame:
    """Prophet with daily + weekly seasonality (history is only ~90 days, so no yearly term)."""
    from prophet import Prophet

    _quiet_prophet()
    df, tz, _ = _prophet_input(train, country)
    model = Prophet(
        daily_seasonality=True,
        weekly_seasonality=True,
        yearly_seasonality=False,
        interval_width=0.8,
    )
    model.fit(df)
    idx, future = _prophet_future(train, horizon, tz)
    out = model.predict(future)
    return _frame(idx, out["yhat"], out["yhat_lower"], out["yhat_upper"])


def _fit_predict_offday_prophet(df, future, country, regressors=None):
    """Prophet with separate weekday / off-day daily curves (weekends + public holidays)."""
    from prophet import Prophet

    _quiet_prophet()
    for frame in (df, future):
        frame["is_offday"] = _offday_flags(frame["ds"], country)
        frame["is_workday"] = ~frame["is_offday"]

    model = Prophet(
        daily_seasonality=False,
        weekly_seasonality=False,
        yearly_seasonality=False,
        changepoint_prior_scale=0.01,
        interval_width=0.8,
    )
    model.add_seasonality("daily_workday", period=1, fourier_order=10, condition_name="is_workday")
    model.add_seasonality("daily_offday", period=1, fourier_order=10, condition_name="is_offday")
    model.add_seasonality("weekly", period=7, fourier_order=3)
    for name in regressors or []:
        model.add_regressor(name)
    model.fit(df)
    return model.predict(future)


def prophet_tuned(train, horizon=HORIZON, country=None, weather=None) -> pd.DataFrame:
    """Prophet with separate weekday / off-day curves and a stiffer trend.

    The default Prophet adds one daily curve and one weekly curve, so it cannot model that
    Saturday's (or a holiday's) shape differs from Tuesday's.
    """
    df, tz, _ = _prophet_input(train, country)
    idx, future = _prophet_future(train, horizon, tz)
    out = _fit_predict_offday_prophet(df, future, country)
    return _frame(idx, out["yhat"], out["yhat_lower"], out["yhat_upper"])


def _degree_days(temp: np.ndarray):
    return np.maximum(0.0, HDD_BASE - temp), np.maximum(0.0, temp - CDD_BASE)


def prophet_temp(train, horizon=HORIZON, country=None, weather=None) -> pd.DataFrame:
    """prophet_tuned on the last 8 weeks plus heating/cooling degree days from the temperature.

    In a backtest the "forecast" temperatures are the measured ones (perfect foresight), so the
    backtest slightly overstates what this model achieves live.
    """
    if weather is None:
        raise MissingWeather("no temperature series supplied")
    train = train.tail(24 * PROPHET_TEMP_DAYS)
    df, tz, utc = _prophet_input(train, country)
    idx, future = _prophet_future(train, horizon, tz)

    past = weather.reindex(utc).interpolate(limit=6, limit_direction="both")
    if past.isna().mean() > 0.1:
        raise MissingWeather("temperature history is incomplete")
    ahead = weather.reindex(idx)
    if ahead.isna().any():
        raise MissingWeather("no temperature forecast for the whole horizon")
    df["hdd"], df["cdd"] = _degree_days(past.ffill().bfill().to_numpy(dtype=float))
    future["hdd"], future["cdd"] = _degree_days(ahead.to_numpy(dtype=float))

    out = _fit_predict_offday_prophet(df, future, country, regressors=["hdd", "cdd"])
    return _frame(idx, out["yhat"], out["yhat_lower"], out["yhat_upper"])


# ----------------------------------------------------------------------------- composites

# Equal-weight averages of two models. The backtest reuses already computed component forecasts
# (see champion.predict_origin) so Prophet is fitted once per origin, not once per ensemble.
COMPOSITES = {
    "ensemble": ("prophet_tuned", "naive_avg3"),
    "ensemble_temp": ("prophet_temp", "naive_level"),
}


def average_frames(frames) -> pd.DataFrame:
    yhat = np.mean([f["yhat"].to_numpy() for f in frames], axis=0)
    return _frame(frames[0].index, yhat)


def run_model(name, train, horizon=HORIZON, country=None, weather=None) -> pd.DataFrame:
    """Run any model by name, composites included."""
    if name in COMPOSITES:
        return average_frames([run_model(c, train, horizon, country, weather) for c in COMPOSITES[name]])
    return MODELS[name](train, horizon, country, weather)


def ensemble(train, horizon=HORIZON, country=None, weather=None) -> pd.DataFrame:
    return run_model("ensemble", train, horizon, country, weather)


def ensemble_temp(train, horizon=HORIZON, country=None, weather=None) -> pd.DataFrame:
    return run_model("ensemble_temp", train, horizon, country, weather)


MODELS = {
    "seasonal_naive": seasonal_naive,
    "naive_avg3": naive_avg3,
    "naive_daytype": naive_daytype,
    "naive_level": naive_level,
    "ets": ets,
    "prophet": prophet,
    "prophet_tuned": prophet_tuned,
    "prophet_temp": prophet_temp,
    "ensemble": ensemble,
    "ensemble_temp": ensemble_temp,
}
# Candidates of a normal run; plain Prophet and ETS never won a backtest and stay research-only.
DEFAULT_MODELS = [
    "seasonal_naive",
    "naive_avg3",
    "naive_daytype",
    "naive_level",
    "prophet_tuned",
    "prophet_temp",
    "ensemble",
    "ensemble_temp",
]
