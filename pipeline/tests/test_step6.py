import numpy as np
import pandas as pd
import pytest

from pipeline import champion, models
from pipeline.champion import collect_predictions, predict_origin
from pipeline.history import synthetic_history
from pipeline.models import HORIZON, MissingWeather, adjustment_factor, future_index
from pipeline.weather import synthetic_weather

from .test_step4 import class_pattern_series


def test_adjustment_factor_follows_the_recent_error_damped_and_clipped():
    assert adjustment_factor(np.full(24, 100.0), np.full(24, 100.0)) == 1.0
    assert adjustment_factor(np.full(24, 105.0), np.full(24, 100.0)) == pytest.approx(1 + models.ADJUST_STRENGTH * 0.05)
    assert adjustment_factor(np.full(24, 95.0), np.full(24, 100.0)) < 1.0
    assert adjustment_factor(np.full(24, 300.0), np.full(24, 100.0)) == models.ADJUST_CLIP[1]
    assert adjustment_factor(np.full(24, 1.0), np.full(24, 100.0)) == models.ADJUST_CLIP[0]
    assert adjustment_factor(np.full(5, 130.0), np.full(5, 100.0)) == 1.0  # too little information
    assert adjustment_factor([np.nan] * 24, np.full(24, 100.0)) == 1.0


def shocked_series(factor=1.05):
    """Class-pattern load whose last 48 hours (before and after the origin) are `factor` times higher."""
    s = class_pattern_series(end="2026-12-20")
    origin = pd.Timestamp("2026-12-17 00:00", tz="UTC")
    s = s.copy()
    s[(s.index >= origin - pd.Timedelta(hours=24)) & (s.index < origin + pd.Timedelta(hours=24))] *= factor
    return s, origin


def test_the_corrected_model_follows_a_level_that_moved_yesterday():
    s, origin = shocked_series()
    train = s[s.index < origin]
    truth = s.reindex(future_index(train)).to_numpy()
    base = models.run_model("naive_level", train, HORIZON, "germany")["yhat"].to_numpy()
    adjusted = models.run_model("naive_level_adj", train, HORIZON, "germany")["yhat"].to_numpy()
    assert np.mean(np.abs(adjusted - truth)) < 0.7 * np.mean(np.abs(base - truth))


def test_nothing_changes_when_the_model_was_right_yesterday():
    s = class_pattern_series(end="2026-12-20")
    origin = pd.Timestamp("2026-12-17 00:00", tz="UTC")
    train = s[s.index < origin]
    a = models.run_model("naive_level", train, HORIZON, "germany")["yhat"].to_numpy()
    b = models.run_model("naive_level_adj", train, HORIZON, "germany")["yhat"].to_numpy()
    np.testing.assert_allclose(a, b, rtol=1e-9)


def test_backtest_path_and_live_path_give_the_same_forecast():
    s, origin = shocked_series()
    train = s[s.index < origin]
    live = models.run_model("naive_level_adj", train, HORIZON, "germany")["yhat"].to_numpy()
    backtest = predict_origin(s, "naive_level_adj", origin, "germany", HORIZON, None, {})["yhat"].to_numpy()
    np.testing.assert_allclose(live, backtest)


def test_the_correction_never_looks_at_data_from_the_origin_onwards():
    """Shock only the hours from the origin on: the corrected forecast must not change."""
    s, origin = shocked_series(factor=1.0)
    quiet = predict_origin(s, "naive_level_adj", origin, "germany", 37, None, {})["yhat"].to_numpy()
    later = s.copy()
    later[later.index >= origin] *= 1.4
    shocked = predict_origin(later, "naive_level_adj", origin, "germany", 37, None, {})["yhat"].to_numpy()
    np.testing.assert_allclose(quiet, shocked)


def test_backtest_reuses_the_base_forecasts_instead_of_refitting(monkeypatch):
    calls = {"n": 0}
    original = models.MODELS["naive_level"]

    def counting(*args, **kwargs):
        calls["n"] += 1
        return original(*args, **kwargs)

    monkeypatch.setitem(models.MODELS, "naive_level", counting)
    s = synthetic_history(days=60, seed=2)
    preds, failures = collect_predictions(s, ["naive_level", "naive_level_adj"], "germany", 3)
    assert set(preds["model"]) == {"naive_level", "naive_level_adj"} and not any(failures.values())
    assert calls["n"] == 4  # 3 origins + the day before the first one, never twice for the same origin


def test_temperature_variants_need_weather_but_the_plain_one_does_not():
    s = synthetic_history(days=50, seed=3)
    assert len(models.run_model("naive_level_adj", s, HORIZON, "spain")) == HORIZON
    for name in ("ridge_temp_adj", "ensemble_temp_adj", "prophet_temp_adj"):
        with pytest.raises(MissingWeather):
            models.run_model(name, s, HORIZON, "spain", None)
    pred = models.run_model("ridge_temp_adj", s, HORIZON, "spain", synthetic_weather(s, seed=3))
    assert np.isfinite(pred["yhat"]).all()


def test_every_adjusted_model_is_a_candidate_with_a_simplicity_rank_and_a_label():
    from pipeline.run import LABELS, TEMPERATURE_MODELS

    for name, base in models.ADJUSTED.items():
        assert name in models.MODELS and name in models.DEFAULT_MODELS
        assert name in champion.SIMPLICITY and name in LABELS
        assert champion.SIMPLICITY.index(base) < champion.SIMPLICITY.index(name)  # preferred only if clearly better
        assert (name in TEMPERATURE_MODELS) == (base != "naive_level")
