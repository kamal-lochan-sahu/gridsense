import numpy as np
import pandas as pd
import pytest

from pipeline import compare, models
from pipeline.history import synthetic_history, synthetic_tso
from pipeline.models import HORIZON, MissingWeather, future_index
from pipeline.trackrecord import day_ahead_frame
from pipeline.weather import synthetic_weather

from .test_step4 import class_pattern_series, temp_driven_series


def forecast_error(fn, train, truth, country="germany", weather=None, horizon=HORIZON):
    pred = fn(train, horizon, country, weather)["yhat"].to_numpy()
    return float(np.mean(np.abs(pred - truth)))


def test_naive_recent_is_exact_on_normal_and_holiday_targets():
    s = class_pattern_series()
    for origin in ("2026-12-25 00:00", "2027-01-08 00:00", "2026-12-16 00:00"):  # Christmas, Friday after holidays, Wednesday
        origin = pd.Timestamp(origin, tz="UTC")
        train = s[s.index < origin]
        truth = s.reindex(future_index(train)).to_numpy()
        np.testing.assert_allclose(models.naive_recent(train, HORIZON, "germany")["yhat"].to_numpy(), truth)


def test_naive_recent_copes_with_a_partly_known_day_before():
    """Day-ahead use: the origin is 11:00 UTC, so yesterday's evening is not known yet."""
    s = class_pattern_series()
    origin = pd.Timestamp("2026-12-16 11:00", tz="UTC")
    train = s[s.index < origin]
    horizon = 37
    truth = s.reindex(future_index(train, horizon)).to_numpy()
    pred = models.naive_recent(train, horizon, "germany")["yhat"].to_numpy()
    np.testing.assert_allclose(pred, truth)


def test_naive_recent_follows_a_falling_load_faster_than_the_three_week_average():
    idx = pd.date_range("2026-09-01", "2026-10-15", freq="1h", tz="UTC", inclusive="left", name="ds")
    days = (idx - idx[0]) / pd.Timedelta(days=1)
    series = pd.Series(30000 * (1 - 0.006 * np.asarray(days)) + 300 * idx.hour.to_numpy(), index=idx)  # -0.6% per day
    origin = pd.Timestamp("2026-10-14 00:00", tz="UTC")
    train = series[series.index < origin]
    truth = series.reindex(future_index(train)).to_numpy()
    assert forecast_error(models.naive_recent, train, truth) < 0.5 * forecast_error(models.naive_avg3, train, truth)


def test_hourly_level_factors_are_one_when_nothing_changed_and_bounded():
    s = class_pattern_series()
    np.testing.assert_allclose(models.hourly_level_factors(s, "germany"), np.ones(24), atol=1e-6)
    shifted = s.copy()
    shifted.iloc[-24 * 7 :] *= 3.0
    factors = models.hourly_level_factors(shifted, "germany")
    assert factors.min() >= models.HOURLY_FACTOR_CLIP[0] and factors.max() <= models.HOURLY_FACTOR_CLIP[1]


def test_naive_level_hourly_fixes_a_drifting_daily_shape_better_than_one_overall_level():
    s = class_pattern_series(end="2026-12-20")
    local_hour = s.index.tz_convert("Europe/Berlin").hour
    drifted = s.copy()
    evening = np.asarray(local_hour >= 17) & (np.arange(len(s)) >= len(s) - 24 * 10)
    drifted[evening] *= 0.93  # the last 10 days: evenings 7% lower, the rest unchanged
    origin = pd.Timestamp("2026-12-18 00:00", tz="UTC")
    train = drifted[drifted.index < origin]
    truth = drifted.reindex(future_index(train)).to_numpy()
    assert forecast_error(models.naive_level_hourly, train, truth) < forecast_error(models.naive_level, train, truth)


def test_ridge_temp_recovers_the_profile_and_follows_the_temperature():
    s, temp = temp_driven_series(days=70)
    origin = s.index[-1] - pd.Timedelta(hours=47)
    train = s[s.index <= origin - pd.Timedelta(hours=1)]
    truth = s.reindex(future_index(train)).to_numpy()
    err = forecast_error(models.ridge_temp, train, truth, weather=temp)
    assert err < 0.03 * truth.mean()  # synthetic data, 1% noise: a few percent at most

    idx = future_index(s)
    cold, warm = temp.copy(), temp.copy()
    cold.loc[idx], warm.loc[idx] = 0.0, 20.0
    pred_cold = models.ridge_temp(s, HORIZON, "germany", cold)["yhat"].mean()
    pred_warm = models.ridge_temp(s, HORIZON, "germany", warm)["yhat"].mean()
    assert pred_cold > pred_warm + 5000


def test_ridge_temp_needs_weather_and_rejects_implausible_forecasts():
    s = synthetic_history(days=45, seed=1)
    with pytest.raises(MissingWeather):
        models.ridge_temp(s, HORIZON, "germany", None)
    weather = synthetic_weather(s, seed=1)
    with pytest.raises(MissingWeather):
        models.ridge_temp(s, HORIZON, "germany", weather[weather.index <= s.index[-1]])
    # a window without any Saturday cannot predict a Saturday: the model must refuse, not output ~0
    start = pd.Timestamp("2026-10-06 00:00", tz="UTC")  # a Tuesday
    window = s.loc[start : start + pd.Timedelta(hours=24 * 4 - 1)]  # Tue-Fri only, ends Fri 23:00 UTC
    with pytest.raises(ValueError):
        models.ridge_temp(window, 24, "germany", synthetic_weather(window, seed=1))


def test_ensemble_ridge_is_the_mean_of_its_parts():
    s = synthetic_history(days=60, seed=2)
    w = synthetic_weather(s, seed=2)
    a = models.run_model("ridge_temp", s, HORIZON, "spain", w)["yhat"].to_numpy()
    b = models.run_model("naive_recent", s, HORIZON, "spain", w)["yhat"].to_numpy()
    np.testing.assert_allclose(models.run_model("ensemble_ridge", s, HORIZON, "spain", w)["yhat"].to_numpy(), (a + b) / 2)


def test_day_ahead_frame_has_actual_and_a_column_per_working_model():
    s = synthetic_history(days=60, seed=3)
    frame = day_ahead_frame(s, ["seasonal_naive", "naive_recent", "ridge_temp"], "germany", weather=None, n_days=5)
    assert "actual" in frame and "seasonal_naive" in frame and "naive_recent" in frame
    assert "ridge_temp" not in frame  # no weather: that model cannot run, the others still do
    assert len(frame) == 5 * 24


def test_compare_main_prints_a_table_with_the_tso_row(capsys):
    assert compare.main(["--synthetic", "--countries", "france", "--models", "naive_recent", "naive_level", "--days", "6"]) == 0
    out = capsys.readouterr().out
    assert "FRANCE" in out and "tso" in out and "naive_recent" in out and "best model:" in out


def test_compare_table_uses_the_same_hours_for_every_column():
    s = synthetic_history(days=60, seed=4)
    frame = day_ahead_frame(s, ["seasonal_naive", "naive_recent"], "germany", None, 6)
    frame["tso"] = synthetic_tso(s, seed=4).reindex(frame.index)
    frame.iloc[5, frame.columns.get_loc("naive_recent")] = np.nan  # one missing forecast hour
    table = compare.compare_table(frame, ["seasonal_naive", "naive_recent"])
    assert set(table.index) == {"seasonal_naive", "naive_recent", "tso"}
    assert table["mape_all"].notna().all()
