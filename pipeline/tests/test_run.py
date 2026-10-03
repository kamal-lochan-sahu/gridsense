import json
import re

import numpy as np
import pandas as pd
import pytest

from pipeline import run as run_module
from pipeline.anomaly import robust_anomalies
from pipeline.champion import score_table, select_champion
from pipeline.history import HistoryError, synthetic_history

FAST = ["seasonal_naive", "naive_avg3"]


def table(**mapes):
    return pd.DataFrame({"mape_pct": mapes, "mae_mw": 1.0, "hours": 100})


def test_champion_prefers_simple_model_unless_complex_one_wins_clearly():
    assert select_champion(table(seasonal_naive=2.0, prophet=1.95)) == "seasonal_naive"
    assert select_champion(table(seasonal_naive=2.0, naive_avg3=1.99, prophet=1.5)) == "prophet"
    assert select_champion(table(seasonal_naive=3.0, naive_avg3=2.3, ensemble=2.35)) == "naive_avg3"


def test_champion_rejects_empty_table():
    with pytest.raises(ValueError):
        select_champion(table().iloc[0:0])


def test_score_table_drops_models_scored_on_few_hours():
    ds = pd.date_range("2026-01-01", periods=100, freq="1h", tz="UTC")
    full = pd.DataFrame({"ds": ds, "actual": 100.0, "yhat": 101.0, "model": "a"})
    sparse = full.iloc[:10].assign(model="b")
    out = score_table(pd.concat([full, sparse]))
    assert list(out.index) == ["a"]
    assert out.loc["a", "mape_pct"] == pytest.approx(1.0)


def residual_frame(n=144, seed=0, noise=0.01):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2026-09-01", periods=n, freq="1h", tz="UTC", name="ds")
    yhat = np.full(n, 1000.0)
    return pd.DataFrame({"actual": yhat * (1 + rng.normal(0, noise, n)), "yhat": yhat}, index=idx)


def test_robust_anomalies_flags_injected_spike_and_dip():
    df = residual_frame()
    df.iloc[-3, df.columns.get_loc("actual")] *= 1.10
    df.iloc[-10, df.columns.get_loc("actual")] *= 0.88
    out = robust_anomalies(df)
    flagged = {(i["time"], i["deviation"]) for i in out["items"]}
    assert (df.index[-3].strftime("%Y-%m-%dT%H:%MZ"), "HIGH") in flagged
    assert (df.index[-10].strftime("%Y-%m-%dT%H:%MZ"), "LOW") in flagged
    assert out["total_anomalies"] == len(out["items"])


def test_robust_anomalies_quiet_on_normal_noise():
    assert robust_anomalies(residual_frame())["total_anomalies"] == 0


def test_robust_anomalies_needs_enough_history():
    out = robust_anomalies(residual_frame(n=40))
    assert out["status"] == "insufficient_data" and out["items"] == []


def test_old_outliers_do_not_hide_new_ones():
    df = residual_frame()
    df.iloc[5:15, df.columns.get_loc("actual")] *= 1.25  # big errors in the baseline
    df.iloc[-2, df.columns.get_loc("actual")] *= 1.12
    assert robust_anomalies(df)["total_anomalies"] >= 1


def test_build_entry_contract_and_calibrated_interval():
    series = synthetic_history(days=60, seed=1)
    entry = run_module.build_country_entry("germany", series, FAST, n_origins=8)
    assert entry["model"] in FAST
    preds = entry["predictions"]
    assert len(preds) == 24
    assert all(re.fullmatch(r"\d{4}-\d\d-\d\d \d\d:\d\d:\d\d", p["ds"]) for p in preds)
    assert all(p["yhat_lower"] < p["yhat_upper"] for p in preds)
    assert set(entry["backtest"]["candidates_mape_pct"]) <= set(FAST)
    json.dumps(entry, allow_nan=False)  # fully serialisable, no NaN


def test_build_entry_detects_a_fresh_spike():
    series = synthetic_history(days=60, seed=2)
    series.iloc[-3:] *= 1.30
    entry = run_module.build_country_entry("germany", series, FAST, n_origins=8)
    last_hours = {t.strftime("%Y-%m-%dT%H:%MZ") for t in series.index[-3:]}
    flagged = {i["time"] for i in entry["anomalies"]["items"] if i["deviation"] == "HIGH"}
    assert flagged & last_hours


def test_failed_country_falls_back_to_previous_entry(monkeypatch, tmp_path):
    previous = {"france": {"model": "naive_avg3", "predictions": [], "anomalies": {}}}

    def fake_load(country, days):
        if country == "france":
            raise HistoryError("ENTSO-E request failed (HTTP 503)")
        return synthetic_history(days=60, seed=3)

    monkeypatch.setattr(run_module, "load_history", fake_load)
    out = run_module.run(["germany", "france"], FAST, 5, 60, False, previous)
    assert out["countries"]["france"]["carried_over"] is True
    assert "carried_over" not in out["countries"]["germany"]
    assert "france" in out["failed"]


def test_main_writes_nothing_when_every_country_fails(monkeypatch, tmp_path):
    monkeypatch.setattr(
        run_module, "load_history", lambda c, d: (_ for _ in ()).throw(HistoryError("down"))
    )
    out = tmp_path / "forecast.json"
    code = run_module.main(["--countries", "germany", "--candidates", "seasonal_naive", "--out", str(out)])
    assert code == 1 and not out.exists()


def test_main_synthetic_end_to_end(tmp_path):
    out = tmp_path / "forecast.json"
    code = run_module.main(
        ["--synthetic", "--countries", "poland", "--candidates", *FAST, "--origins", "6", "--out", str(out)]
    )
    data = json.loads(out.read_text())
    assert code == 0 and data["schema_version"] == 1
    assert data["countries"]["poland"]["predictions"]
