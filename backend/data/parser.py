"""Parser for ENTSO-E load documents (documentType A65).

Every point gets a real UTC timestamp: start + (position - 1) * resolution.
Missing positions are handled according to the series curve type:
  * A03 (variable sized blocks): an omitted point repeats the previous value.
  * anything else: the point is a real gap and stays None in ``series``.
"""
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

_RESOLUTION_RE = re.compile(r"^PT(?:(\d+)H)?(?:(\d+)M)?$")


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _child(element, name):
    for child in element:
        if _local(child.tag) == name:
            return child
    return None


def _children(element, name):
    return [child for child in element if _local(child.tag) == name]


def _resolution_minutes(text):
    match = _RESOLUTION_RE.match(text or "")
    if not match or not (match.group(1) or match.group(2)):
        raise ValueError(f"Unsupported resolution: {text!r}")
    return int(match.group(1) or 0) * 60 + int(match.group(2) or 0)


def _parse_time(text: str) -> datetime:
    parsed = datetime.fromisoformat(text.strip().replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _format_time(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%dT%H:%MZ")


def parse_energy_xml(xml_text: str, country: str) -> dict:
    """Parse a raw ENTSO-E XML document into a clean, timestamped load series."""
    try:
        root = ET.fromstring(xml_text)

        if _local(root.tag) == "Acknowledgement_MarketDocument":
            reason = _child(root, "Reason")
            text_el = _child(reason, "text") if reason is not None else None
            message = text_el.text if text_el is not None and text_el.text else "No matching data found"
            return {"country": country, "status": "no_data", "message": message}

        points = {}
        resolution = None
        filled = 0

        for series_el in _children(root, "TimeSeries"):
            curve_el = _child(series_el, "curveType")
            forward_fill = curve_el is not None and (curve_el.text or "").strip() == "A03"

            for period in _children(series_el, "Period"):
                interval = _child(period, "timeInterval")
                start = _parse_time(_child(interval, "start").text)
                end = _parse_time(_child(interval, "end").text)
                resolution = _resolution_minutes(_child(period, "resolution").text)
                step = timedelta(minutes=resolution)
                expected = int((end - start) / step)

                by_position = {}
                for point in _children(period, "Point"):
                    position = int(_child(point, "position").text)
                    by_position[position] = float(_child(point, "quantity").text)

                last_value = None
                for position in range(1, expected + 1):
                    moment = start + (position - 1) * step
                    if position in by_position:
                        last_value = by_position[position]
                        points[moment] = last_value
                    elif forward_fill and last_value is not None:
                        points[moment] = last_value
                        filled += 1
                    else:
                        points.setdefault(moment, None)

        if not points:
            return {"country": country, "status": "no_data", "message": "No time series data found"}

        ordered = sorted(points.items())
        values = [value for _, value in ordered if value is not None]
        if not values:
            return {"country": country, "status": "no_data", "message": "Series contains no values"}

        latest_time = max(moment for moment, value in ordered if value is not None)

        return {
            "country": country,
            "status": "success",
            "resolution_minutes": resolution,
            "expected_points": len(ordered),
            "total_points": len(values),
            "missing_points": len(ordered) - len(values),
            "filled_points": filled,
            "latest_time": _format_time(latest_time),
            "latest_load_mw": points[latest_time],
            "max_load_mw": max(values),
            "min_load_mw": min(values),
            "avg_load_mw": round(sum(values) / len(values), 2),
            "all_loads": values,
            "series": [
                {"time": _format_time(moment), "load_mw": value} for moment, value in ordered
            ],
        }
    except Exception as exc:  # malformed XML or unexpected structure
        return {"country": country, "status": "error", "message": str(exc)}
