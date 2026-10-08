"""Shared configuration: supported regions and cache lifetimes."""
import os

COUNTRY_CODES = {
    "germany": "10Y1001A1001A83F",
    "france": "10YFR-RTE------C",
    "spain": "10YES-REE------0",
    "poland": "10YPL-AREA-----S",
}

CITY_COORDS = {
    "berlin": {"latitude": 52.52, "longitude": 13.41},
    "paris": {"latitude": 48.85, "longitude": 2.35},
    "madrid": {"latitude": 40.42, "longitude": -3.70},
    "warsaw": {"latitude": 52.23, "longitude": 21.01},
}

# ENTSO-E publishes new load values roughly every 15 minutes (with a delay of about an hour).
ENERGY_TTL_SECONDS = int(os.getenv("ENERGY_TTL_SECONDS", "300"))
WEATHER_TTL_SECONDS = int(os.getenv("WEATHER_TTL_SECONDS", "1800"))

# If a refresh fails, cached data up to this age is still served (flagged as stale).
MAX_STALE_SECONDS = int(os.getenv("MAX_STALE_SECONDS", str(6 * 3600)))

# The scheduled pipeline (GitHub Actions) publishes forecast.json as an asset of the GitHub release
# `forecast-data`. It is deliberately not a git branch: Vercel builds every pushed branch, and a
# data-only branch made those builds fail.
FORECAST_URL = os.getenv(
    "FORECAST_URL",
    "https://github.com/kamal-lochan-sahu/gridsense/releases/download/forecast-data/forecast.json",
)
# Earlier location (orphan `data` branch). Only tried when the primary URL fails; set to "" to disable.
FORECAST_FALLBACK_URL = os.getenv(
    "FORECAST_FALLBACK_URL",
    "https://raw.githubusercontent.com/kamal-lochan-sahu/gridsense/data/forecast.json",
)
FORECAST_URLS = tuple(url for url in (FORECAST_URL, FORECAST_FALLBACK_URL) if url)
FORECAST_TTL_SECONDS = int(os.getenv("FORECAST_TTL_SECONDS", "600"))
# The pipeline runs every few hours; keep serving the last file for up to two days if GitHub is down.
FORECAST_MAX_STALE_SECONDS = int(os.getenv("FORECAST_MAX_STALE_SECONDS", str(48 * 3600)))
# Pipeline anomalies older than this are ignored in favour of the live z-score fallback.
PIPELINE_MAX_AGE_HOURS = float(os.getenv("PIPELINE_MAX_AGE_HOURS", "12"))
