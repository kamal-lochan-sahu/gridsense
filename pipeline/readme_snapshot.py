"""Regenerate the README accuracy snapshot from the published forecast.json.

The table in README.md sits between two HTML comment markers and this script rewrites only that
part, so the numbers are never typed by hand. Run it from the repository root whenever the
snapshot should be refreshed (it needs no extra packages):

    python -m pipeline.readme_snapshot                      # downloads the live forecast.json
    python -m pipeline.readme_snapshot --file forecast.json # or reads a local copy
"""
import argparse
import json
import re
import sys
import urllib.request
from datetime import date
from pathlib import Path

START = "<!-- snapshot:start -->"
END = "<!-- snapshot:end -->"
DEFAULT_URL = (
    "https://github.com/kamal-lochan-sahu/gridsense/releases/download/forecast-data/forecast.json"
)
README = Path(__file__).resolve().parent.parent / "README.md"
ORDER = ("germany", "france", "spain", "poland")
MONTHS = (
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
)


class SnapshotError(Exception):
    """The forecast file or the README does not have what the snapshot needs."""


def _day(text: str) -> str:
    day = date.fromisoformat(text)
    return f"{day.day} {MONTHS[day.month - 1]} {day.year}"


def _cell(value, best) -> str:
    if value is None:
        return "n/a"
    text = f"{value:.2f} %"
    return f"**{text}**" if value == best else text


def render(forecast: dict) -> str:
    """The text between the markers: one sentence and the table of the 7-day errors."""
    rows, last_days = [], []
    countries = forecast.get("countries") or {}
    for key in ORDER:
        record = (countries.get(key) or {}).get("track_record") or {}
        week = (record.get("summary") or {}).get("7d")
        daily = record.get("daily") or []
        if not week or not daily:
            continue
        values = [week.get("gridsense"), week.get("tso"), week.get("naive")]
        known = [v for v in values if v is not None]
        if not known:
            continue
        best = min(known)
        cells = [_cell(v, best) for v in values]
        rows.append(f"| {key.capitalize()} | " + " | ".join(cells) + " |")
        last_days.append(daily[-1]["date"])
    if not rows:
        raise SnapshotError("the forecast file has no track record to build a snapshot from")

    header = [
        f"Snapshot, average error over the 7 days to {_day(min(last_days))} "
        "(lower is better, generated from the published `forecast.json`):",
        "",
        "| Country | GridSense | TSO day-ahead | Same hour last week |",
        "| ------- | --------- | ------------- | ------------------- |",
    ]
    return "\n".join(header + rows)


def update_readme(text: str, block: str) -> str:
    pattern = re.compile(re.escape(START) + r".*?" + re.escape(END), re.DOTALL)
    if not pattern.search(text):
        raise SnapshotError(f"README.md has no {START} ... {END} markers")
    return pattern.sub(lambda _: f"{START}\n{block}\n{END}", text, count=1)


def load(file: str | None) -> dict:
    if file:
        return json.loads(Path(file).read_text(encoding="utf-8"))
    request = urllib.request.Request(DEFAULT_URL, headers={"User-Agent": "gridsense-readme-snapshot"})
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--file", help="local forecast.json instead of the published one")
    parser.add_argument("--readme", default=str(README), help="README to update")
    args = parser.parse_args(argv)
    try:
        block = render(load(args.file))
        path = Path(args.readme)
        path.write_text(update_readme(path.read_text(encoding="utf-8"), block), encoding="utf-8")
    except (SnapshotError, OSError, ValueError) as exc:
        print(f"snapshot not updated: {exc}", file=sys.stderr)
        return 1
    print(block)
    return 0


if __name__ == "__main__":
    sys.exit(main())
