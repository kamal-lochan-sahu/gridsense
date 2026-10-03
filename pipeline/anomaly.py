"""Forecast-residual anomaly detection (robust z-score on how far reality is from the forecast).

A plain z-score on the load itself flags nothing on a smooth daily curve (and flags the normal
evening peak elsewhere). Here we compare each recent hour with what the champion model
predicted for it *without seeing it*, and ask whether that error is unusual compared with the
errors of the previous days (median / MAD, so past outliers do not inflate the scale).
"""
import numpy as np
import pandas as pd

METHOD = "forecast-residual robust z-score (median/MAD)"
THRESHOLD = 3.5
WINDOW_HOURS = 24
MIN_BASELINE_HOURS = 48
SCALE_FLOOR = 0.003  # relative; stops a very quiet baseline from making everything an anomaly


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
    window, baseline = rel.iloc[-window_hours:], rel.iloc[:-window_hours]
    center = float(np.median(baseline))
    mad = float(np.median(np.abs(baseline - center)))
    scale = max(1.4826 * mad, SCALE_FLOOR)
    score = (window - center) / scale

    items = []
    for ts in score.index[np.abs(score.to_numpy()) > threshold]:
        items.append(
            {
                "time": ts.strftime("%Y-%m-%dT%H:%MZ"),
                "load_mw": round(float(residuals.loc[ts, "actual"]), 1),
                "expected_mw": round(float(residuals.loc[ts, "yhat"]), 1),
                "deviation_pct": round(float(window[ts]) * 100, 2),
                "score": round(float(score[ts]), 2),
                "deviation": "HIGH" if score[ts] > 0 else "LOW",
            }
        )
    return {
        **base_info,
        "status": "success",
        "baseline_hours": int(len(baseline)),
        "typical_error_pct": round(scale * 100, 2),
        "total_anomalies": len(items),
        "items": items,
    }
