import logging
import os

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from core import service
from core.config import CITY_COORDS, COUNTRY_CODES
from data.fetcher import UpstreamError

load_dotenv()
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

app = FastAPI(
    title="GridSense API",
    description="Real-Time Industrial Energy Intelligence Platform",
    version="1.1.0",
)

# Public read-only API without credentials. Restrict with CORS_ORIGINS="https://a.com,https://b.com".
cors_origins = [o.strip() for o in os.getenv("CORS_ORIGINS", "*").split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=False,
    allow_methods=["GET"],
    allow_headers=["*"],
)


@app.exception_handler(UpstreamError)
async def upstream_error_handler(_: Request, exc: UpstreamError):
    return JSONResponse(status_code=502, content={"detail": str(exc)})


def _known_country(country: str) -> str:
    key = country.lower()
    if key not in COUNTRY_CODES:
        raise HTTPException(
            status_code=404,
            detail=f"Country '{key}' not found. Available: {list(COUNTRY_CODES)}",
        )
    return key


@app.get("/")
def root():
    return {"message": "GridSense API is running!"}


@app.get("/health")
def health():
    return {
        "status": "ok",
        "entsoe_key_configured": bool(os.getenv("ENTSOE_API_KEY")),
        "cache_age_seconds": {**service.cache.ages(), **service.forecast_cache.ages()},
    }


@app.get("/energy/{country}")
def get_country_energy(country: str):
    return service.get_energy(_known_country(country))


@app.get("/energy")
def get_all_energy():
    return service.get_all_energy()


@app.get("/weather/{city}")
def get_city_weather(city: str):
    key = city.lower()
    if key not in CITY_COORDS:
        raise HTTPException(
            status_code=404,
            detail=f"City '{key}' not found. Available: {list(CITY_COORDS)}",
        )
    return service.get_weather(key)


@app.get("/weather")
def get_all_weather():
    return service.get_all_weather()


@app.get("/forecast")
def get_forecast():
    """Germany (kept for older clients); use /forecast/{country} for the others."""
    return service.get_forecast("germany")


@app.get("/forecast/{country}")
def get_country_forecast(country: str):
    return service.get_forecast(_known_country(country))


@app.get("/anomaly/{country}")
def get_anomaly(country: str):
    """Unusual load values of one country (forecast-residual method, z-score fallback)."""
    return service.get_anomalies(_known_country(country))
