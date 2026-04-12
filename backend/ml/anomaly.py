import numpy as np

def detect_anomalies(loads: list, threshold: float = 2.0):
    """
    Energy load data mein anomalies detect karo
    Z-score method use karta hai
    threshold = 2.0 matlab 2 standard deviations se bahar = anomaly
    """
    if len(loads) < 10:
        return {
            "status": "insufficient_data",
            "anomalies": [],
            "total_anomalies": 0
        }

    loads_array = np.array(loads)
    mean = np.mean(loads_array)
    std = np.std(loads_array)

    if std == 0:
        return {
            "status": "success",
            "anomalies": [],
            "total_anomalies": 0,
            "mean_load": round(float(mean), 2),
            "std_load": 0
        }

    # Z-score calculate karo
    z_scores = np.abs((loads_array - mean) / std)

    # Anomalies dhundo
    anomaly_indices = np.where(z_scores > threshold)[0]

    anomalies = []
    for idx in anomaly_indices:
        anomalies.append({
            "position": int(idx),
            "load_mw": round(float(loads_array[idx]), 2),
            "z_score": round(float(z_scores[idx]), 2),
            "deviation": "HIGH" if loads_array[idx] > mean else "LOW"
        })

    return {
        "status": "success",
        "total_anomalies": len(anomalies),
        "mean_load": round(float(mean), 2),
        "std_load": round(float(std), 2),
        "threshold": threshold,
        "anomalies": anomalies
    }


if __name__ == "__main__":
    # Test data
    test_loads = [50000, 51000, 49000, 52000, 48000,
                  80000, 50500, 51500, 49500, 52500,
                  48500, 20000, 50000, 51000, 49000]

    result = detect_anomalies(test_loads)
    print(f"Total anomalies: {result['total_anomalies']}")
    print(f"Mean load: {result['mean_load']} MW")
    for a in result['anomalies']:
        print(f"Position {a['position']}: {a['load_mw']} MW — {a['deviation']} (z={a['z_score']})")