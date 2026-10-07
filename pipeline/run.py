"""Production run: for every country pick the best model, forecast 24h, flag anomalies.

Usage (from the repo root):
    python -m pipeline.run                       # real ENTSO-E data, writes pipeline/out/forecast.json
    python -m pipeline.run --synthetic           # offline smoke run
    python -m pipeline.run --previous old.json   # keep a country's last good entry if it fails now
"""
import argparse
import json
import os
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from pipeline.anomaly import robust_anomalies
from pipeline.champion import (
    MARGIN,
    champion_residuals,
    collect_predictions,
    score_table,
    select_champion,
)
from pipeline.history import HistoryError, load_history, synthetic_history
from pipeline.models import DEFAULT_MODELS, HORIZON, MODELS, run_model
from pipeline.weather import WeatherError, load_weather, synthetic_weather

SCHEMA_VERSION = 1
DEFAULT_OUT = Path(__file__).resolve().parent / "out" / "forecast.json"
INTERVAL_QUANTILES = (0.10, 0.90)  # -> an empirical 80% prediction interval

LABELS = {
    "seasonal_naive": "Seasonal naive (same hour last week)",
    "naive_avg3": "3-week seasonal average",
    "naive_daytype": "Holiday-aware 3-week average",
    "naive_level": "Level-adjusted weekly pattern",
    "ensemble": "Ensemble (Prophet + 3-week average)",
    "ensemble_temp": "Ensemble (Prophet + temperature, level-adjusted)",
    "prophet_tuned": "Prophet (weekday/off-day curves)",
    "prophet_temp": "Prophet + temperature",
    "prophet": "Prophet",
    "ets": "Holt-Winters (ETS)",
}
TEMPERATURE_MODELS = {"prophet_temp", "ensemble_temp"}


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def build_country_entry(country: str, series: pd.Series, candidates, n_origins: int, weather=None) -> dict:
    """Backtest the candidates, choose the champion, forecast and check anomalies."""
    preds, failures = collect_predictions(series, candidates, country, n_origins, weather=weather)
    table = score_table(preds)
    champion = select_champion(table)

    residuals = champion_residuals(series, champion, country, preds, weather=weather)
    rel = ((residuals["actual"] - residuals["yhat"]) / residuals["yhat"]).to_numpy()
    q_lo, q_hi = np.quantile(rel, INTERVAL_QUANTILES)

    forecast = run_model(champion, series, HORIZON, country, weather)
    if not np.isfinite(forecast["yhat"].to_numpy()).all():
        raise ValueError(f"{champion} produced a non-finite forecast")

    predictions = [
        {
            "ds": ts.strftime("%Y-%m-%d %H:%M:%S"),
            "yhat": round(float(row.yhat), 1),
            "yhat_lower": round(float(row.yhat * (1 + q_lo)), 1),
            "yhat_upper": round(float(row.yhat * (1 + q_hi)), 1),
        }
        for ts, row in forecast.iterrows()
    ]
    return {
        "model": champion,
        "model_label": LABELS.get(champion, champion),
        "data_until": series.index[-1].strftime("%Y-%m-%dT%H:%MZ"),
        "inputs": {"temperature": champion in TEMPERATURE_MODELS},
        "backtest": {
            "origins": int(preds["origin"].nunique()),
            "mape_pct": round(float(table.loc[champion, "mape_pct"]), 2),
            "mae_mw": round(float(table.loc[champion, "mae_mw"]), 1),
            "candidates_mape_pct": {m: round(float(v), 2) for m, v in table["mape_pct"].items()},
            "failures": {m: n for m, n in failures.items() if n},
            "selection_margin": MARGIN,
        },
        "interval": {
            "method": "empirical backtest residuals",
            "coverage": 0.8,
            "lower_pct": round(float(q_lo) * 100, 2),
            "upper_pct": round(float(q_hi) * 100, 2),
        },
        "predictions": predictions,
        "anomalies": robust_anomalies(residuals),
    }


def load_previous(path):
    if not path:
        return {}
    try:
        return json.loads(Path(path).read_text()).get("countries", {})
    except (OSError, ValueError):
        return {}


def write_atomic(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, indent=2, allow_nan=False)
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    with os.fdopen(fd, "w") as handle:
        handle.write(text)
    os.replace(tmp, path)


def run(countries, candidates, n_origins, history_days, synthetic, previous, use_weather=True) -> dict:
    entries, failed = {}, {}
    for i, country in enumerate(countries):
        started = time.perf_counter()
        print(f"[{country}] loading history...", flush=True)
        try:
            series = (
                synthetic_history(history_days, seed=i)
                if synthetic
                else load_history(country, history_days)
            )
            weather = None
            if use_weather:
                try:
                    weather = (
                        synthetic_weather(series, seed=i) if synthetic else load_weather(country, history_days)
                    )
                except WeatherError as exc:
                    print(f"[{country}] temperature unavailable, temperature models skipped: {exc}", flush=True)
            entry = build_country_entry(country, series, candidates, n_origins, weather)
        except (HistoryError, ValueError) as exc:
            failed[country] = str(exc)[:200]
            print(f"[{country}] FAILED: {failed[country]}", flush=True)
            if country in previous:
                entries[country] = {**previous[country], "carried_over": True}
            continue
        entries[country] = entry
        print(
            f"[{country}] champion={entry['model']} (backtest MAPE {entry['backtest']['mape_pct']}%), "
            f"{entry['anomalies']['total_anomalies']} anomalies, {time.perf_counter() - started:.0f}s",
            flush=True,
        )
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": utc_now().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "failed": failed,
        "countries": entries,
    }


def main(argv=None) -> int:
    from backend.core.config import COUNTRY_CODES

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument("--countries", nargs="+", default=list(COUNTRY_CODES), choices=list(COUNTRY_CODES))
    parser.add_argument("--candidates", nargs="+", default=DEFAULT_MODELS, choices=list(MODELS))
    parser.add_argument("--origins", type=int, default=10)
    parser.add_argument("--history-days", type=int, default=90)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--previous", help="earlier forecast.json to fall back on per country")
    parser.add_argument("--synthetic", action="store_true", help="fake data, no API key needed")
    parser.add_argument("--no-weather", action="store_true", help="do not load temperatures")
    args = parser.parse_args(argv)
    candidates = list(dict.fromkeys(["seasonal_naive"] + args.candidates))

    result = run(
        args.countries,
        candidates,
        args.origins,
        args.history_days,
        args.synthetic,
        load_previous(args.previous),
        use_weather=not args.no_weather,
    )
    fresh = [c for c, e in result["countries"].items() if not e.get("carried_over")]
    if not fresh:
        print("No country could be processed; nothing written.", file=sys.stderr)
        return 1

    write_atomic(args.out, result)
    print(f"\nWrote {args.out} ({len(result['countries'])} countries, {len(fresh)} fresh)")
    for country, entry in result["countries"].items():
        a = entry["anomalies"]
        print(
            f"  {country:8s} {entry['model']:15s} MAPE {entry['backtest']['mape_pct']:>5}%  "
            f"anomalies(24h): {a['total_anomalies']}  interval {entry['interval']['lower_pct']}%..{entry['interval']['upper_pct']}%"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
