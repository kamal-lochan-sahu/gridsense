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
RECENT_DAYS = {"wd": 5, "sat": 3, "sun": 3}  # how many recent same-type days naive_recent averages
RECENT_LOOKBACK_DAYS = 28
HOURLY_FACTOR_CLIP = (0.85, 1.15)
RIDGE_DAYS = 56  # training window of ridge_temp
RIDGE_HALF_LIFE_DAYS = 14.0  # recent hours count more
RIDGE_ALPHA = 1.0  # penalty on the temperature and trend terms only
RIDGE_DUMMY_ALPHA = 1e-3  # the hour x day-type dummies behave like intercepts: (almost) unpenalised
N_DUMMIES = 72
TIME_BLOCKS = ((0, 5), (6, 11), (12, 17), (18, 23))  # local hours; temperature acts differently in each


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


# ----------------------------------------------------------------------------- recent-days family


def recent_reference(train: pd.Series, idx: pd.DatetimeIndex, country) -> np.ndarray:
    """Mean of the same local hour on the most recent days of the same type (see pipeline.daytype).

    Unlike the 1-3 weeks-back references this follows a drifting load (seasonal change) within
    days. Hours that are not known yet (the part of yesterday after the forecast origin) are
    skipped, so the next older day of the same type is used for them.
    """
    tz = tz_of(country)
    lookup = _train_by_local_time(train, tz)
    local = idx.tz_convert(tz).tz_localize(None)
    dates = local.normalize()
    out = np.full(len(local), np.nan)
    for day_stamp in pd.unique(dates):
        stamp = pd.Timestamp(day_stamp)
        day = stamp.date()
        cls = day_class(day, country)
        mask = np.asarray(dates == stamp)
        times = local[mask]
        rows = []
        for back in range(1, RECENT_LOOKBACK_DAYS + 1):
            candidate = day - timedelta(days=back)
            if day_class(candidate, country) == cls:
                rows.append(lookup.reindex(times - pd.Timedelta(days=back)).to_numpy())
        if not rows:
            continue
        stack = np.vstack(rows)  # most recent day first
        valid = ~np.isnan(stack)
        take = valid & (np.cumsum(valid, axis=0) <= RECENT_DAYS[cls])
        count = take.sum(axis=0)
        out[mask] = np.where(count > 0, np.where(take, stack, 0.0).sum(axis=0) / np.maximum(count, 1), np.nan)
    return out


def naive_recent(train, horizon=HORIZON, country=None, weather=None) -> pd.DataFrame:
    """Average of the last 5 weekdays (3 Saturdays / Sundays-and-holidays) at the same hour."""
    idx = future_index(train, horizon)
    ref = recent_reference(train, idx, country)
    fallback = naive_daytype(train, horizon, country)["yhat"].to_numpy()
    return _frame(idx, np.where(np.isnan(ref), fallback, ref))


def hourly_level_factors(train: pd.Series, country, hours: int = LEVEL_HOURS) -> np.ndarray:
    """24 multipliers (one per local hour): how the last week's load compares with the reference.

    One overall level factor cannot fix a daily *shape* that is drifting (e.g. evenings falling
    faster than mornings in autumn); one factor per hour of the day can.
    """
    tz = tz_of(country)
    recent = train.index[-hours:]
    ref = daytype_reference(train, recent, country)
    actual = train.reindex(recent).to_numpy(dtype=float)
    local_hour = recent.tz_convert(tz).hour.to_numpy()
    factors = np.ones(24)
    for hour in range(24):
        ok = (local_hour == hour) & np.isfinite(ref) & np.isfinite(actual)
        if ok.sum() >= 3:
            factors[hour] = actual[ok].sum() / ref[ok].sum()
    smoothed = (np.roll(factors, 1) + 2 * factors + np.roll(factors, -1)) / 4  # neighbouring hours share information
    return np.clip(smoothed, *HOURLY_FACTOR_CLIP)


def naive_level_hourly(train, horizon=HORIZON, country=None, weather=None) -> pd.DataFrame:
    """naive_daytype with a separate level correction for every hour of the day."""
    base = naive_daytype(train, horizon, country)
    hours = base.index.tz_convert(tz_of(country)).hour.to_numpy()
    return _frame(base.index, base["yhat"].to_numpy() * hourly_level_factors(train, country)[hours])


