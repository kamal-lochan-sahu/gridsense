"""Show the last hours of one country next to the same hour 1, 2 and 3 weeks ago.

Use it to judge whether a flagged anomaly is real or only the reference weeks being unusual:
    python -m pipeline.diagnose --country germany --hours 36
Lines where the actual load differs from the 3-week mean by more than 8% are marked '<<'.
"""
import argparse

import pandas as pd

from pipeline.history import load_history
from pipeline.models import shift_local, tz_of


def build_table(series: pd.Series, country: str, hours: int) -> pd.DataFrame:
    tz = tz_of(country)
    idx = series.index[-hours:]
    refs = {f"w-{k}": series.reindex(shift_local(idx, 7 * k, tz)).to_numpy() for k in (1, 2, 3)}
    table = pd.DataFrame(refs, index=idx)
    table.insert(0, "actual", series.reindex(idx).to_numpy())
    table["mean3"] = table[["w-1", "w-2", "w-3"]].mean(axis=1)
    table["dev_pct"] = (table["actual"] / table["mean3"] - 1) * 100
    table.insert(0, "local", idx.tz_convert(tz).strftime("%a %H:%M"))
    return table


def main(argv=None) -> int:
    from backend.core.config import COUNTRY_CODES

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument("--country", default="germany", choices=list(COUNTRY_CODES))
    parser.add_argument("--hours", type=int, default=36)
    args = parser.parse_args(argv)

    series = load_history(args.country, 45)
    table = build_table(series, args.country, args.hours)
    table["flag"] = (table["dev_pct"].abs() > 8).map({True: "<<", False: ""})
    pd.options.display.float_format = "{:,.1f}".format
    table.index = table.index.strftime("%m-%d %H:%MZ")
    print(f"{args.country}: last {args.hours} hours (UTC index, local weekday/hour in 'local')")
    print(table.to_string())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
