from datetime import date

import numpy as np
import pandas as pd
import pytest
import requests

from pipeline import champion as champion_module
from pipeline import models, run as run_module, weather as weather_module
from pipeline.champion import collect_predictions
from pipeline.daytype import day_class, is_holiday
from pipeline.history import synthetic_history
from pipeline.models import HORIZON, MissingWeather, future_index
from pipeline.weather import WeatherError, load_weather, synthetic_weather


# ------------------------------------------------------------------ holidays / day classes


def test_national_holidays_come_from_the_calendar():
    assert is_holiday(date(2026, 12, 25), "germany")
    assert not is_holiday(date(2026, 12, 24), "germany")
    assert is_holiday(date(2026, 11, 11), "france") and is_holiday(date(2026, 11, 11), "poland")
    assert is_holiday(date(2026, 10, 12), "spain") and not is_holiday(date(2026, 11, 11), "spain")
    assert not is_holiday(date(2026, 12, 25), "atlantis")  # unknown country: no holidays


def test_day_classes():
    assert day_class(date(2026, 12, 25), "germany") == "sun"  # Friday holiday behaves like Sunday
    assert day_class(date(2026, 10, 3), "germany") == "sat"  # holiday on a Saturday stays Saturday
    assert day_class(date(2026, 10, 4), "germany") == "sun"
    assert day_class(date(2026, 10, 6), "germany") == "wd"


def class_pattern_series(start="2026-10-15", end="2027-01-10", tz="Europe/Berlin", country="germany", growth=None):
    """Load that depends only on the local hour and the day class (weekday/Saturday/Sunday-like)."""
    idx = pd.date_range(start, end, freq="1h", tz="UTC", inclusive="left", name="ds")
    local = idx.tz_convert(tz)
    shape = {"wd": 1500.0, "sat": 800.0, "sun": 300.0}
    values = [
        20000 + shape[day_class(ts.date(), country)] + 40 * ts.hour for ts in local
    ]
    series = pd.Series(np.asarray(values, dtype=float), index=idx)
    if growth:
        series.iloc[-growth[0] :] *= growth[1]
    return series


def test_naive_daytype_is_exact_on_a_public_holiday_where_seasonal_naive_is_not():
    s = class_pattern_series()
    origin = pd.Timestamp("2026-12-25 00:00", tz="UTC")  # 01:00 on Christmas Day in Berlin
    train, truth = s[s.index < origin], s.reindex(future_index(s[s.index < origin]))
    pred = models.naive_daytype(train, HORIZON, "germany")
    np.testing.assert_allclose(pred["yhat"].to_numpy(), truth.to_numpy())
    wrong = models.seasonal_naive(train, HORIZON, "germany")
    assert np.abs(wrong["yhat"].to_numpy() - truth.to_numpy()).max() > 500


def test_naive_daytype_skips_holidays_in_the_reference_weeks():
    s = class_pattern_series()
    origin = pd.Timestamp("2027-01-08 00:00", tz="UTC")  # a Friday; Jan 1 and Dec 25 were holidays
    train, truth = s[s.index < origin], s.reindex(future_index(s[s.index < origin]))
    np.testing.assert_allclose(
        models.naive_daytype(train, HORIZON, "germany")["yhat"].to_numpy(), truth.to_numpy()
    )
    assert np.abs(models.seasonal_naive(train, HORIZON, "germany")["yhat"].to_numpy() - truth.to_numpy()).max() > 500


def test_level_factor_is_one_when_nothing_changed_and_clipped_when_extreme():
    s = class_pattern_series()
    assert models.level_factor(s, "germany") == pytest.approx(1.0, abs=1e-6)
    jumped = class_pattern_series(growth=(24 * 14, 1.6))
    assert models.level_factor(jumped, "germany") == pytest.approx(models.LEVEL_CLIP[1])


