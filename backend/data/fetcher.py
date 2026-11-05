"""HTTP clients for ENTSO-E (electricity load), Open-Meteo (weather) and the forecast file.

All functions raise ``UpstreamError`` instead of returning placeholder data.
Error messages never contain the ENTSO-E security token.
"""
import logging
import os
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import requests
from dotenv import load_dotenv
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

load_dotenv()
log = logging.getLogger(__name__)

ENTSOE_BASE_URL = "https://web-api.tp.entsoe.eu/api"
WEATHER_URL = "https://api.open-meteo.com/v1/forecast"
# Fallback weather source (free, no key). Its terms ask for an identifying User-Agent and a credit.
MET_URL = "https://api.met.no/weatherapi/locationforecast/2.0/compact"
MET_USER_AGENT = os.getenv(
    "MET_USER_AGENT", "GridSense/1.1 (+https://github.com/kamal-lochan-sahu/gridsense)"
)
WEATHER_TIMEZONE = "Europe/Berlin"
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
        raise_on_status=False,  # hand back the last response so the real HTTP status is reported
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


def _fetch_open_meteo(city: str, latitude: float, longitude: float) -> dict:
    """Hourly temperature, wind speed and cloud cover for the next two days."""
    params = {
        "latitude": latitude,
        "longitude": longitude,
        "hourly": "temperature_2m,windspeed_10m,cloudcover",
        "forecast_days": 2,
        "timezone": WEATHER_TIMEZONE,
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
        "timezone": data.get("timezone", WEATHER_TIMEZONE),
        "hourly_time": times,
        "temperature": hourly.get("temperature_2m", []),
        "windspeed": hourly.get("windspeed_10m", []),
        "cloudcover": hourly.get("cloudcover", []),
    }


def _fetch_met_norway(city: str, latitude: float, longitude: float) -> dict:
    """Fallback: MET Norway forecast converted to the Open-Meteo shape the dashboard expects.

    Wind comes in m/s (converted to km/h) and times in UTC (converted to local wall-clock
    strings). Only the leading hourly part of the series is used (up to 48 hours).
    """
    params = {"lat": round(latitude, 4), "lon": round(longitude, 4)}
    try:
        response = _session.get(
            MET_URL, params=params, headers={"User-Agent": MET_USER_AGENT}, timeout=REQUEST_TIMEOUT
        )
        data = response.json()
    except (requests.RequestException, ValueError) as exc:
        log.warning("MET Norway request failed for %s: %s", city, type(exc).__name__)
        raise UpstreamError(f"MET Norway request failed for {city}") from None

    if response.status_code != 200 or not isinstance(data, dict):
        log.warning("MET Norway error for %s: HTTP %s", city, response.status_code)
        raise UpstreamError(f"MET Norway error for {city}: HTTP {response.status_code}")

    zone = ZoneInfo(WEATHER_TIMEZONE)
    times: list = []
    temperature: list = []
    windspeed: list = []
    cloudcover: list = []
    previous = None
    for entry in (data.get("properties") or {}).get("timeseries") or []:
        try:
            moment = datetime.fromisoformat(entry["time"].replace("Z", "+00:00"))
            details = entry["data"]["instant"]["details"]
            temp = round(float(details["air_temperature"]), 1)
            wind = round(float(details["wind_speed"]) * 3.6, 1)
            cloud = round(float(details["cloud_area_fraction"]))
        except (KeyError, TypeError, ValueError, AttributeError):
            break
        if previous is not None and moment - previous != timedelta(hours=1):
            break  # the series continues in 3 h and 6 h steps, the dashboard needs hourly values
        previous = moment
        times.append(moment.astimezone(zone).strftime("%Y-%m-%dT%H:%M"))
        temperature.append(temp)
        windspeed.append(wind)
        cloudcover.append(cloud)
        if len(times) == 48:
            break

    if not times:
        raise UpstreamError(f"MET Norway returned no hourly data for {city}")

    return {
        "city": city,
        "timezone": WEATHER_TIMEZONE,
        "hourly_time": times,
        "temperature": temperature,
        "windspeed": windspeed,
        "cloudcover": cloudcover,
    }


def fetch_weather(city: str, latitude: float, longitude: float) -> dict:
    """Open-Meteo first, MET Norway when Open-Meteo fails; ``source`` says which one answered."""
    try:
        data = _fetch_open_meteo(city, latitude, longitude)
        data["source"] = "open-meteo"
        return data
    except UpstreamError as primary:
        log.warning("Open-Meteo unavailable for %s (%s); trying MET Norway", city, primary)
        try:
            data = _fetch_met_norway(city, latitude, longitude)
        except UpstreamError as fallback:
            raise UpstreamError(f"{primary}; {fallback}") from None
        data["source"] = "met-norway"
        return data


def fetch_forecast_file(url: str) -> dict:
    """The forecast.json published by the scheduled pipeline."""
    try:
        response = _session.get(url, timeout=REQUEST_TIMEOUT)
    except requests.RequestException as exc:
        log.warning("Forecast file request failed: %s", type(exc).__name__)
        raise UpstreamError("Forecast file request failed") from None

    if response.status_code != 200:
        log.warning("Forecast file returned HTTP %s", response.status_code)
        raise UpstreamError(f"Forecast file returned HTTP {response.status_code}")

    try:
        data = response.json()
    except ValueError:
        raise UpstreamError("Forecast file is not valid JSON") from None

    if not isinstance(data, dict) or not isinstance(data.get("countries"), dict):
        raise UpstreamError("Forecast file has an unexpected format")
    if data.get("schema_version") != 1:
        raise UpstreamError(f"Unsupported forecast schema version: {data.get('schema_version')}")
    return data