# ----------------------------------------------------------------------------- regression


def _day_classes(local_dates, country) -> np.ndarray:
    lookup = {d: day_class(d, country) for d in set(local_dates)}
    return np.array([lookup[d] for d in local_dates])


def _ridge_features(idx: pd.DatetimeIndex, country, temp: np.ndarray, t0: pd.Timestamp) -> np.ndarray:
    """Hour-of-day x day-type dummies, heating/cooling degree days per part of the day, a trend."""
    local = idx.tz_convert(tz_of(country))
    hour = local.hour.to_numpy()
    classes = _day_classes(list(local.date), country)
    cols = []
    for cls in ("wd", "sat", "sun"):
        for h in range(24):
            cols.append(((classes == cls) & (hour == h)).astype(float))
    hdd, cdd = _degree_days(temp)
    for start, end in TIME_BLOCKS:
        block = ((hour >= start) & (hour <= end)).astype(float)
        cols.append(block * hdd / 10.0)
        cols.append(block * cdd / 10.0)
    cols.append(((idx - t0) / pd.Timedelta(days=1)).to_numpy(dtype=float) / 30.0)
    return np.column_stack(cols)


def ridge_temp(train, horizon=HORIZON, country=None, weather=None) -> pd.DataFrame:
    """Weighted ridge regression on calendar + temperature, fitted on the last 8 weeks.

    Recent hours get more weight (half-life two weeks) so a drifting load is followed. In a
    backtest the temperatures are the measured ones (perfect foresight), as for prophet_temp.
    """
    if weather is None:
        raise MissingWeather("no temperature series supplied")
    train = train.tail(24 * RIDGE_DAYS)
    idx = future_index(train, horizon)
    past = weather.reindex(train.index).interpolate(limit=6, limit_direction="both")
    if past.isna().mean() > 0.1:
        raise MissingWeather("temperature history is incomplete")
    ahead = weather.reindex(idx)
    if ahead.isna().any():
        raise MissingWeather("no temperature forecast for the whole horizon")

    t0 = train.index[-1]
    x_train = _ridge_features(train.index, country, past.ffill().bfill().to_numpy(dtype=float), t0)
    x_future = _ridge_features(idx, country, ahead.to_numpy(dtype=float), t0)
    y = train.to_numpy(dtype=float) / 1000.0
    age_days = ((t0 - train.index) / pd.Timedelta(days=1)).to_numpy(dtype=float)
    weights = 0.5 ** (age_days / RIDGE_HALF_LIFE_DAYS)
    xw = x_train * weights[:, None]
    penalty = np.r_[np.full(N_DUMMIES, RIDGE_DUMMY_ALPHA), np.full(x_train.shape[1] - N_DUMMIES, RIDGE_ALPHA)]
    beta = np.linalg.solve(x_train.T @ xw + np.diag(penalty), xw.T @ y)
    yhat = (x_future @ beta) * 1000.0
    if not np.isfinite(yhat).all() or yhat.min() < 0.5 * float(train.tail(168).min()):
        raise ValueError("ridge forecast is implausible")  # e.g. a day type that is missing from the window
    return _frame(idx, yhat)


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
    "ensemble_ridge": ("ridge_temp", "naive_recent"),
}


def average_frames(frames) -> pd.DataFrame:
    yhat = np.mean([f["yhat"].to_numpy() for f in frames], axis=0)
    return _frame(frames[0].index, yhat)


# Error-corrected variants: the base model's forecast is scaled by how wrong the same model was
# over the last 24 hours that are already known (damped, clipped). It follows a level that moved
# since yesterday, which is what leaves France and Poland biased low in autumn.
ADJUSTED = {
    "naive_level_adj": "naive_level",
    "ridge_temp_adj": "ridge_temp",
    "prophet_temp_adj": "prophet_temp",
    "ensemble_temp_adj": "ensemble_temp",
}
ADJUST_HOURS = 24
ADJUST_STRENGTH = 0.6  # share of the recent relative error that is carried over
ADJUST_CLIP = (0.92, 1.08)  # never move a forecast by more than 8%
MIN_ADJUST_HOURS = 12