def test_naive_level_follows_a_level_shift_better_than_naive_daytype():
    s = class_pattern_series(end="2026-12-20", growth=(24 * 10, 1.06))
    origin = pd.Timestamp("2026-12-17 00:00", tz="UTC")
    full = class_pattern_series(end="2026-12-20", growth=(24 * 10, 1.06))
    train = full[full.index < origin]
    truth = full.reindex(future_index(train)).to_numpy()
    err_level = np.abs(models.naive_level(train, HORIZON, "germany")["yhat"].to_numpy() - truth).mean()
    err_plain = np.abs(models.naive_daytype(train, HORIZON, "germany")["yhat"].to_numpy() - truth).mean()
    assert err_level < err_plain


def test_offday_flags_include_holidays():
    ds = pd.Series(pd.to_datetime(["2026-12-24 10:00", "2026-12-25 10:00", "2026-12-26 10:00", "2026-12-28 10:00"]))
    assert list(models._offday_flags(ds, "germany")) == [False, True, True, False]


# ------------------------------------------------------------------ temperature


def city_payload(temps_by_city, missing_hours=()):
    times = [f"2026-10-04T{h:02d}:00" for h in range(4)]
    out = []
    for t in temps_by_city:
        values = [None if h in missing_hours and t == temps_by_city[0] else float(t) for h in range(4)]
        out.append({"hourly": {"time": times, "temperature_2m": values}})
    return out


class FakeResponse:
    def __init__(self, status=200, body=None):
        self.status_code, self._body = status, body

    def json(self):
        if isinstance(self._body, Exception):
            raise self._body
        return self._body


def test_load_weather_returns_population_weighted_temperature(monkeypatch):
    cities = weather_module.CITIES["germany"]
    temps = [10, 12, 14, 16, 18]
    weights = np.array([c[2] for c in cities])
    monkeypatch.setattr(requests, "get", lambda url, params, timeout: FakeResponse(200, city_payload(temps)))
    series = load_weather("germany", 90)
    assert len(series) == 4 and str(series.index.tz) == "UTC"
    assert series.iloc[0] == pytest.approx(float(np.average(temps, weights=weights)))


def test_load_weather_renormalises_weights_when_a_city_has_no_value(monkeypatch):
    cities = weather_module.CITIES["germany"]
    temps = [10, 12, 14, 16, 18]
    monkeypatch.setattr(
        requests, "get", lambda url, params, timeout: FakeResponse(200, city_payload(temps, missing_hours=(1,)))
    )
    series = load_weather("germany", 90)
    weights = np.array([c[2] for c in cities])[1:]
    assert series.iloc[1] == pytest.approx(float(np.average(temps[1:], weights=weights)))


@pytest.mark.parametrize(
    "responses",
    [
        [FakeResponse(400, None)],
        [FakeResponse(500, None)] * 3,
        [FakeResponse(200, ValueError("not json"))],
        [FakeResponse(200, {"hourly": {}})],  # one location instead of five
        [FakeResponse(200, [{"hourly": {"time": ["2026-10-04T00:00"], "temperature_2m": [None]}}] * 5)],
    ],
    ids=["bad-request", "server-error-3x", "not-json", "wrong-shape", "all-missing"],
)
def test_load_weather_failures_raise_weather_error(monkeypatch, responses):
    calls = iter(responses + [responses[-1]] * 3)
    monkeypatch.setattr(requests, "get", lambda url, params, timeout: next(calls))
    monkeypatch.setattr(weather_module.time, "sleep", lambda s: None)
    with pytest.raises(WeatherError):
        load_weather("germany", 90)


def test_load_weather_retries_network_errors_then_succeeds(monkeypatch):
    attempts = {"n": 0}

    def flaky(url, params, timeout):
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise requests.ConnectionError("boom")
        return FakeResponse(200, city_payload([10, 12, 14, 16, 18]))

    monkeypatch.setattr(requests, "get", flaky)
    monkeypatch.setattr(weather_module.time, "sleep", lambda s: None)
    assert len(load_weather("germany", 90)) == 4 and attempts["n"] == 3


