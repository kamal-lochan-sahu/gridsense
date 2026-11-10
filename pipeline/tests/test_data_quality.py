import numpy as np
import pandas as pd

from pipeline.anomaly import robust_anomalies
from pipeline.history import suspect_hours, to_hourly


def quarter_series(values, start="2026-11-05 00:00"):
    idx = pd.date_range(start, periods=len(values), freq="15min", tz="UTC")
    return pd.Series(values, index=idx, dtype=float)


def hours(index):
    return [t.strftime("%H:%M") for t in index]


def test_a_steep_but_smooth_ramp_is_not_suspect():
    assert len(suspect_hours(quarter_series(np.linspace(50000, 66000, 40)))) == 0  # +1.6 % per step


def test_a_jump_marks_the_hours_on_both_sides():
    values = [65000] * 8 + [53000] * 4 + [65000] * 4  # hour 2 is 12 GW lower than its neighbours
    assert hours(suspect_hours(quarter_series(values))) == ["01:00", "02:00", "03:00"]


def test_several_jumps_in_one_hour_give_each_hour_once():
    values = [65000, 53000, 66000, 54000, 65000, 65000, 65000, 65000]  # three jumps in hour 0
    assert hours(suspect_hours(quarter_series(values))) == ["00:00", "01:00"]


def test_a_missing_quarter_hour_does_not_make_a_jump():
    series = quarter_series([65000] * 4 + [53000] * 4).drop(index=pd.Timestamp("2026-11-05 01:00", tz="UTC"))
    assert len(suspect_hours(series)) == 0  # steps are only judged between consecutive quarter-hours


def test_hourly_data_is_not_checked():
    idx = pd.date_range("2026-11-05", periods=6, freq="1h", tz="UTC")
    assert len(suspect_hours(pd.Series([50000, 56000, 62000, 56000, 50000, 44000], index=idx))) == 0


def test_to_hourly_keeps_the_suspect_hours():
    series = quarter_series([65000] * 8 + [53000] * 4 + [65000] * 4)
    points = [{"time": t.strftime("%Y-%m-%dT%H:%MZ"), "load_mw": v} for t, v in series.items()]
    hourly = to_hourly(points)
    assert hours(hourly.attrs["suspect_hours"]) == ["01:00", "02:00", "03:00"]
    assert len(hourly) == 4


def residual_frame(n=144, seed=0, noise=0.01):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2026-09-01", periods=n, freq="1h", tz="UTC", name="ds")
    yhat = np.full(n, 1000.0)
    return pd.DataFrame({"actual": yhat * (1 + rng.normal(0, noise, n)), "yhat": yhat}, index=idx)


def stamp(ts):
    return ts.strftime("%Y-%m-%dT%H:%MZ")


def test_a_dip_in_suspect_hours_is_held_back_instead_of_reported():
    df = residual_frame()
    df.iloc[-6:-3, df.columns.get_loc("actual")] *= 0.85
    assert robust_anomalies(df)["total_anomalies"] >= 3  # without the quality information it is flagged

    suspect = df.index[-7:-2]
    out = robust_anomalies(df, suspect=suspect)
    assert out["total_anomalies"] == 0 and out["items"] == []
    quality = out["data_quality"]
    assert len(quality["suppressed_items"]) >= 3
    assert quality["suspect_hours"] == [stamp(t) for t in suspect]
    assert quality["step_limit_pct"] == 8.0


def test_a_real_anomaly_outside_the_suspect_hours_is_still_reported():
    df = residual_frame()
    df.iloc[-3, df.columns.get_loc("actual")] *= 0.88
    out = robust_anomalies(df, suspect=df.index[-20:-15])
    assert [i["time"] for i in out["items"]] == [stamp(df.index[-3])]
    assert out["data_quality"]["suppressed_items"] == []


def test_suspect_hours_in_the_past_do_not_inflate_the_normal_error():
    df = residual_frame()
    bad = df.index[10:100:8]  # 12 hours (10 % of the baseline) with large errors
    df.loc[bad, "actual"] *= 1.15
    inflated = robust_anomalies(df)["typical_error_pct"]
    clean = robust_anomalies(df, suspect=bad)["typical_error_pct"]
    assert clean < inflated / 2


def test_no_quality_information_changes_nothing_and_reports_an_empty_quality_block():
    out = robust_anomalies(residual_frame())
    assert out["data_quality"]["suspect_hours"] == [] and out["data_quality"]["suppressed_items"] == []


def test_the_hour_on_each_side_of_a_suspect_hour_is_held_back_too():
    df = residual_frame()
    df.iloc[-6:-3, df.columns.get_loc("actual")] *= 0.85  # three low hours, only the middle one has a jump
    df.iloc[-1, df.columns.get_loc("actual")] *= 0.85  # one more low hour, 4 hours after the suspect hour
    out = robust_anomalies(df, suspect=[df.index[-5]])
    assert [i["time"] for i in out["items"]] == [stamp(df.index[-1])]
    assert [i["time"] for i in out["data_quality"]["suppressed_items"]] == [stamp(t) for t in df.index[-6:-3]]
    assert out["data_quality"]["suspect_hours"] == [stamp(df.index[-5])]  # only the hour with the jump is listed


def test_a_steep_steady_ramp_is_not_a_jump_but_a_lone_spike_is():
    factors = [1.03, 1.06, 1.09, 1.09, 1.09, 1.06, 1.03]  # Italy-like morning ramp, up to +9% per quarter-hour
    ramp = [20000.0] * 4
    for factor in factors:
        ramp.append(ramp[-1] * factor)
    ramp += [ramp[-1]] * 4
    assert len(suspect_hours(quarter_series(ramp))) == 0

    spike = [30000.0] * 6 + [6000.0] + [30000.0] * 6  # one dropped value
    assert hours(suspect_hours(quarter_series(spike))) == ["01:00"]  # the hour that holds the bad value
