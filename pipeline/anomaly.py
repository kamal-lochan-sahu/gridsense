"""Forecast-residual anomaly detection (robust z-score on how far reality is from the forecast).

A plain z-score on the load itself flags nothing on a smooth daily curve (and flags the normal
evening peak elsewhere). Here we compare each recent hour with what the champion model
predicted for it *without seeing it*.

Forecast errors are strongly correlated within a day (a cold snap or a level drift moves every
hour the same way). Judging each hour against the pooled errors of earlier days would therefore
flag whole days. Instead every hour is compared with the *level of its own surroundings* (a
rolling median over about a day), so only spikes and dips on top of that level are anomalies;
the level itself is reported separately as ``window_level_pct``. The scale of "normal" comes from
the same centred errors of the previous days. It is the 95th percentile of their size divided by
1.96 (the same as the standard deviation for normal errors): unlike the median/MAD it respects
the heavy tails real forecast errors have, and it still ignores up to ~5% old outlier hours.

Source-data glitches: ENTSO-E sometimes publishes quarter-hours that jump by more than 8% from the
previous one (Germany, 5 Nov 2026: 65.5 -> 52.8 GW within 15 minutes), which no real grid does.
The hours touched by such a jump are *suspect*: they are left out of the level and of the scale
of normal errors, and a deviation found in them is not reported as an anomaly but listed under
``data_quality`` so the dashboard can say that the source data is inconsistent instead. A glitch
block often goes on after its last jump without a new one (6 Nov 2026: a plateau about 10 GW too
low from 11:15 to 13:45 with a jump only at 11:00 and 12:00), so the hour on each side of a suspect
hour is held back as well.
"""
import numpy as np
import pandas as pd

METHOD = "forecast-residual robust z-score (local level removed, 95th-percentile scale)"
THRESHOLD = 3.5
WINDOW_HOURS = 24
MIN_BASELINE_HOURS = 48
SCALE_FLOOR = 0.003  # relative; stops a very quiet baseline from making everything an anomaly
LEVEL_WINDOW = 25  # hours; centred rolling median that defines the local level of the errors
STEP_LIMIT = 0.08  # a national load does not move by more than 8% within one quarter-hour
SUSPECT_MARGIN = pd.Timedelta(hours=1)  # hours next to a suspect hour are held back too


def _item(ts, residuals, rel, score) -> dict:
    return {
        "time": ts.strftime("%Y-%m-%dT%H:%MZ"),
        "load_mw": round(float(residuals.loc[ts, "actual"]), 1),
        "expected_mw": round(float(residuals.loc[ts, "yhat"]), 1),
        "deviation_pct": round(float(rel[ts]) * 100, 2),  # vs. the forecast
        "score": round(float(score[ts]), 2),
        "deviation": "HIGH" if score[ts] > 0 else "LOW",
    }


def robust_anomalies(
    residuals: pd.DataFrame,
    window_hours: int = WINDOW_HOURS,
    threshold: float = THRESHOLD,
    min_baseline: int = MIN_BASELINE_HOURS,
    suspect=None,
) -> dict:
    """``residuals``: DataFrame indexed by UTC hour with columns ``actual`` and ``yhat``.

    ``suspect``: UTC hours whose source data jumps implausibly (see the module docstring).
    """
    base_info = {"method": METHOD, "threshold": threshold, "window_hours": window_hours}
    if len(residuals) < window_hours + min_baseline:
        return {**base_info, "status": "insufficient_data", "total_anomalies": 0, "items": []}

    suspect_index = pd.DatetimeIndex(suspect if suspect is not None else [])
    detected = pd.Series(residuals.index.isin(suspect_index), index=residuals.index)
    held_index = suspect_index.union(suspect_index - SUSPECT_MARGIN).union(suspect_index + SUSPECT_MARGIN)
    is_suspect = pd.Series(residuals.index.isin(held_index), index=residuals.index)

    rel = (residuals["actual"] - residuals["yhat"]) / residuals["yhat"]
    rel_clean = rel.where(~is_suspect)  # suspect hours do not shape the level or the scale
    level = rel_clean.rolling(LEVEL_WINDOW, center=True, min_periods=LEVEL_WINDOW // 2).median()
    level = level.interpolate(limit_direction="both")  # a run of suspect hours must not leave holes
    centred = rel - level
    window = centred.iloc[-window_hours:]
    baseline = (rel_clean - level).iloc[:-window_hours].dropna()
    if len(baseline) < min_baseline:
        return {**base_info, "status": "insufficient_data", "total_anomalies": 0, "items": []}
    center = float(np.median(baseline))
    scale = max(float(np.quantile(np.abs(baseline - center), 0.95)) / 1.96, SCALE_FLOOR)
    score = (window - center) / scale

    items, suppressed = [], []
    for ts in score.index[np.abs(score.to_numpy()) > threshold]:
        (suppressed if is_suspect[ts] else items).append(_item(ts, residuals, rel, score))

    in_window = rel_clean.iloc[-window_hours:]
    if not in_window.notna().any():
        in_window = rel.iloc[-window_hours:]
    suspect_in_window = [
        ts.strftime("%Y-%m-%dT%H:%MZ") for ts in detected.index[-window_hours:][detected.iloc[-window_hours:]]
    ]
    return {
        **base_info,
        "status": "success",
        "baseline_hours": int(len(baseline)),
        "typical_error_pct": round(scale * 100, 2),
        "window_level_pct": round(float(in_window.median()) * 100, 2),
        "total_anomalies": len(items),
        "items": items,
        "data_quality": {
            "step_limit_pct": round(STEP_LIMIT * 100, 1),
            "suspect_hours": suspect_in_window,  # the hours with a jump; their neighbours are held back too
            "suppressed_items": suppressed,
        },
    }
