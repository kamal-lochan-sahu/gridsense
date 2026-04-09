import requests
from datetime import datetime, timedelta
from dotenv import load_dotenv
import os

load_dotenv()

ENTSOE_API_KEY = os.getenv("ENTSOE_API_KEY")
ENTSOE_BASE_URL = "https://web-api.tp.entsoe.eu/api"
WEATHER_URL = "https://api.open-meteo.com/v1/forecast"

# European countries aur unke ENTSO-E codes
COUNTRY_CODES = {
    "Germany": "10Y1001A1001A83F",
    "France": "10YFR-RTE------C",
    "Spain": "10YES-REE------0",
    "Poland": "10YPL-AREA-----S",
}

# Weather cities
EUROPEAN_CITIES = [
    {"city": "Berlin", "latitude": 52.52, "longitude": 13.41},
    {"city": "Paris", "latitude": 48.85, "longitude": 2.35},
    {"city": "Madrid", "latitude": 40.42, "longitude": -3.70},
    {"city": "Warsaw", "latitude": 52.23, "longitude": 21.01},
]


def get_energy_data(country: str, country_code: str):
    """
    ENTSO-E se ek country ka live electricity load data fetch karo
    """
    now = datetime.utcnow()
    start = (now - timedelta(hours=24)).strftime("%Y%m%d%H00")
    end = now.strftime("%Y%m%d%H00")

    params = {
        "securityToken": ENTSOE_API_KEY,
        "documentType": "A65",
        "processType": "A16",
        "outBiddingZone_Domain": country_code,
        "periodStart": start,
        "periodEnd": end,
    }

    response = requests.get(ENTSOE_BASE_URL, params=params)

    if response.status_code == 200:
        return {
            "country": country,
            "status": "success",
            "data_length": len(response.text),
            "raw_xml": response.text[:500]
        }
    else:
        return {
            "country": country,
            "status": "error",
            "error_code": response.status_code,
            "message": response.text[:200]
        }


def get_weather_data(latitude: float, longitude: float, city: str):
    """
    Open-Meteo se weather data fetch karo
    """
    params = {
        "latitude": latitude,
        "longitude": longitude,
        "hourly": ["temperature_2m", "windspeed_10m", "cloudcover"],
        "forecast_days": 2,
        "timezone": "Europe/Berlin"
    }

    response = requests.get(WEATHER_URL, params=params)
    data = response.json()

    return {
        "city": city,
        "timezone": data["timezone"],
        "hourly_time": data["hourly"]["time"],
        "temperature": data["hourly"]["temperature_2m"],
        "windspeed": data["hourly"]["windspeed_10m"],
        "cloudcover": data["hourly"]["cloudcover"]
    }


def get_all_energy_data():
    """
    Saare countries ka energy data fetch karo
    """
    results = []
    for country, code in COUNTRY_CODES.items():
        data = get_energy_data(country, code)
        results.append(data)
        print(f"⚡ {country}: {data['status']}")
    return results


def get_all_cities_weather():
    """
    Saari cities ka weather fetch karo
    """
    results = []
    for city_info in EUROPEAN_CITIES:
        data = get_weather_data(
            latitude=city_info["latitude"],
            longitude=city_info["longitude"],
            city=city_info["city"]
        )
        results.append(data)
        print(f"🌤️ {city_info['city']} weather fetched")
    return results


if __name__ == "__main__":
    print("⚡ Fetching ENTSO-E Energy Data...\n")
    energy_data = get_all_energy_data()

    print("\n🌍 Fetching Weather Data...\n")
    weather_data = get_all_cities_weather()

    print("\n📊 Sample — Germany Energy:")
    germany = energy_data[0]
    print(f"Status: {germany['status']}")
    if germany['status'] == 'success':
        print(f"Data received: {germany['data_length']} bytes")

    print("\n📊 Sample — Berlin Weather:")
    berlin = weather_data[0]
    print(f"Temperature: {berlin['temperature'][0]}°C")
    print(f"Wind Speed: {berlin['windspeed'][0]} km/h")