"""HTTP clients for ENTSO-E (electricity load) and Open-Meteo (weather).

Both functions raise ``UpstreamError`` instead of returning placeholder data.
Error messages never contain the ENTSO-E security token.
"""
import logging
import os
from datetime import datetime, timedelta, timezone

import requests
from dotenv import load_dotenv
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

load_dotenv()
log = logging.getLogger(__name__)

ENTSOE_BASE_URL = "https://web-api.tp.entsoe.eu/api"
WEATHER_URL = "https://api.open-meteo.com/v1/forecast"
REQUEST_TIMEOUT = (5, 25)  # (connect, read) seconds


class UpstreamError(Exception):
    """An upstream data provider failed or returned unusable data."""


def _build_session() -> requests.Session:
    retry = Retry(
        total=2,
        backoff_factor=0.5,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=("GET",),
        respect_retry_after_header=False,  # keep worst-case latency bounded
    )
    session = requests.Session()
    session.mount("https://", HTTPAdapter(max_retries=retry, pool_maxsize=10))
    return session


_session = _build_session()


def fetch_energy_xml(country: str, country_code: str) -> str:
    """Raw ENTSO-E actual-load XML for the last 24 hours."""
    api_key = os.getenv("ENTSOE_API_KEY")
    if not api_key:
        raise UpstreamError("ENTSOE_API_KEY is not configured")

    now = datetime.now(timezone.utc)
    params = {
        "securityToken": api_key,
        "documentType": "A65",
        "processType": "A16",
        "outBiddingZone_Domain": country_code,
        "periodStart": (now - timedelta(hours=24)).strftime("%Y%m%d%H00"),
        "periodEnd": now.strftime("%Y%m%d%H00"),
    }
    try:
        response = _session.get(ENTSOE_BASE_URL, params=params, timeout=REQUEST_TIMEOUT)
    except requests.RequestException as exc:
        # Only the exception type is logged: request errors can embed the URL (and token).
        log.warning("ENTSO-E request failed for %s: %s", country, type(exc).__name__)
        raise UpstreamError(f"ENTSO-E request failed for {country}") from None

    if response.status_code != 200:
        log.warning("ENTSO-E returned HTTP %s for %s", response.status_code, country)
        raise UpstreamError(f"ENTSO-E returned HTTP {response.status_code} for {country}")
    return response.text


def fetch_weather(city: str, latitude: float, longitude: float) -> dict:
    """Hourly temperature, wind speed and cloud cover for the next two days."""
    params = {
        "latitude": latitude,
        "longitude": longitude,
        "hourly": "temperature_2m,windspeed_10m,cloudcover",
        "forecast_days": 2,
        "timezone": "Europe/Berlin",
    }
    try:
        response = _session.get(WEATHER_URL, params=params, timeout=REQUEST_TIMEOUT)
        data = response.json()
    except (requests.RequestException, ValueError) as exc:
        log.warning("Open-Meteo request failed for %s: %s", city, type(exc).__name__)
        raise UpstreamError(f"Open-Meteo request failed for {city}") from None

    if not isinstance(data, dict) or response.status_code != 200 or data.get("error"):
        reason = data.get("reason") if isinstance(data, dict) else None
        log.warning("Open-Meteo error for %s: HTTP %s %s", city, response.status_code, reason)
        raise UpstreamError(f"Open-Meteo error for {city}: {reason or response.status_code}")

    hourly = data.get("hourly") or {}
    times = hourly.get("time") or []
    if not times:
        raise UpstreamError(f"Open-Meteo returned no hourly data for {city}")

    return {
        "city": city,
        "timezone": data.get("timezone", "Europe/Berlin"),
        "hourly_time": times,
        "temperature": hourly.get("temperature_2m", []),
        "windspeed": hourly.get("windspeed_10m", []),
        "cloudcover": hourly.get("cloudcover", []),
    }
