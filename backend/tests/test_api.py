import pytest
from fastapi.testclient import TestClient

import main
from core import service
from core.cache import TTLCache
from data import fetcher
from data.fetcher import UpstreamError

client = TestClient(main.app)


@pytest.fixture
def energy_calls(monkeypatch, energy_xml):
    calls = []

    def fake_fetch(country, code):
        calls.append(country)
        return energy_xml

    monkeypatch.setattr(fetcher, "fetch_energy_xml", fake_fetch)
    return calls


def weather_payload(city):
    return {
        "city": city,
        "timezone": "Europe/Berlin",
        "hourly_time": ["2026-10-01T00:00"],
        "temperature": [10.0],
        "windspeed": [5.0],
        "cloudcover": [50],
    }


def test_energy_returns_all_countries_and_is_cached(energy_calls):
    first = client.get("/energy")
    assert first.status_code == 200
    body = first.json()
    assert sorted(item["country"] for item in body) == ["France", "Germany", "Poland", "Spain"]
    assert all(item["status"] == "success" and item["series"] and item["stale"] is False for item in body)
    assert len(energy_calls) == 4

    assert client.get("/energy").status_code == 200
    assert len(energy_calls) == 4  # second request served from cache


def test_anomaly_reuses_cached_energy(energy_calls):
    client.get("/energy")
    response = client.get("/anomaly/germany")
    assert response.status_code == 200
    assert response.json()["country"] == "Germany"
    assert len(energy_calls) == 4  # no extra ENTSO-E call


def test_energy_skips_failing_country(monkeypatch, energy_xml):
    def fake_fetch(country, code):
        if country == "France":
            raise UpstreamError("France down")
        return energy_xml

    monkeypatch.setattr(fetcher, "fetch_energy_xml", fake_fetch)
    response = client.get("/energy")
    assert response.status_code == 200
    assert sorted(item["country"] for item in response.json()) == ["Germany", "Poland", "Spain"]


def test_energy_all_failing_is_502(monkeypatch):
    def fake_fetch(country, code):
        raise UpstreamError("down")

    monkeypatch.setattr(fetcher, "fetch_energy_xml", fake_fetch)
    response = client.get("/energy")
    assert response.status_code == 502
    assert "unavailable" in response.json()["detail"]


def test_single_country_upstream_error_is_502(monkeypatch):
    def fake_fetch(country, code):
        raise UpstreamError("Germany down")

    monkeypatch.setattr(fetcher, "fetch_energy_xml", fake_fetch)
    response = client.get("/energy/germany")
    assert response.status_code == 502
    assert response.json() == {"detail": "Germany down"}


def test_empty_entsoe_answer_counts_as_upstream_error(monkeypatch):
    ack = (
        '<Acknowledgement_MarketDocument xmlns="urn:iec62325.351:tc57wg16:451-1:acknowledgementdocument:7:0">'
        "<Reason><code>999</code><text>No matching data found</text></Reason>"
        "</Acknowledgement_MarketDocument>"
    )
    monkeypatch.setattr(fetcher, "fetch_energy_xml", lambda country, code: ack)
    response = client.get("/energy/germany")
    assert response.status_code == 502
    assert "No matching data" in response.json()["detail"]


@pytest.mark.parametrize("path", ["/energy/atlantis", "/anomaly/atlantis", "/weather/atlantis"])
def test_unknown_region_is_404(path):
    assert client.get(path).status_code == 404


def test_stale_data_is_served_when_refresh_fails(monkeypatch, energy_xml):
    class Clock:
        now = 0.0

        def __call__(self):
            return self.now

    clock = Clock()
    monkeypatch.setattr(service, "cache", TTLCache(clock=clock))
    monkeypatch.setattr(fetcher, "fetch_energy_xml", lambda country, code: energy_xml)
    assert client.get("/energy/germany").json()["stale"] is False

    def broken(country, code):
        raise UpstreamError("down")

    monkeypatch.setattr(fetcher, "fetch_energy_xml", broken)
    clock.now = 1000  # older than the 5 minute TTL, younger than the max stale age
    response = client.get("/energy/germany")
    assert response.status_code == 200
    assert response.json()["stale"] is True


def test_weather_endpoints(monkeypatch):
    monkeypatch.setattr(fetcher, "fetch_weather", lambda city, lat, lon: weather_payload(city))
    body = client.get("/weather").json()
    assert sorted(item["city"] for item in body) == ["Berlin", "Madrid", "Paris", "Warsaw"]
    assert client.get("/weather/berlin").json()["city"] == "Berlin"


def test_weather_skips_failing_city_and_all_failing_is_502(monkeypatch):
    def partly_failing(city, lat, lon):
        if city == "Paris":
            raise UpstreamError("Paris down")
        return weather_payload(city)

    monkeypatch.setattr(fetcher, "fetch_weather", partly_failing)
    assert len(client.get("/weather").json()) == 3

    def failing(city, lat, lon):
        raise UpstreamError("down")

    monkeypatch.setattr(fetcher, "fetch_weather", failing)
    monkeypatch.setattr(service, "cache", TTLCache())
    assert client.get("/weather").status_code == 502
    assert client.get("/weather/berlin").status_code == 502


def test_health_reports_status_and_cache_ages(energy_calls):
    client.get("/energy/germany")
    body = client.get("/health").json()
    assert body["status"] == "ok"
    assert "energy:germany" in body["cache_age_seconds"]
