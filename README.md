# ⚡ GridSense

[![CI](https://github.com/kamal-lochan-sahu/gridsense/actions/workflows/ci.yml/badge.svg)](https://github.com/kamal-lochan-sahu/gridsense/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

**Real-time electricity load dashboard for European grids.**

- Live app: <https://gridsense-eight.vercel.app>
- API: <https://gridsense-backend-k8pa.onrender.com> ([interactive docs](https://gridsense-backend-k8pa.onrender.com/docs))

> The API runs on a free Render instance. After a period of inactivity the first request can take up to a minute while the server wakes up.

## What it does

GridSense pulls official actual-load data from the ENTSO-E Transparency Platform for Germany, France, Spain and Poland and shows it next to local weather, an anomaly check and a 24-hour forecast.

- **Load chart per country**: the last 24 hours in 15-minute steps, with real timestamps shown in your local time, plus max / average / min.
- **Anomaly detection**: flags load values more than 2 standard deviations from the 24-hour mean (z-score) and shows when they happened.
- **Weather**: current temperature, wind speed and cloud cover for Berlin, Paris, Madrid and Warsaw (Open-Meteo).
- **Forecast**: Prophet predictions for Germany. These are currently a **static file generated in April 2026**; the UI says so. Automatic retraining is planned (see roadmap).
- **Resilient by design**: results are cached, data providers are called in parallel with timeouts and retries, and if a provider fails the API serves the last good data (flagged `"stale": true`) or a clear `502` error instead of made-up values.
- Auto-refresh every 5 minutes, responsive layout.

ENTSO-E publishes load data with a delay of roughly one hour, so the newest point is never "now". Each card shows the time of its latest value.

## Architecture

```
Browser ── Next.js dashboard (Vercel)
              │  fetch (JSON)
              ▼
        FastAPI backend (Render) ── TTL cache ──┬─ ENTSO-E Transparency Platform (load, XML)
                                                └─ Open-Meteo (weather, JSON)
```

| Layer    | Technology                                         |
| -------- | -------------------------------------------------- |
| Frontend | Next.js 16, React 19, Tailwind CSS 4, Recharts      |
| Backend  | Python 3.12, FastAPI, requests, NumPy               |
| Data     | ENTSO-E Transparency Platform, Open-Meteo           |
| Forecast | Prophet (pre-computed predictions)                  |
| Hosting  | Vercel (frontend), Render (backend)                 |
| CI       | GitHub Actions                                      |

## API

| Endpoint                 | Description                                                    |
| ------------------------ | -------------------------------------------------------------- |
| `GET /energy`            | 24h load of all countries (countries that fail are skipped)    |
| `GET /energy/{country}`  | 24h load of one country: `germany`, `france`, `spain`, `poland` |
| `GET /anomaly/{country}` | Anomalies in the 24h load of one country                       |
| `GET /weather`           | Hourly weather for all cities                                  |
| `GET /weather/{city}`    | Hourly weather for one city: `berlin`, `paris`, `madrid`, `warsaw` |
| `GET /forecast`          | Pre-computed 24h forecast (Germany)                            |
| `GET /health`            | Liveness, configuration check and cache ages                   |

Energy responses include a timestamped `series` (`{time, load_mw}`, `null` marks a real gap), the resolution, summary statistics, `fetched_at` and `stale`. Unknown regions return `404`; an unavailable data provider returns `502` with a `detail` message.

## Project structure

```
gridsense/
├── backend/
│   ├── main.py            # FastAPI app and routes
│   ├── core/              # config, TTL cache, cached data service
│   ├── data/              # ENTSO-E / Open-Meteo clients, ENTSO-E XML parser
│   ├── ml/                # anomaly detection, forecast loader
│   ├── models/            # pre-computed Prophet predictions
│   └── tests/             # pytest suite (no network access needed)
├── frontend/
│   ├── app/               # Next.js app router: dashboard page and layout
│   ├── lib/               # API client, types, formatting helpers
│   └── public/            # icons and manifest
├── docs/                  # project notes
├── render.yaml            # Render service definition
└── .github/workflows/     # CI
```

## Run it locally

You need Python 3.11+ (3.12 recommended), Node.js 20+ and a free [ENTSO-E API token](https://transparency.entsoe.eu/) (register an account, email the platform support to enable RESTful API access, then copy the token from your account settings).

**Backend**

```bash
cd backend
python3 -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt
echo "ENTSOE_API_KEY=your_token_here" > .env
uvicorn main:app --reload
```

The API is now on <http://localhost:8000> (docs at `/docs`).

**Frontend**

```bash
cd frontend
npm ci
echo "NEXT_PUBLIC_API_URL=http://localhost:8000" > .env.local
npm run dev
```

Open <http://localhost:3000>. Without `NEXT_PUBLIC_API_URL` the frontend uses the production API.

## Configuration

| Variable               | Where    | Default       | Purpose                                          |
| ---------------------- | -------- | ------------- | ------------------------------------------------ |
| `ENTSOE_API_KEY`       | backend  | (required)    | ENTSO-E web API security token                   |
| `ENERGY_TTL_SECONDS`   | backend  | `300`         | How long load data is cached                     |
| `WEATHER_TTL_SECONDS`  | backend  | `1800`        | How long weather data is cached                  |
| `MAX_STALE_SECONDS`    | backend  | `21600`       | Oldest cached data served when a provider fails  |
| `CORS_ORIGINS`         | backend  | `*`           | Comma-separated list of allowed origins          |
| `LOG_LEVEL`            | backend  | `INFO`        | Python logging level                             |
| `NEXT_PUBLIC_API_URL`  | frontend | production API | Base URL of the backend                         |

## Tests

```bash
# backend
cd backend
pip install -r requirements-dev.txt
python -m pytest

# frontend
cd frontend
npm run lint && npx tsc --noEmit && npm run build
```

CI runs both on every push to `main` and on pull requests.

## Deployment

- **Backend**: Render web service from `render.yaml` (root directory `backend`, health check `/health`). Set `ENTSOE_API_KEY` in the service environment.
- **Frontend**: Vercel project with root directory `frontend`. Optionally set `NEXT_PUBLIC_API_URL`.

## Roadmap

- Live forecasting: scheduled retraining on fresh ENTSO-E data for every country, replacing the static predictions.
- Better anomaly detection that accounts for the daily load pattern (for example residuals against the forecast).
- More bidding zones and data types (generation mix, cross-border flows).

## Data sources

- Electricity load: [ENTSO-E Transparency Platform](https://transparency.entsoe.eu/)
- Weather: [Open-Meteo](https://open-meteo.com/) (CC BY 4.0)

## License

[MIT](LICENSE) © Kamal Lochan Sahu
