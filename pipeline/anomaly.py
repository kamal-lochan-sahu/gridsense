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
"""
import numpy as np
import pandas as pd

METHOD = "forecast-residual robust z-score (local level removed, 95th-percentile scale)"
THRESHOLD = 3.5
WINDOW_HOURS = 24
MIN_BASELINE_HOURS = 48
SCALE_FLOOR = 0.003  # relative; stops a very quiet baseline from making everything an anomaly
LEVEL_WINDOW = 25  # hours; centred rolling median that defines the local level of the errors


def robust_anomalies(
    residuals: pd.DataFrame,
    window_hours: int = WINDOW_HOURS,
    threshold: float = THRESHOLD,
    min_baseline: int = MIN_BASELINE_HOURS,
) -> dict:
    """``residuals``: DataFrame indexed by UTC hour with columns ``actual`` and ``yhat``."""
    base_info = {"method": METHOD, "threshold": threshold, "window_hours": window_hours}
    if len(residuals) < window_hours + min_baseline:
        return {**base_info, "status": "insufficient_data", "total_anomalies": 0, "items": []}

    rel = (residuals["actual"] - residuals["yhat"]) / residuals["yhat"]
    level = rel.rolling(LEVEL_WINDOW, center=True, min_periods=LEVEL_WINDOW // 2).median()
    centred = rel - level
    window, baseline = centred.iloc[-window_hours:], centred.iloc[:-window_hours]
    center = float(np.median(baseline))
    scale = max(float(np.quantile(np.abs(baseline - center), 0.95)) / 1.96, SCALE_FLOOR)
    score = (window - center) / scale

    items = []
    for ts in score.index[np.abs(score.to_numpy()) > threshold]:
        items.append(
            {
                "time": ts.strftime("%Y-%m-%dT%H:%MZ"),
                "load_mw": round(float(residuals.loc[ts, "actual"]), 1),
                "expected_mw": round(float(residuals.loc[ts, "yhat"]), 1),
                "deviation_pct": round(float(rel[ts]) * 100, 2),  # vs. the forecast
                "score": round(float(score[ts]), 2),
                "deviation": "HIGH" if score[ts] > 0 else "LOW",
            }
        )
    return {
        **base_info,
        "status": "success",
        "baseline_hours": int(len(baseline)),
        "typical_error_pct": round(scale * 100, 2),
        "window_level_pct": round(float(rel.iloc[-window_hours:].median()) * 100, 2),
        "total_anomalies": len(items),
        "items": items,
    }
