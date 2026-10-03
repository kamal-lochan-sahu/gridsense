"""Forecast models. Each takes an hourly UTC load Series and returns the next ``horizon`` hours.

Return value: DataFrame indexed by ``ds`` (UTC) with columns yhat, yhat_lower, yhat_upper.
Models without prediction intervals return NaN for the bounds.
"""
import logging
import warnings

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore", message=".*Optimization failed to converge.*")


def _quiet_prophet() -> None:
    """Prophet/cmdstanpy configure their own loggers on import, so silence them afterwards."""
    for name in ("cmdstanpy", "prophet", "prophet.plot"):
        logging.getLogger(name).setLevel(logging.CRITICAL)

HORIZON = 24
DEFAULT_TZ = "Europe/Berlin"
COUNTRY_TZ = {
    "germany": "Europe/Berlin",
    "france": "Europe/Paris",
    "spain": "Europe/Madrid",
    "poland": "Europe/Warsaw",
}


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


def seasonal_naive(train: pd.Series, horizon: int = HORIZON, country=None) -> pd.DataFrame:
    """Same hour one week ago (falls back to one day ago). The baseline every model must beat."""
    idx = future_index(train, horizon)
    tz = tz_of(country)
    weekly = train.reindex(shift_local(idx, 7, tz)).to_numpy(dtype=float)
    daily = train.reindex(shift_local(idx, 1, tz)).to_numpy(dtype=float)
    yhat = np.where(np.isnan(weekly), daily, weekly)
    return _frame(idx, yhat)


def ets(train: pd.Series, horizon: int = HORIZON, country=None) -> pd.DataFrame:
    """Holt-Winters with a 24h seasonal cycle on the last 4 weeks."""
    from statsmodels.tsa.holtwinters import ExponentialSmoothing

    values = train.tail(24 * 28).to_numpy(dtype=float)
    fit = ExponentialSmoothing(
        values, trend="add", damped_trend=True, seasonal="add", seasonal_periods=24
    ).fit()
    return _frame(future_index(train, horizon), fit.forecast(horizon))


def _prophet_input(train: pd.Series, country):
    """Training frame on the local wall clock (so the daily curve survives DST changes)."""
    tz = tz_of(country)
    df = pd.DataFrame({"ds": local_naive(train.index, tz), "y": train.to_numpy(dtype=float)})
    # The repeated hour when clocks go back would give duplicate timestamps.
    return df.drop_duplicates("ds", keep="first").reset_index(drop=True), tz


def _prophet_future(train: pd.Series, horizon: int, tz: str):
    idx = future_index(train, horizon)
    return idx, pd.DataFrame({"ds": local_naive(idx, tz)})


def prophet(train: pd.Series, horizon: int = HORIZON, country=None) -> pd.DataFrame:
    """Prophet with daily + weekly seasonality (history is only ~90 days, so no yearly term)."""
    from prophet import Prophet

    _quiet_prophet()
    df, tz = _prophet_input(train, country)
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


def naive_avg3(train: pd.Series, horizon: int = HORIZON, country=None) -> pd.DataFrame:
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


def prophet_tuned(train: pd.Series, horizon: int = HORIZON, country=None) -> pd.DataFrame:
    """Prophet with separate weekday/weekend daily curves and a stiffer trend.

    The default Prophet adds one daily curve and one weekly curve, so it cannot model that
    Saturday's shape differs from Tuesday's. Conditional seasonality fixes that.
    """
    from prophet import Prophet

    _quiet_prophet()
    df, tz = _prophet_input(train, country)
    df["is_weekend"] = (df["ds"].dt.dayofweek >= 5).to_numpy()
    df["is_weekday"] = ~df["is_weekend"]

    model = Prophet(
        daily_seasonality=False,
        weekly_seasonality=False,
        yearly_seasonality=False,
        changepoint_prior_scale=0.01,
        interval_width=0.8,
    )
    model.add_seasonality("daily_weekday", period=1, fourier_order=10, condition_name="is_weekday")
    model.add_seasonality("daily_weekend", period=1, fourier_order=10, condition_name="is_weekend")
    model.add_seasonality("weekly", period=7, fourier_order=3)
    model.fit(df)

    idx, future = _prophet_future(train, horizon, tz)
    future["is_weekend"] = (future["ds"].dt.dayofweek >= 5).to_numpy()
    future["is_weekday"] = ~future["is_weekend"]
    out = model.predict(future)
    return _frame(idx, out["yhat"], out["yhat_lower"], out["yhat_upper"])


def ensemble(train: pd.Series, horizon: int = HORIZON, country=None) -> pd.DataFrame:
    """Equal-weight average of tuned Prophet and the 3-week naive."""
    a = prophet_tuned(train, horizon, country)["yhat"].to_numpy()
    b = naive_avg3(train, horizon, country)["yhat"].to_numpy()
    return _frame(future_index(train, horizon), (a + b) / 2)


MODELS = {
    "seasonal_naive": seasonal_naive,
    "naive_avg3": naive_avg3,
    "ets": ets,
    "prophet": prophet,
    "prophet_tuned": prophet_tuned,
    "ensemble": ensemble,
}
DEFAULT_MODELS = ["seasonal_naive", "naive_avg3", "prophet", "prophet_tuned", "ensemble"]
