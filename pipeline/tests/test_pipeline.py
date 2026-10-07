import numpy as np
import pandas as pd
import pytest

from pipeline.backtest import rolling_origins, run_backtest, score
from pipeline.history import synthetic_history, to_hourly
from pipeline.models import HORIZON, MODELS, future_index, naive_avg3, seasonal_naive


def periodic_series(days=30):
    """Perfectly weekly-periodic hourly series."""
    idx = pd.date_range("2026-01-01", periods=days * 24, freq="1h", tz="UTC", name="ds")
    pattern = np.arange(24 * 7, dtype=float) + 1000
    return pd.Series(np.resize(pattern, len(idx)), index=idx)


def test_to_hourly_resamples_quarter_hours_and_drops_zeros():
    points = [
        {"time": "2026-01-01T00:00Z", "load_mw": 100.0},
        {"time": "2026-01-01T00:15Z", "load_mw": 200.0},
        {"time": "2026-01-01T00:30Z", "load_mw": 0.0},  # glitch, ignored
        {"time": "2026-01-01T00:45Z", "load_mw": 300.0},
        {"time": "2026-01-01T01:00Z", "load_mw": 400.0},
    ]
    hourly = to_hourly(points)
    assert hourly.iloc[0] == pytest.approx(200.0)
    assert hourly.iloc[1] == pytest.approx(400.0)
    assert str(hourly.index.tz) == "UTC"


def test_to_hourly_fills_only_short_gaps():
    times = pd.date_range("2026-01-01", periods=10, freq="1h", tz="UTC")
    points = [{"time": t.strftime("%Y-%m-%dT%H:%MZ"), "load_mw": 100.0} for t in times]
    points = [p for i, p in enumerate(points) if i not in (3, 4)]  # 2-hour gap: filled
    assert len(to_hourly(points)) == 10
    points = [p for i, p in enumerate(points) if i not in (6, 7, 8, 9)]  # long gap at the end
    assert len(to_hourly(points)) < 10


def test_seasonal_naive_is_exact_on_weekly_pattern():
    s = periodic_series()
    train, truth = s.iloc[:-24], s.iloc[-24:]
    pred = seasonal_naive(train)
    assert list(pred.index) == list(truth.index)
    np.testing.assert_allclose(pred["yhat"].to_numpy(), truth.to_numpy())


def test_seasonal_naive_falls_back_to_yesterday_when_last_week_missing():
    s = periodic_series(days=3)  # no data from a week ago
    pred = seasonal_naive(s)
    assert not pred["yhat"].isna().any()


def test_rolling_origins_have_full_actuals():
    s = synthetic_history(days=30)
    origins = rolling_origins(s, 5)
    assert len(origins) == 5 and origins == sorted(origins)
    assert origins[-1] + pd.Timedelta(hours=HORIZON - 1) <= s.index[-1]
    assert all(o.hour == 0 for o in origins)


def test_score_handles_missing_and_interval_coverage():
    idx = pd.date_range("2026-01-01", periods=24, freq="1h", tz="UTC")
    pred = pd.DataFrame({"yhat": 100.0, "yhat_lower": 90.0, "yhat_upper": 110.0}, index=idx)
    out = score(np.full(24, 105.0), pred)
    assert out["mae"] == pytest.approx(5.0)
    assert out["coverage"] == pytest.approx(1.0)
    assert np.isnan(score(np.full(24, np.nan), pred)["mae"])


@pytest.mark.parametrize("name", list(MODELS))
def test_every_model_returns_24_finite_hours(name):
    from pipeline.weather import synthetic_weather

    s = synthetic_history(days=45)
    pred = MODELS[name](s, HORIZON, "germany", synthetic_weather(s))
    assert list(pred.index) == list(future_index(s))
    assert len(pred) == HORIZON and np.isfinite(pred["yhat"]).all()


def test_backtest_survives_a_failing_model(monkeypatch):
    def boom(train, horizon=24, country=None, weather=None):
        raise RuntimeError("model exploded")

    monkeypatch.setitem(MODELS, "broken", boom)
    res = run_backtest(synthetic_history(days=45), ["seasonal_naive", "broken"], n_origins=2)
    assert set(res["model"]) == {"seasonal_naive", "broken"}
    assert res.loc[res["model"] == "broken", "error"].str.contains("exploded").all()
    assert res.loc[res["model"] == "seasonal_naive", "mape"].notna().all()


def test_naive_avg3_exact_on_weekly_pattern_and_averages_noise():
    s = periodic_series()
    pred = naive_avg3(s.iloc[:-24])
    np.testing.assert_allclose(pred["yhat"].to_numpy(), s.iloc[-24:].to_numpy())

    noisy = s.copy()
    idx = future_index(s.iloc[:-24])
    noisy.loc[idx[0] - pd.Timedelta(days=7)] += 3000  # one-off spike a week ago
    spike_naive = seasonal_naive(noisy.iloc[:-24])["yhat"].iloc[0]
    spike_avg = naive_avg3(noisy.iloc[:-24])["yhat"].iloc[0]
    truth = s.iloc[-24]
    assert abs(spike_avg - truth) < abs(spike_naive - truth)


def local_pattern_series(start="2026-10-01", end="2026-11-10", tz="Europe/Berlin"):
    """Load that depends only on local wall-clock hour and weekday (like real demand)."""
    idx = pd.date_range(start, end, freq="1h", tz="UTC", inclusive="left", name="ds")
    local = idx.tz_convert(tz)
    values = 1000 + 50 * local.hour + 300 * (local.dayofweek >= 5)
    return pd.Series(np.asarray(values, dtype=float), index=idx)


def test_naive_models_stay_exact_across_the_october_dst_change():
    from pipeline.models import naive_avg3

    s = local_pattern_series()
    # 2026-10-25: Europe/Berlin goes back from CEST to CET. Forecast 3 days after the change.
    origin = pd.Timestamp("2026-10-28 00:00", tz="UTC")
    train, truth = s[s.index < origin], s.reindex(future_index(s[s.index < origin]))
    for fn in (seasonal_naive, naive_avg3):
        pred = fn(train, HORIZON, "germany")
        np.testing.assert_allclose(pred["yhat"].to_numpy(), truth.to_numpy())


def test_utc_shift_would_have_been_wrong_after_dst():
    """Documents why shift_local exists: a UTC-based week shift is off by an hour here."""
    s = local_pattern_series()
    origin = pd.Timestamp("2026-10-28 00:00", tz="UTC")
    idx = future_index(s[s.index < origin])
    naive_utc = s.reindex(idx - pd.Timedelta(days=7)).to_numpy()
    assert np.abs(naive_utc - s.reindex(idx).to_numpy()).max() > 0


def test_shift_local_handles_ambiguous_and_missing_hours():
    from pipeline.models import shift_local

    # 2026-11-01 local 02:00-03:00 (Berlin) is the repeated hour exactly one week after the
    # change; shifting a week earlier must not raise.
    idx = pd.date_range("2026-11-01 00:00", periods=6, freq="1h", tz="UTC")
    out = shift_local(idx, 7, "Europe/Berlin")
    assert len(out) == len(idx)


def test_prophet_models_accept_series_spanning_dst():
    from pipeline.models import prophet_tuned

    s = local_pattern_series(start="2026-09-15", end="2026-10-30")
    pred = prophet_tuned(s, HORIZON, "germany")
    assert len(pred) == HORIZON and np.isfinite(pred["yhat"]).all()

