from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

import main
from core import service
from core.cache import TTLCache
from data import fetcher
from data.fetcher import UpstreamError

client = TestClient(main.app)
REAL_FETCH_FORECAST_FILE = fetcher.fetch_forecast_file  # conftest stubs the module attribute


def iso(hours_ago=0.0):
    ts = datetime.now(timezone.utc) - timedelta(hours=hours_ago)
    return ts.strftime("%Y-%m-%dT%H:%M:%SZ")


def prediction(hour):
    return {
        "ds": f"2026-10-03 {hour:02d}:00:00",
        "yhat": 40000.0 + hour,
        "yhat_lower": 38000.0 + hour,
        "yhat_upper": 42000.0 + hour,
    }


def entry(model="naive_avg3", anomalies=None, **extra):
    return {
        "model": model,
        "model_label": "3-week seasonal average",
        "data_until": "2026-10-02T23:00Z",
        "backtest": {"mape_pct": 2.61},
        "predictions": [prediction(h) for h in range(24)],
        "anomalies": anomalies
        or {
            "status": "success",
            "method": "forecast-residual robust z-score (median/MAD)",
            "threshold": 3.5,
            "window_hours": 24,
            "typical_error_pct": 2.43,
            "window_level_pct": 5.1,
            "total_anomalies": 1,
            "items": [
                {
                    "time": "2026-10-02T10:00Z",
                    "load_mw": 64888.5,
                    "expected_mw": 57663.0,
                    "deviation_pct": 12.53,
                    "score": 5.01,
                    "deviation": "HIGH",
                }
            ],
        },
        **extra,
    }


def payload(countries=None, generated_at=None):
    return {
        "schema_version": 1,
        "generated_at": generated_at or iso(1),
        "failed": {},
        "countries": countries if countries is not None else {"germany": entry(), "france": entry("ensemble")},
    }


@pytest.fixture
def pipeline(monkeypatch):
    """Serve ``pipeline.data`` as the forecast file and count the downloads."""
    state = {"data": payload(), "calls": 0}

    def fake_fetch(url):
        state["calls"] += 1
        if isinstance(state["data"], Exception):
            raise state["data"]
        return state["data"]

    monkeypatch.setattr(fetcher, "fetch_forecast_file", fake_fetch)
    return state


def test_forecast_for_a_country_keeps_the_old_contract_and_adds_metadata(pipeline):
    body = client.get("/forecast/france").json()
    assert body["status"] == "success" and body["country"] == "France"
    assert body["total_predictions"] == 24 == len(body["predictions"])
    assert set(body["predictions"][0]) == {"ds", "yhat", "yhat_lower", "yhat_upper"}
    assert body["source"] == "pipeline" and body["model_key"] == "ensemble"
    assert body["model"] == "3-week seasonal average"
    assert body["backtest_mape_pct"] == 2.61 and body["stale"] is False
    assert body["data_until"] == "2026-10-02T23:00Z" and body["carried_over"] is False


def test_forecast_without_country_is_germany(pipeline):
    assert client.get("/forecast").json()["country"] == "Germany"


def test_forecast_file_is_downloaded_once_and_cached(pipeline):
    client.get("/forecast/germany")
    client.get("/forecast/france")
    client.get("/anomaly/germany")
    assert pipeline["calls"] == 1


def test_unknown_country_is_404(pipeline):
    assert client.get("/forecast/atlantis").status_code == 404


def test_country_missing_from_pipeline_is_502(pipeline):
    pipeline["data"] = payload({"germany": entry()})
    assert client.get("/forecast/spain").status_code == 502


def test_germany_falls_back_to_static_file_when_pipeline_is_down(pipeline):
    pipeline["data"] = UpstreamError("down")
    body = client.get("/forecast").json()
    assert body["source"] == "static" and body["stale"] is True and body["country"] == "Germany"
    assert client.get("/forecast/poland").status_code == 502


def test_malformed_pipeline_entry_does_not_crash(pipeline):
    pipeline["data"] = payload({"germany": {"model": "naive_avg3"}})
    assert client.get("/forecast/germany").json()["source"] == "static"


def test_last_good_file_is_served_stale_when_refresh_fails(monkeypatch, pipeline):
    now = [0.0]
    monkeypatch.setattr(service, "forecast_cache", TTLCache(max_stale_seconds=3600, clock=lambda: now[0]))
    assert client.get("/forecast/germany").json()["stale"] is False
    pipeline["data"] = UpstreamError("GitHub down")
    now[0] = 700  # past the 600 s TTL
    body = client.get("/forecast/germany").json()
    assert body["source"] == "pipeline" and body["stale"] is True


