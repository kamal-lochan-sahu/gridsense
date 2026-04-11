# ⚡ GridSense

**Real-Time Industrial Energy Intelligence Platform**

Live Demo: [gridsense-eight.vercel.app](https://gridsense-eight.vercel.app)

---

## What is GridSense?

GridSense is a real-time energy intelligence dashboard built for European industrial operators, factory managers, and grid engineers.

It fetches live electricity load data from official European power grids and displays it in a clean, interactive dashboard.

---

## The Problem

- European energy grids are becoming unstable due to renewable energy unpredictability
- German industries lose €4+ billion annually from poor energy management
- No affordable real-time prediction tool exists for factory operators

---

## Features

- Live electricity load data for Germany, France, Spain, Poland
- Last 24hr energy load chart per country
- Max, Min, Average load statistics
- Live weather data for Berlin, Paris, Madrid, Warsaw
- Country selector — click any card to switch

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Frontend | Next.js 14, Tailwind CSS, Recharts |
| Backend | Python, FastAPI |
| Data | ENTSO-E API, Open-Meteo API |
| Deployment | Vercel + Render.com |

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
│   └── requirements.txt
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
