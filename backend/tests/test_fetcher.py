import pytest
import requests

from data import fetcher
from data.fetcher import UpstreamError

TOKEN = "secret-token-123"


class FakeResponse:
    def __init__(self, status_code=200, text="", json_data=None):
        self.status_code = status_code
        self.text = text
        self._json = json_data

    def json(self):
        if self._json is None:
            raise ValueError("not json")
        return self._json


def patch_get(monkeypatch, response=None, error=None):
    seen = {}

    def fake_get(url, params=None, timeout=None):
        seen["url"], seen["params"], seen["timeout"] = url, params, timeout
        if error:
            raise error
        return response

    monkeypatch.setattr(fetcher._session, "get", fake_get)
    return seen


def test_entsoe_requires_api_key(monkeypatch):
    monkeypatch.delenv("ENTSOE_API_KEY", raising=False)
    with pytest.raises(UpstreamError, match="not configured"):
        fetcher.fetch_energy_xml("Germany", "CODE")


def test_entsoe_success_returns_xml_and_uses_timeout(monkeypatch):
    monkeypatch.setenv("ENTSOE_API_KEY", TOKEN)
    seen = patch_get(monkeypatch, FakeResponse(200, "<xml/>"))
    assert fetcher.fetch_energy_xml("Germany", "CODE") == "<xml/>"
    assert seen["params"]["documentType"] == "A65"
    assert seen["params"]["outBiddingZone_Domain"] == "CODE"
    assert seen["timeout"] == fetcher.REQUEST_TIMEOUT


def test_entsoe_http_error_does_not_leak_token(monkeypatch):
    monkeypatch.setenv("ENTSOE_API_KEY", TOKEN)
    patch_get(monkeypatch, FakeResponse(401, "Unauthorized"))
    with pytest.raises(UpstreamError) as info:
        fetcher.fetch_energy_xml("Germany", "CODE")
    assert "401" in str(info.value)
    assert TOKEN not in str(info.value)


def test_entsoe_network_error_does_not_leak_token(monkeypatch):
    monkeypatch.setenv("ENTSOE_API_KEY", TOKEN)
    patch_get(monkeypatch, error=requests.ConnectionError(f"failed ?securityToken={TOKEN}"))
    with pytest.raises(UpstreamError) as info:
        fetcher.fetch_energy_xml("Germany", "CODE")
    assert TOKEN not in str(info.value)
    assert info.value.__cause__ is None


def test_weather_success_maps_fields(monkeypatch):
    payload = {
        "timezone": "Europe/Berlin",
        "hourly": {
            "time": ["2026-10-01T00:00", "2026-10-01T01:00"],
            "temperature_2m": [10.5, 11.0],
            "windspeed_10m": [5.0, 6.0],
            "cloudcover": [20, 30],
        },
    }
    patch_get(monkeypatch, FakeResponse(200, json_data=payload))
    result = fetcher.fetch_weather("Berlin", 52.52, 13.41)
    assert result == {
        "city": "Berlin",
        "timezone": "Europe/Berlin",
        "hourly_time": ["2026-10-01T00:00", "2026-10-01T01:00"],
        "temperature": [10.5, 11.0],
        "windspeed": [5.0, 6.0],
        "cloudcover": [20, 30],
    }


def test_weather_api_error_raises(monkeypatch):
    patch_get(monkeypatch, FakeResponse(400, json_data={"error": True, "reason": "Too many requests"}))
    with pytest.raises(UpstreamError, match="Too many requests"):
        fetcher.fetch_weather("Berlin", 52.52, 13.41)


def test_weather_without_hourly_data_raises(monkeypatch):
    patch_get(monkeypatch, FakeResponse(200, json_data={"hourly": {}}))
    with pytest.raises(UpstreamError, match="no hourly data"):
        fetcher.fetch_weather("Berlin", 52.52, 13.41)


def test_weather_network_and_json_errors_raise(monkeypatch):
    patch_get(monkeypatch, error=requests.Timeout("slow"))
    with pytest.raises(UpstreamError):
        fetcher.fetch_weather("Berlin", 52.52, 13.41)
    patch_get(monkeypatch, FakeResponse(200))  # body is not JSON
    with pytest.raises(UpstreamError):
        fetcher.fetch_weather("Berlin", 52.52, 13.41)
