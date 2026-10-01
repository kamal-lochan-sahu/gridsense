import numpy as np


def detect_anomalies(loads: list, threshold: float = 2.0) -> dict:
    """Flag load values whose z-score exceeds ``threshold`` standard deviations."""
    if len(loads) < 10:
        return {"status": "insufficient_data", "anomalies": [], "total_anomalies": 0}

    values = np.array(loads)
    mean = np.mean(values)
    std = np.std(values)

    if std == 0:
        return {
            "status": "success",
            "anomalies": [],
            "total_anomalies": 0,
            "mean_load": round(float(mean), 2),
            "std_load": 0,
        }

    z_scores = np.abs((values - mean) / std)
    anomalies = [
        {
            "position": int(idx),
            "load_mw": round(float(values[idx]), 2),
            "z_score": round(float(z_scores[idx]), 2),
            "deviation": "HIGH" if values[idx] > mean else "LOW",
        }
        for idx in np.where(z_scores > threshold)[0]
    ]

    return {
        "status": "success",
        "total_anomalies": len(anomalies),
        "mean_load": round(float(mean), 2),
        "std_load": round(float(std), 2),
        "threshold": threshold,
        "anomalies": anomalies,
    }
