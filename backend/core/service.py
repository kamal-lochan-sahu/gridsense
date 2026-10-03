"""Cached, fault-tolerant data access used by the API routes."""
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from core.cache import TTLCache
from core.config import (
    CITY_COORDS,
    COUNTRY_CODES,
    ENERGY_TTL_SECONDS,
    FORECAST_MAX_STALE_SECONDS,
    FORECAST_TTL_SECONDS,
    FORECAST_URL,
    MAX_STALE_SECONDS,
    PIPELINE_MAX_AGE_HOURS,
    WEATHER_TTL_SECONDS,
)
from data import fetcher
from data.fetcher import UpstreamError
from data.parser import parse_energy_xml
from ml.anomaly import detect_anomalies
from ml.forecaster import get_next_24hr_forecast

log = logging.getLogger(__name__)

cache = TTLCache(max_stale_seconds=MAX_STALE_SECONDS)
forecast_cache = TTLCache(max_stale_seconds=FORECAST_MAX_STALE_SECONDS)


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


def _pipeline_file() -> tuple:
    """``(forecast.json content, is_stale)``; raises UpstreamError if never loaded."""
    return forecast_cache.get_or_load(
        "forecast:file", FORECAST_TTL_SECONDS, lambda: fetcher.fetch_forecast_file(FORECAST_URL)
    )


def _age_hours(timestamp: str) -> float:
    generated = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    return (datetime.now(timezone.utc) - generated).total_seconds() / 3600


def get_forecast(country: str) -> dict:
    """24h forecast of one country from the scheduled pipeline.

    Germany falls back to the bundled static file when the pipeline file is unavailable.
    Keeps the response shape of the old static endpoint (status/country/model/predictions).
    """
    name = country.capitalize()
    try:
        data, stale = _pipeline_file()
        entry = data["countries"].get(country)
        if entry is not None:
            return {
                "status": "success",
                "source": "pipeline",
                "country": name,
                "model": entry.get("model_label") or entry["model"],
                "model_key": entry["model"],
                "backtest_mape_pct": entry["backtest"]["mape_pct"],
                "generated_at": data.get("generated_at"),
                "data_until": entry.get("data_until"),
                "carried_over": bool(entry.get("carried_over")),
                "stale": stale,
                "total_predictions": len(entry["predictions"]),
                "predictions": entry["predictions"],
            }
    except UpstreamError as exc:
        log.warning("Pipeline forecast unavailable: %s", exc)
    except (KeyError, TypeError):
        log.exception("Pipeline forecast entry for %s is malformed", country)

    if country == "germany":
        static = get_next_24hr_forecast()
        if static["status"] == "success":
            return {**static, "source": "static", "stale": True}
    raise UpstreamError(f"No forecast available for {name}")


def _pipeline_anomalies(country: str):
    """Residual-based anomalies from the pipeline, or None if missing, too old or unusable."""
    try:
        data, stale = _pipeline_file()
        entry = data["countries"].get(country)
        if not entry or entry.get("carried_over"):
            return None
        found = entry["anomalies"]
        if found.get("status") != "success" or _age_hours(data["generated_at"]) > PIPELINE_MAX_AGE_HOURS:
            return None
        return {
            "status": "success",
            "source": "pipeline",
            "country": country.capitalize(),
            "method": found["method"],
            "threshold": found["threshold"],
            "window_hours": found["window_hours"],
            "typical_error_pct": found.get("typical_error_pct"),
            "total_anomalies": found["total_anomalies"],
            "anomalies": [
                {
                    "time": item["time"],
                    "load_mw": item["load_mw"],
                    "expected_mw": item["expected_mw"],
                    "deviation_pct": item["deviation_pct"],
                    "z_score": item["score"],
                    "deviation": item["deviation"],
                }
                for item in found["items"]
            ],
            "generated_at": data["generated_at"],
            "data_until": entry.get("data_until"),
            "stale": stale,
        }
    except UpstreamError:
        return None
    except (KeyError, TypeError, ValueError):
        log.exception("Pipeline anomaly entry for %s is malformed", country)
        return None


def get_anomalies(country: str) -> dict:
    """Anomalies of one country: forecast-residual method from the pipeline when available,
    otherwise a z-score on the cached live energy series."""
    from_pipeline = _pipeline_anomalies(country)
    if from_pipeline is not None:
        return from_pipeline

    energy = get_energy(country)
    result = detect_anomalies(energy["all_loads"])
    result["country"] = country.capitalize()
    result["stale"] = energy["stale"]
    result["source"] = "live-zscore"
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
