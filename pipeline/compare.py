"""Compare every candidate model with the TSO over the last days (day-ahead walk-forward).

Usage (from the repo root):
    python -m pipeline.compare                    # real data, all countries (needs ENTSOE_API_KEY)
    python -m pipeline.compare --countries spain  # one country
    python -m pipeline.compare --synthetic        # offline smoke run

For each past day the models forecast the 24 hours using only data up to 10:00 UTC the day
before (see pipeline.trackrecord); the error is the mean absolute percentage miss against the
realised load on exactly the same hours for every column. Lower is better.
"""
import argparse

import pandas as pd

from pipeline.history import HistoryError, load_history, load_tso_forecast, synthetic_history, synthetic_tso
from pipeline.models import DEFAULT_MODELS, MODELS
from pipeline.trackrecord import TRACK_DAYS, day_ahead_frame
from pipeline.weather import WeatherError, load_weather, synthetic_weather


def compare_table(frame: pd.DataFrame, models, last_days: int = 7) -> pd.DataFrame:
    """MAPE (all days and last ``last_days``) and bias per column; ``frame`` has actual + models + tso."""
    columns = [c for c in [*models, "tso"] if c in frame]
    frame = frame.dropna(subset=["actual", *columns])  # the same hours for every column
    err = frame[columns].sub(frame["actual"], axis=0).div(frame["actual"], axis=0) * 100
    day_of = frame.index.floor("D")
    days = sorted(set(day_of))
    recent = day_of >= days[max(0, len(days) - last_days)]  # fewer days than the window: use them all
    table = pd.DataFrame(
        {
            "mape_all": err.abs().mean(),
            f"mape_{last_days}d": err[recent].abs().mean(),
            "bias": err.mean(),  # forecast minus actual, + means too high
        }
    )
    return table.round(2).sort_values("mape_all")


def main(argv=None) -> int:
    from backend.core.config import COUNTRY_CODES

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument("--countries", nargs="+", default=list(COUNTRY_CODES), choices=list(COUNTRY_CODES))
    parser.add_argument("--models", nargs="+", default=DEFAULT_MODELS, choices=list(MODELS))
    parser.add_argument("--days", type=int, default=TRACK_DAYS)
    parser.add_argument("--synthetic", action="store_true")
    args = parser.parse_args(argv)
    models = list(dict.fromkeys(["seasonal_naive"] + args.models))

    pd.options.display.float_format = "{:.2f}".format
    for i, country in enumerate(args.countries):
        print(f"\n=== {country.upper()} ===", flush=True)
        try:
            if args.synthetic:
                series = synthetic_history(90, seed=i)
                tso, weather = synthetic_tso(series, seed=i), synthetic_weather(series, seed=i)
            else:
                series = load_history(country, 90)
                tso = load_tso_forecast(country, 90)
                try:
                    weather = load_weather(country, 90)
                except WeatherError as exc:
                    print("temperature unavailable, temperature models skipped:", exc)
                    weather = None
        except HistoryError as exc:
            print("SKIPPED:", exc)
            continue
        reasons = {}
        frame = day_ahead_frame(series, models, country, weather, args.days, failures=reasons)
        frame["tso"] = tso.reindex(frame.index)
        for name in models:
            if name not in frame:
                print(f"could not run: {name} - {reasons.get(name, 'no forecast produced')}")
            elif name in reasons:
                print(f"partly failed: {name} - {reasons[name]}")
        table = compare_table(frame, models)
        print(table.to_string())
        ours = table.drop(index="tso", errors="ignore")
        best = ours["mape_all"].idxmin()
        if "tso" in table.index:
            gap = table.loc[best, "mape_all"] - table.loc["tso", "mape_all"]
            print(f"best model: {best} {table.loc[best, 'mape_all']}% | TSO {table.loc['tso', 'mape_all']}% | gap {gap:+.2f} points")
        else:
            print(f"best model: {best} {table.loc[best, 'mape_all']}% (no TSO data)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
