"""Cached, fault-tolerant data access used by the API routes."""
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from core.cache import TTLCache
from core.config import (
    CITY_COORDS,
    COUNTRY_CODES,
    ENERGY_TTL_SECONDS,
    MAX_STALE_SECONDS,
    WEATHER_TTL_SECONDS,
)
from data import fetcher
from data.fetcher import UpstreamError
from data.parser import parse_energy_xml
from ml.anomaly import detect_anomalies

log = logging.getLogger(__name__)

cache = TTLCache(max_stale_seconds=MAX_STALE_SECONDS)


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def get_energy(country: str) -> dict:
    """Parsed 24h load for one country. ``country`` must be a key of COUNTRY_CODES."""
    name = country.capitalize()

    def load() -> dict:
        xml = fetcher.fetch_energy_xml(name, COUNTRY_CODES[country])
        parsed = parse_energy_xml(xml, name)
        if parsed.get("status") != "success":
            detail = parsed.get("message") or parsed.get("status")
            raise UpstreamError(f"No usable load data for {name}: {detail}")
        parsed["fetched_at"] = _now_iso()
        return parsed

    value, stale = cache.get_or_load(f"energy:{country}", ENERGY_TTL_SECONDS, load)
    return {**value, "stale": stale}


def get_all_energy() -> list:
    """All countries in parallel. Countries that fail are skipped; all failing raises."""

    def fetch_one(country: str):
        try:
            return get_energy(country)
        except UpstreamError as exc:
            log.warning("Energy data unavailable for %s: %s", country, exc)
            return None

    countries = list(COUNTRY_CODES)
    with ThreadPoolExecutor(max_workers=len(countries)) as pool:
        results = list(pool.map(fetch_one, countries))

    available = [item for item in results if item is not None]
    if not available:
        raise UpstreamError("Energy data is unavailable for all countries")
    return available


def get_anomalies(country: str) -> dict:
    """Anomalies of one country, computed from the cached energy series."""
    energy = get_energy(country)
    result = detect_anomalies(energy["all_loads"])
    result["country"] = country.capitalize()
    result["stale"] = energy["stale"]
    return result


def get_weather(city: str) -> dict:
    """Hourly weather for one city. ``city`` must be a key of CITY_COORDS."""
    coords = CITY_COORDS[city]
    name = city.capitalize()

    def load() -> dict:
        data = fetcher.fetch_weather(name, coords["latitude"], coords["longitude"])
        data["fetched_at"] = _now_iso()
        return data

    value, stale = cache.get_or_load(f"weather:{city}", WEATHER_TTL_SECONDS, load)
    return {**value, "stale": stale}


def get_all_weather() -> list:
    """All cities in parallel. Cities that fail are skipped; all failing raises."""

    def fetch_one(city: str):
        try:
            return get_weather(city)
        except UpstreamError as exc:
            log.warning("Weather unavailable for %s: %s", city, exc)
            return None

    cities = list(CITY_COORDS)
    with ThreadPoolExecutor(max_workers=len(cities)) as pool:
        results = list(pool.map(fetch_one, cities))

    available = [item for item in results if item is not None]
    if not available:
        raise UpstreamError("Weather data is unavailable for all cities")
    return available