def adjustment_factor(actual, predicted) -> float:
    """Multiplier for the next forecast from the model's own recent error (1.0 if unknown)."""
    a, p = np.asarray(actual, dtype=float), np.asarray(predicted, dtype=float)
    ok = np.isfinite(a) & np.isfinite(p) & (p > 0)
    if ok.sum() < MIN_ADJUST_HOURS:
        return 1.0
    ratio = a[ok].sum() / p[ok].sum()
    return float(np.clip(1 + ADJUST_STRENGTH * (ratio - 1), *ADJUST_CLIP))


def run_model(name, train, horizon=HORIZON, country=None, weather=None) -> pd.DataFrame:
    """Run any model by name, composites and error-corrected variants included."""
    if name in COMPOSITES:
        return average_frames([run_model(c, train, horizon, country, weather) for c in COMPOSITES[name]])
    if name in ADJUSTED:
        base = ADJUSTED[name]
        now = run_model(base, train, horizon, country, weather)
        past = train.iloc[:-ADJUST_HOURS]
        if len(past) < 24 * 14:
            return now
        before = run_model(base, past, ADJUST_HOURS, country, weather)  # covers exactly the last 24 known hours
        factor = adjustment_factor(train.reindex(before.index).to_numpy(), before["yhat"].to_numpy())
        return _frame(now.index, now["yhat"].to_numpy() * factor)
    return MODELS[name](train, horizon, country, weather)


def ensemble(train, horizon=HORIZON, country=None, weather=None) -> pd.DataFrame:
    return run_model("ensemble", train, horizon, country, weather)


def ensemble_temp(train, horizon=HORIZON, country=None, weather=None) -> pd.DataFrame:
    return run_model("ensemble_temp", train, horizon, country, weather)


def ensemble_ridge(train, horizon=HORIZON, country=None, weather=None) -> pd.DataFrame:
    return run_model("ensemble_ridge", train, horizon, country, weather)


def naive_level_adj(train, horizon=HORIZON, country=None, weather=None) -> pd.DataFrame:
    return run_model("naive_level_adj", train, horizon, country, weather)


def ridge_temp_adj(train, horizon=HORIZON, country=None, weather=None) -> pd.DataFrame:
    return run_model("ridge_temp_adj", train, horizon, country, weather)


def prophet_temp_adj(train, horizon=HORIZON, country=None, weather=None) -> pd.DataFrame:
    return run_model("prophet_temp_adj", train, horizon, country, weather)


def ensemble_temp_adj(train, horizon=HORIZON, country=None, weather=None) -> pd.DataFrame:
    return run_model("ensemble_temp_adj", train, horizon, country, weather)


MODELS = {
    "seasonal_naive": seasonal_naive,
    "naive_avg3": naive_avg3,
    "naive_daytype": naive_daytype,
    "naive_level": naive_level,
    "naive_recent": naive_recent,
    "naive_level_hourly": naive_level_hourly,
    "ets": ets,
    "prophet": prophet,
    "prophet_tuned": prophet_tuned,
    "prophet_temp": prophet_temp,
    "ridge_temp": ridge_temp,
    "ensemble": ensemble,
    "ensemble_temp": ensemble_temp,
    "ensemble_ridge": ensemble_ridge,
    "naive_level_adj": naive_level_adj,
    "ridge_temp_adj": ridge_temp_adj,
    "prophet_temp_adj": prophet_temp_adj,
    "ensemble_temp_adj": ensemble_temp_adj,
}
# Candidates of a normal run; plain Prophet and ETS never won a backtest and stay research-only.
DEFAULT_MODELS = [
    "seasonal_naive",
    "naive_avg3",
    "naive_daytype",
    "naive_level",
    "naive_recent",
    "naive_level_hourly",
    "prophet_tuned",
    "prophet_temp",
    "ridge_temp",
    "ensemble",
    "ensemble_temp",
    "ensemble_ridge",
    "naive_level_adj",
    "ridge_temp_adj",
    "prophet_temp_adj",
    "ensemble_temp_adj",
]