def test_carried_over_country_is_flagged(pipeline):
    pipeline["data"] = payload({"germany": entry(carried_over=True)})
    assert client.get("/forecast/germany").json()["carried_over"] is True


def test_anomalies_come_from_the_pipeline_without_touching_entsoe(monkeypatch, pipeline):
    monkeypatch.setattr(
        fetcher, "fetch_energy_xml", lambda *a: (_ for _ in ()).throw(AssertionError("ENTSO-E called"))
    )
    body = client.get("/anomaly/germany").json()
    assert body["source"] == "pipeline" and body["status"] == "success"
    assert body["total_anomalies"] == 1 == len(body["anomalies"])
    item = body["anomalies"][0]
    assert item["time"] == "2026-10-02T10:00Z" and item["z_score"] == 5.01 and item["deviation"] == "HIGH"
    assert item["expected_mw"] == 57663.0 and item["deviation_pct"] == 12.53
    assert body["country"] == "Germany" and body["method"].startswith("forecast-residual")
    assert body["window_level_pct"] == 5.1


@pytest.mark.parametrize(
    "data",
    [
        payload({"germany": entry(carried_over=True)}),
        payload(generated_at=iso(30)),  # pipeline stopped running a day ago
        payload({"germany": entry(anomalies={"status": "insufficient_data", "items": []})}),
    ],
    ids=["carried-over", "too-old", "insufficient-data"],
)
def test_anomalies_fall_back_to_live_zscore(monkeypatch, pipeline, energy_xml, data):
    pipeline["data"] = data
    monkeypatch.setattr(fetcher, "fetch_energy_xml", lambda country, code: energy_xml)
    body = client.get("/anomaly/germany").json()
    assert body["source"] == "live-zscore" and body["country"] == "Germany"


def test_health_lists_forecast_cache_age(pipeline):
    client.get("/forecast/germany")
    assert "forecast:file" in client.get("/health").json()["cache_age_seconds"]


def test_fetch_forecast_file_validates_the_payload(monkeypatch):
    class Response:
        def __init__(self, status, body):
            self.status_code, self._body = status, body

        def json(self):
            if isinstance(self._body, Exception):
                raise self._body
            return self._body

    def with_response(response):
        monkeypatch.setattr(fetcher._session, "get", lambda url, timeout: response)

    with_response(Response(200, payload()))
    assert REAL_FETCH_FORECAST_FILE("https://x")["schema_version"] == 1

    for bad in (
        Response(404, None),
        Response(200, ValueError("not json")),
        Response(200, ["list"]),
        Response(200, {"schema_version": 1}),
        Response(200, {"schema_version": 2, "countries": {}}),
    ):
        with_response(bad)
        with pytest.raises(UpstreamError):
            REAL_FETCH_FORECAST_FILE("https://x")


def test_second_url_is_used_when_the_first_fails(monkeypatch):
    seen = []

    def fake_fetch(url):
        seen.append(url)
        if url == "https://primary.example/forecast.json":
            raise UpstreamError("HTTP 404")
        return payload()

    monkeypatch.setattr(service, "FORECAST_URLS", ("https://primary.example/forecast.json", "https://fallback.example/forecast.json"))
    monkeypatch.setattr(fetcher, "fetch_forecast_file", fake_fetch)
    assert client.get("/forecast/germany").json()["source"] == "pipeline"
    assert seen == ["https://primary.example/forecast.json", "https://fallback.example/forecast.json"]


def test_primary_url_wins_and_fallback_is_not_touched(monkeypatch):
    seen = []
    monkeypatch.setattr(service, "FORECAST_URLS", ("https://primary.example/f.json", "https://fallback.example/f.json"))
    monkeypatch.setattr(fetcher, "fetch_forecast_file", lambda url: seen.append(url) or payload())
    client.get("/forecast/germany")
    assert seen == ["https://primary.example/f.json"]


def test_all_urls_failing_means_no_pipeline_forecast(monkeypatch):
    monkeypatch.setattr(service, "FORECAST_URLS", ("https://a.example/f.json", "https://b.example/f.json"))
    monkeypatch.setattr(fetcher, "fetch_forecast_file", lambda url: (_ for _ in ()).throw(UpstreamError("down")))
    assert client.get("/forecast/spain").status_code == 502
    assert client.get("/forecast/germany").json()["source"] == "static"


def test_default_forecast_url_is_the_release_asset_not_a_branch():
    from core import config

    assert config.FORECAST_URL.endswith("/releases/download/forecast-data/forecast.json")
    assert config.FORECAST_URLS[0] == config.FORECAST_URL
