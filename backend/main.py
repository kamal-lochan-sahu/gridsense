from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
from data.fetcher import get_energy_data, get_weather_data, get_all_energy_data, get_all_cities_weather
from data.parser import parse_energy_xml
from ml.forecaster import get_next_24hr_forecast
from ml.anomaly import detect_anomalies
import os

load_dotenv()

app = FastAPI(
    title="GridSense API",
    description="Real-Time Industrial Energy Intelligence Platform",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

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


@app.get("/")
def root():
    return {"message": "GridSense API is running!"}


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/energy/{country}")
def get_country_energy(country: str):
    country = country.lower()
    if country not in COUNTRY_CODES:
        raise HTTPException(
            status_code=404,
            detail=f"Country '{country}' not found. Available: {list(COUNTRY_CODES.keys())}"
        )
    raw = get_energy_data(country.capitalize(), COUNTRY_CODES[country])
    if raw["status"] != "success":
        raise HTTPException(status_code=500, detail=f"Failed to fetch data for {country}")
    parsed = parse_energy_xml(raw["raw_xml"], country.capitalize())
    return parsed


@app.get("/energy")
def get_all_energy():
    results = []
    for country, code in COUNTRY_CODES.items():
        raw = get_energy_data(country.capitalize(), code)
        if raw["status"] == "success":
            parsed = parse_energy_xml(raw["raw_xml"], country.capitalize())
            results.append(parsed)
    return results


@app.get("/weather/{city}")
def get_city_weather(city: str):
    city = city.lower()
    if city not in CITY_COORDS:
        raise HTTPException(
            status_code=404,
            detail=f"City '{city}' not found. Available: {list(CITY_COORDS.keys())}"
        )
    coords = CITY_COORDS[city]
    data = get_weather_data(
        latitude=coords["latitude"],
        longitude=coords["longitude"],
        city=city.capitalize()
    )
    return data


@app.get("/weather")
def get_all_weather():
    return get_all_cities_weather()


@app.get("/forecast")
def get_forecast():
    result = get_next_24hr_forecast()
    if result["status"] != "success":
        raise HTTPException(status_code=500, detail="Forecast model error")
    return result


@app.get("/anomaly/{country}")
def get_anomaly(country: str):
    """
    Ek country ka anomaly detection — unusual energy spikes flag karo
    """
    country = country.lower()
    if country not in COUNTRY_CODES:
        raise HTTPException(
            status_code=404,
            detail=f"Country '{country}' not found."
        )
    raw = get_energy_data(country.capitalize(), COUNTRY_CODES[country])
    if raw["status"] != "success":
        raise HTTPException(status_code=500, detail="Failed to fetch energy data")

    parsed = parse_energy_xml(raw["raw_xml"], country.capitalize())
    loads = parsed.get("all_loads", [])
    result = detect_anomalies(loads)
    result["country"] = country.capitalize()
    return result