def temp_driven_series(days=70, seed=0):
    base = synthetic_history(days, seed=seed, base=30000.0)
    temp = synthetic_weather(base, extra_hours=72, seed=seed)
    hdd = np.maximum(0.0, models.HDD_BASE - temp.reindex(base.index).to_numpy())
    return base + 1500.0 * hdd, temp


def test_temperature_models_need_weather():
    s, _ = temp_driven_series(days=45)
    for name in ("prophet_temp", "ensemble_temp"):
        with pytest.raises(MissingWeather):
            models.run_model(name, s, HORIZON, "germany", None)


def test_prophet_temp_needs_temperatures_for_the_whole_horizon():
    s, temp = temp_driven_series(days=45)
    with pytest.raises(MissingWeather):
        models.prophet_temp(s, HORIZON, "germany", temp[temp.index <= s.index[-1]])


def test_prophet_temp_responds_to_the_temperature_forecast():
    s, temp = temp_driven_series(days=70)
    idx = future_index(s)
    cold, warm = temp.copy(), temp.copy()
    cold.loc[idx], warm.loc[idx] = 0.0, 20.0
    pred_cold = models.prophet_temp(s, HORIZON, "germany", cold)["yhat"].mean()
    pred_warm = models.prophet_temp(s, HORIZON, "germany", warm)["yhat"].mean()
    assert pred_cold > pred_warm + 5000  # ~16 degree-days * 1500 MW


# ------------------------------------------------------------------ composites and wiring


def test_ensembles_reuse_component_forecasts(monkeypatch):
    calls = {"prophet_tuned": 0}
    original = models.MODELS["prophet_tuned"]

    def counting(*args, **kwargs):
        calls["prophet_tuned"] += 1
        return original(*args, **kwargs)

    monkeypatch.setitem(models.MODELS, "prophet_tuned", counting)
    s = synthetic_history(days=45)
    preds, failures = collect_predictions(s, ["prophet_tuned", "naive_avg3", "ensemble"], "germany", 3)
    assert calls["prophet_tuned"] == 3  # once per origin, shared by the ensemble
    assert set(preds["model"]) == {"prophet_tuned", "naive_avg3", "ensemble"}
    ens = preds[preds["model"] == "ensemble"].reset_index(drop=True)
    parts = [preds[preds["model"] == m].reset_index(drop=True)["yhat"] for m in ("prophet_tuned", "naive_avg3")]
    np.testing.assert_allclose(ens["yhat"], (parts[0] + parts[1]) / 2)


def test_temperature_candidates_are_skipped_without_weather():
    s = synthetic_history(days=45)
    preds, failures = collect_predictions(s, ["seasonal_naive", "prophet_temp", "ensemble_temp"], "germany", 3, weather=None)
    assert set(preds["model"]) == {"seasonal_naive"}
    assert failures["prophet_temp"] == 3 and failures["ensemble_temp"] == 3


def test_run_without_weather_never_picks_a_temperature_model(tmp_path):
    out = tmp_path / "forecast.json"
    code = run_module.main(
        ["--synthetic", "--no-weather", "--countries", "france", "--candidates", "seasonal_naive", "prophet_temp",
         "--origins", "4", "--out", str(out)]
    )
    import json

    entry = json.loads(out.read_text())["countries"]["france"]
    assert code == 0 and entry["model"] == "seasonal_naive" and entry["inputs"] == {"temperature": False}
    assert entry["backtest"]["failures"] == {"prophet_temp": 4}


def test_entry_with_weather_reports_temperature_input_flag():
    s = synthetic_history(days=60, seed=5)
    entry = run_module.build_country_entry(
        "germany", s, ["seasonal_naive", "naive_level", "prophet_temp"], 4, synthetic_weather(s, seed=5)
    )
    assert entry["inputs"]["temperature"] is (entry["model"] in run_module.TEMPERATURE_MODELS)
    assert entry["model_label"] == run_module.LABELS[entry["model"]]
