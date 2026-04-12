# ⚡ GridSense

**Real-Time Industrial Energy Intelligence Platform**

Live Demo: [gridsense-eight.vercel.app](https://gridsense-eight.vercel.app)

---

## What is GridSense?

GridSense is a real-time energy intelligence dashboard built for European industrial operators, factory managers, and grid engineers. It fetches live electricity load data from official European power grids, runs ML forecasting, and detects anomalies in real-time.

---

## The Problem

- European energy grids are becoming unstable due to renewable energy unpredictability
- German industries lose €4+ billion annually from poor energy management
- No affordable real-time prediction tool exists for factory operators

---

## Features

- Live electricity load data for Germany, France, Spain, Poland
- Last 24hr energy load chart per country
- ML forecasting — next 24hr predictions using Prophet model
- Anomaly detection — unusual energy spikes flagged in real-time
- Max, Min, Average load statistics
- Live weather data for Berlin, Paris, Madrid, Warsaw
- Auto refresh every 5 minutes
- Mobile responsive design
- PWA — installable as mobile app

---

## ML Pipeline

- Data source: ENTSO-E API — 30 days of real European energy data
- Model: Facebook Prophet — time series forecasting
- Training: Google Colab (GPU T4)
- Output: Next 24hr energy consumption predictions with confidence intervals
- Anomaly Detection: Z-score method — flags unusual spikes (threshold: 2.0 std)

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Frontend | Next.js 14, Tailwind CSS, Recharts |
| Backend | Python, FastAPI |
| ML | Prophet, NumPy |
| Data | ENTSO-E API, Open-Meteo API |
| Deployment | Vercel + Render.com |

---

## API Endpoints

| Endpoint | Description |
|----------|-------------|
| `GET /energy` | All countries live energy data |
| `GET /energy/{country}` | Single country energy data |
| `GET /weather` | All cities weather data |
| `GET /weather/{city}` | Single city weather data |
| `GET /forecast` | Next 24hr ML predictions |
| `GET /anomaly/{country}` | Anomaly detection results |
| `GET /docs` | Swagger API documentation |

---

## Data Sources

- **ENTSO-E API** — Official European electricity transparency platform
- **Open-Meteo API** — Free weather data, no API key required

---

## Project Structure

gridsense/
├── frontend/
│   └── app/
│       ├── page.tsx        # Main dashboard
│       └── layout.tsx      # App layout
├── backend/
│   ├── main.py             # FastAPI server
│   ├── data/
│   │   ├── fetcher.py      # API data fetching
│   │   └── parser.py       # XML parser
│   ├── ml/
│   │   ├── forecaster.py   # Prophet forecasting
│   │   └── anomaly.py      # Z-score anomaly detection
│   └── requirements.txt
├── notebooks/
│   └── model_training.ipynb
└── README.md

---

## Local Setup

**Backend:**
```bash
cd backend
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
uvicorn main:app --reload
```

**Frontend:**
```bash
cd frontend
npm install
npm run dev
```

---

## Live URLs

- Frontend: https://gridsense-eight.vercel.app
- Backend API: https://gridsense-backend-k8pa.onrender.com
- API Docs: https://gridsense-backend-k8pa.onrender.com/docs

---

## Author

**Kamal Lochan Sahu**
Full Stack + ML Engineer
GitHub: [kamal-lochan-sahu](https://github.com/kamal-lochan-sahu)