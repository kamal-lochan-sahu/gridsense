import json

import numpy as np
import pandas as pd
import pytest

from pipeline import run as run_module
from pipeline import trackrecord
from pipeline.history import HistoryError, synthetic_history, synthetic_tso
from pipeline.trackrecord import build_track_record, target_days


def day_end_series(spike_from=None, factor=2.0):
    """Deterministic weekly-periodic series that ends exactly at 23:00 UTC."""
    idx = pd.date_range("2026-08-01", "2026-10-02 23:00", freq="1h", tz="UTC", name="ds")
    local_hour = idx.hour.to_numpy()
    values = 30000 + 500 * local_hour + 2000 * (idx.dayofweek.to_numpy() >= 5)
    series = pd.Series(values.astype(float), index=idx)
    if spike_from is not None:
        series.loc[series.index >= spike_from] *= factor
    return series


def test_target_days_are_complete_utc_days_oldest_first():
    s = day_end_series()
    days = target_days(s, 5)
    assert len(days) == 5 and days == sorted(days)
    assert days[-1] == pd.Timestamp("2026-10-02", tz="UTC")
    partial = s.iloc[:-5]  # ends at 18:00: the last day is not complete
    assert target_days(partial, 1)[0] == pd.Timestamp("2026-10-01", tz="UTC")


def test_record_has_summary_daily_and_hourly_parts():
    s = synthetic_history(days=60, seed=1)
    rec = build_track_record(s, "naive_avg3", "germany", tso=synthetic_tso(s, seed=1))
    assert rec["sources"] == ["gridsense", "tso", "naive"] and rec["model"] == "naive_avg3"
    assert set(rec["summary"]) == {"7d", "14d"}
    for window in rec["summary"].values():
        assert {"days", "hours", "gridsense", "tso", "naive"} <= set(window)
    assert 10 <= len(rec["daily"]) <= 14
    assert 48 <= len(rec["hourly"]) <= 72
    assert set(rec["hourly"][0]) == {"ds", "actual", "gridsense", "tso", "naive"}
    json.dumps(rec, allow_nan=False)


def test_tso_is_optional():
    s = synthetic_history(days=60, seed=2)
    rec = build_track_record(s, "naive_avg3", "germany", tso=None)
    assert rec["sources"] == ["gridsense", "naive"]
    assert "tso" not in rec["summary"]["7d"] and "tso" not in rec["hourly"][0]


def test_a_perfect_tso_scores_zero_and_ours_does_not():
    s = synthetic_history(days=60, seed=3)
    rec = build_track_record(s, "naive_avg3", "germany", tso=s.copy())
    assert rec["summary"]["14d"]["tso"] == 0.0 and rec["summary"]["14d"]["gridsense"] > 0


def test_naive_champion_matches_the_naive_baseline():
    s = synthetic_history(days=60, seed=4)
    rec = build_track_record(s, "seasonal_naive", "germany")
    assert rec["summary"]["14d"]["gridsense"] == rec["summary"]["14d"]["naive"]


def test_forecasts_only_use_data_from_before_the_origin_hour():
    """A shock after the origin of the last day changes the actual load, not our forecast for it."""
    base = day_end_series()
    shocked = day_end_series(spike_from=pd.Timestamp("2026-10-02 00:00", tz="UTC"))
    a = build_track_record(base, "naive_avg3", "germany")
    b = build_track_record(shocked, "naive_avg3", "germany")
    last_a = [h for h in a["hourly"] if h["ds"].startswith("2026-10-02")]
    last_b = [h for h in b["hourly"] if h["ds"].startswith("2026-10-02")]
    assert len(last_a) == len(last_b) == 24
    assert [h["gridsense"] for h in last_a] == [h["gridsense"] for h in last_b]
    assert [h["actual"] for h in last_b] == [round(h["actual"] * 2, 1) for h in last_a]


def test_returns_none_when_there_is_no_usable_day():
    short = synthetic_history(days=5, seed=5)  # less than the 14 days of history a model needs
    assert build_track_record(short, "naive_avg3", "germany") is None


def test_entry_contains_the_track_record_and_survives_its_failure(monkeypatch):
    s = synthetic_history(days=60, seed=6)
    entry = run_module.build_country_entry("germany", s, ["seasonal_naive", "naive_avg3"], 6, None, synthetic_tso(s, 6))
    assert entry["track_record"]["model"] == entry["model"]

    def boom(*args, **kwargs):
        raise RuntimeError("no")

    monkeypatch.setattr(run_module, "build_track_record", boom)
    entry = run_module.build_country_entry("germany", s, ["seasonal_naive"], 6, None, None)
    assert entry["track_record"] is None and len(entry["predictions"]) == 24


def test_main_synthetic_run_writes_track_record_and_no_tso_flag(tmp_path):
    out = tmp_path / "f.json"
    assert run_module.main(["--synthetic", "--countries", "france", "--candidates", "seasonal_naive", "--origins", "4", "--out", str(out)]) == 0
    assert "tso" in json.loads(out.read_text())["countries"]["france"]["track_record"]["sources"]
    assert run_module.main(["--synthetic", "--no-tso", "--countries", "france", "--candidates", "seasonal_naive", "--origins", "4", "--out", str(out)]) == 0
    assert "tso" not in json.loads(out.read_text())["countries"]["france"]["track_record"]["sources"]


def test_failing_tso_download_only_drops_the_tso(monkeypatch):
    monkeypatch.setattr(run_module, "load_history", lambda c, d: synthetic_history(60, seed=7))
    monkeypatch.setattr(run_module, "load_tso_forecast", lambda c, d: (_ for _ in ()).throw(HistoryError("HTTP 503")))
    out = run_module.run(["germany"], ["seasonal_naive"], 4, 60, False, {}, use_weather=False)
    assert out["failed"] == {} and "tso" not in out["countries"]["germany"]["track_record"]["sources"]
