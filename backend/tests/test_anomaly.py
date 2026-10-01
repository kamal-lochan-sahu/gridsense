from ml.anomaly import detect_anomalies

LOADS = [50000, 51000, 49000, 52000, 48000, 80000, 50500, 51500,
         49500, 52500, 48500, 20000, 50000, 51000, 49000]


def test_too_few_points_is_insufficient_data():
    result = detect_anomalies([1, 2, 3])
    assert result["status"] == "insufficient_data"
    assert result["total_anomalies"] == 0


def test_flat_series_has_no_anomalies():
    result = detect_anomalies([5000] * 20)
    assert result["status"] == "success"
    assert result["total_anomalies"] == 0


def test_spike_and_dip_are_flagged():
    result = detect_anomalies(LOADS)
    assert result["total_anomalies"] == 2
    assert [(a["position"], a["deviation"]) for a in result["anomalies"]] == [(5, "HIGH"), (11, "LOW")]
