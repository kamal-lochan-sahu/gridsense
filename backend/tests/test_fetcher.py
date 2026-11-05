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

    def fake_get(url, params=None, timeout=None, headers=None):
        seen["url"], seen["params"], seen["timeout"], seen["headers"] = url, params, timeout, headers
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
        "source": "open-meteo",
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


def met_payload(hours=3, start_hour=22, gap_after=None):
    """MET Norway compact payload: hourly entries from 2026-11-04 22:00 UTC (23:00 in Berlin)."""
    series = []
    for i in range(hours):
        stamp = f"2026-11-04T{start_hour + i:02d}:00:00Z" if start_hour + i < 24 else f"2026-11-05T{start_hour + i - 24:02d}:00:00Z"
        series.append(
            {
                "time": stamp,
                "data": {
                    "instant": {
                        "details": {
                            "air_temperature": 8.04 + i,
                            "wind_speed": 2.0 + i,
                            "cloud_area_fraction": 45.6,
                        }
                    }
                },
            }
        )
    if gap_after is not None:
        series[gap_after]["time"] = "2026-11-05T18:00:00Z"
    return {"properties": {"timeseries": series}}


def route_get(monkeypatch, open_meteo, met):
    """Different fake responses per provider; returns the list of called URLs."""
    calls = []

    def fake_get(url, params=None, timeout=None, headers=None):
        calls.append((url, headers))
        target = open_meteo if url == fetcher.WEATHER_URL else met
        if isinstance(target, Exception):
            raise target
        return target

    monkeypatch.setattr(fetcher._session, "get", fake_get)
    return calls


def test_weather_falls_back_to_met_norway(monkeypatch):
    calls = route_get(
        monkeypatch,
        FakeResponse(429, json_data={"error": True, "reason": "Too many requests"}),
        FakeResponse(200, json_data=met_payload()),
    )
    result = fetcher.fetch_weather("Berlin", 52.52, 13.41)
    assert result == {
        "city": "Berlin",
        "timezone": "Europe/Berlin",
        "hourly_time": ["2026-11-04T23:00", "2026-11-05T00:00", "2026-11-05T01:00"],
        "temperature": [8.0, 9.0, 10.0],
        "windspeed": [7.2, 10.8, 14.4],  # m/s converted to km/h
        "cloudcover": [46, 46, 46],
        "source": "met-norway",
    }
    assert [url for url, _ in calls] == [fetcher.WEATHER_URL, fetcher.MET_URL]
    assert "GridSense" in calls[1][1]["User-Agent"]


def test_weather_prefers_open_meteo_when_it_works(monkeypatch):
    payload = {
        "timezone": "Europe/Berlin",
        "hourly": {"time": ["2026-10-01T00:00"], "temperature_2m": [1], "windspeed_10m": [2], "cloudcover": [3]},
    }
    calls = route_get(monkeypatch, FakeResponse(200, json_data=payload), FakeResponse(500))
    assert fetcher.fetch_weather("Berlin", 52.52, 13.41)["source"] == "open-meteo"
    assert len(calls) == 1


def test_weather_both_providers_failing_reports_both(monkeypatch):
    route_get(
        monkeypatch,
        requests.exceptions.RetryError("too many 429 error responses"),
        FakeResponse(503, json_data={}),
    )
    with pytest.raises(UpstreamError) as info:
        fetcher.fetch_weather("Berlin", 52.52, 13.41)
    message = str(info.value)
    assert "Open-Meteo request failed for Berlin" in message
    assert "MET Norway error for Berlin: HTTP 503" in message


def test_met_norway_keeps_only_the_hourly_part(monkeypatch):
    route_get(monkeypatch, requests.Timeout("slow"), FakeResponse(200, json_data=met_payload(hours=4, gap_after=2)))
    result = fetcher.fetch_weather("Paris", 48.85, 2.35)
    assert len(result["hourly_time"]) == 2  # the entry after the gap and everything behind it is dropped


def test_met_norway_without_usable_data_raises(monkeypatch):
    route_get(monkeypatch, requests.Timeout("slow"), FakeResponse(200, json_data={"properties": {"timeseries": [{"time": "x"}]}}))
    with pytest.raises(UpstreamError, match="MET Norway returned no hourly data"):
        fetcher.fetch_weather("Paris", 48.85, 2.35)
