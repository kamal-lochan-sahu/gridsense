"""Rolling-origin backtest: which model forecasts the next 24h best, per country?

Usage (from the repo root):
    python -m pipeline.backtest --synthetic            # offline smoke run
    python -m pipeline.backtest                        # real ENTSO-E data (needs ENTSOE_API_KEY)
    python -m pipeline.backtest --countries germany spain --origins 10
"""
import argparse
import json
import time
from pathlib import Path

import numpy as np
import pandas as pd

from pipeline.champion import predict_origin
from pipeline.history import HistoryError, load_history, synthetic_history
from pipeline.models import DEFAULT_MODELS, HORIZON, MODELS
from pipeline.weather import WeatherError, load_weather, synthetic_weather

OUT_DIR = Path(__file__).resolve().parent / "out"


def rolling_origins(series: pd.Series, n_origins: int, horizon: int = HORIZON) -> list:
    """Midnight-UTC forecast origins, oldest first, each with a full ``horizon`` of actuals."""
    latest = (series.index[-1] - pd.Timedelta(hours=horizon - 1)).floor("D")
    return [latest - pd.Timedelta(days=i) for i in range(n_origins)][::-1]


def score(actual: np.ndarray, pred: pd.DataFrame) -> dict:
    mask = ~np.isnan(actual) & ~np.isnan(pred["yhat"].to_numpy())
    if mask.sum() < 12:
        return {"mae": np.nan, "mape": np.nan, "coverage": np.nan}
    a, p = actual[mask], pred["yhat"].to_numpy()[mask]
    lo, hi = pred["yhat_lower"].to_numpy()[mask], pred["yhat_upper"].to_numpy()[mask]
    coverage = np.nan if np.isnan(lo).any() else float(np.mean((a >= lo) & (a <= hi)))
    return {
        "mae": float(np.mean(np.abs(a - p))),
        "mape": float(np.mean(np.abs((a - p) / a)) * 100),
        "coverage": coverage,
    }


def run_backtest(series, model_names, n_origins: int = 7, horizon: int = HORIZON, country=None, weather=None):
    rows, memo = [], {}
    for origin in rolling_origins(series, n_origins, horizon):
        for name in model_names:
            started = time.perf_counter()
            try:
                pred = predict_origin(series, name, origin, country, horizon, weather, memo)
                if pred is None:  # not enough clean history before this origin
                    continue
                result = score(pred["actual"].to_numpy(dtype=float), pred)
                error = None
            except Exception as exc:  # one failing model must not stop the comparison
                result = {"mae": np.nan, "mape": np.nan, "coverage": np.nan}
                error = f"{type(exc).__name__}: {exc}"[:200]
            rows.append(
                {
                    "model": name,
                    "origin": origin.isoformat(),
                    "seconds": round(time.perf_counter() - started, 2),
                    "error": error,
                    **result,
                }
            )
    return pd.DataFrame(rows)


def summarize(results: pd.DataFrame) -> pd.DataFrame:
    grouped = results.groupby(["country", "model"])
    summary = grouped.agg(
        mae_mw=("mae", "mean"),
        mape_pct=("mape", "mean"),
        coverage=("coverage", "mean"),
        sec_per_fit=("seconds", "mean"),
        failures=("error", lambda s: int(s.notna().sum())),
        origins=("origin", "count"),
    ).round(2)
    baseline = summary["mape_pct"].xs("seasonal_naive", level="model", drop_level=False)
    base_by_country = baseline.droplevel("model")
    ref = summary.index.get_level_values("country").map(base_by_country)
    summary["vs_naive_pct"] = ((summary["mape_pct"] / np.asarray(ref) - 1) * 100).round(1)
    return summary


def main(argv=None) -> int:
    from backend.core.config import COUNTRY_CODES

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument("--countries", nargs="+", default=list(COUNTRY_CODES), choices=list(COUNTRY_CODES))
    parser.add_argument("--models", nargs="+", default=DEFAULT_MODELS, choices=list(MODELS))
    parser.add_argument("--history-days", type=int, default=90)
    parser.add_argument("--origins", type=int, default=14)
    parser.add_argument("--synthetic", action="store_true", help="use fake data (no API key needed)")
    parser.add_argument("--no-weather", action="store_true", help="skip temperature (temperature models then fail)")
    args = parser.parse_args(argv)
    args.models = list(dict.fromkeys(["seasonal_naive"] + args.models))  # baseline is always needed

    all_results = []
    for i, country in enumerate(args.countries):
        print(f"[{country}] loading history...", flush=True)
        try:
            series = (
                synthetic_history(args.history_days, seed=i)
                if args.synthetic
                else load_history(country, args.history_days)
            )
        except HistoryError as exc:
            print(f"[{country}] SKIPPED: {exc}")
            continue
        print(
            f"[{country}] {len(series)} hourly points, {series.index[0]:%Y-%m-%d} -> "
            f"{series.index[-1]:%Y-%m-%d %H:%M} UTC; backtesting {args.models}...",
            flush=True,
        )
        weather = None
        if not args.no_weather:
            try:
                weather = synthetic_weather(series, seed=i) if args.synthetic else load_weather(country, args.history_days)
            except WeatherError as exc:
                print(f"[{country}] temperature unavailable: {exc}")
        res = run_backtest(series, args.models, args.origins, country=country, weather=weather)
        res.insert(0, "country", country)
        all_results.append(res)

    if not all_results:
        print("No results.")
        return 1

    results = pd.concat(all_results, ignore_index=True)
    summary = summarize(results)
    print("\n=== Backtest summary (lower MAPE is better) ===")
    print(summary.to_string())

    print("\n=== Best model per country (by MAPE; vs_naive_pct < 0 means better than the baseline) ===")
    best = summary["mape_pct"].groupby(level="country").idxmin()
    for country, (_, model) in best.items():
        row = summary.loc[(country, model)]
        print(f"{country}: {model} ({row['mape_pct']}% MAPE, {row['vs_naive_pct']}% vs seasonal_naive)")

    OUT_DIR.mkdir(exist_ok=True)
    path = OUT_DIR / "backtest.json"
    path.write_text(json.dumps(results.to_dict(orient="records"), indent=2, default=str))
    print(f"\nDetails saved to {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
