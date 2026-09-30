from datetime import datetime, timedelta
from pathlib import Path

from data.parser import parse_energy_xml

NS = "urn:iec62325.351:tc57wg16:451-6:generationloaddocument:3:0"
FIXTURE = Path(__file__).parent / "fixtures" / "germany_sample.xml"


def make_xml(points, start="2026-01-01T00:00Z", end="2026-01-01T01:00Z", res="PT15M", curve=None):
    curve_xml = f"<curveType>{curve}</curveType>" if curve else ""
    body = "".join(
        f"<Point><position>{p}</position><quantity>{q}</quantity></Point>" for p, q in points
    )
    return (
        f'<?xml version="1.0"?><GL_MarketDocument xmlns="{NS}"><TimeSeries>{curve_xml}'
        f"<Period><timeInterval><start>{start}</start><end>{end}</end></timeInterval>"
        f"<resolution>{res}</resolution>{body}</Period></TimeSeries></GL_MarketDocument>"
    )


def test_real_germany_document():
    result = parse_energy_xml(FIXTURE.read_text(encoding="utf-8"), "Germany")
    assert result["status"] == "success"
    assert result["resolution_minutes"] == 15
    series = result["series"]
    assert len(series) == result["expected_points"]
    times = [datetime.strptime(p["time"], "%Y-%m-%dT%H:%MZ") for p in series]
    assert all(b - a == timedelta(minutes=15) for a, b in zip(times, times[1:]))
    assert result["latest_time"] == series[-1]["time"]
    assert result["min_load_mw"] <= result["avg_load_mw"] <= result["max_load_mw"]
    assert len(result["all_loads"]) == result["total_points"]


def test_gap_stays_none_and_is_excluded_from_stats():
    xml = make_xml([(1, 100), (2, 110), (4, 130)], curve="A01")
    result = parse_energy_xml(xml, "Test")
    assert [p["load_mw"] for p in result["series"]] == [100, 110, None, 130]
    assert result["missing_points"] == 1
    assert result["all_loads"] == [100, 110, 130]
    assert result["max_load_mw"] == 130
    assert result["latest_time"] == "2026-01-01T00:45Z"


def test_a03_forward_fills_omitted_points():
    xml = make_xml([(1, 100), (3, 120)], curve="A03")
    result = parse_energy_xml(xml, "Test")
    assert [p["load_mw"] for p in result["series"]] == [100, 100, 120, 120]
    assert result["filled_points"] == 2
    assert result["missing_points"] == 0


def test_hourly_resolution_timestamps():
    xml = make_xml([(1, 10), (2, 20), (3, 30)], end="2026-01-01T03:00Z", res="PT60M")
    result = parse_energy_xml(xml, "Test")
    assert result["resolution_minutes"] == 60
    assert [p["time"] for p in result["series"]] == [
        "2026-01-01T00:00Z",
        "2026-01-01T01:00Z",
        "2026-01-01T02:00Z",
    ]


def test_acknowledgement_document_is_no_data():
    xml = (
        '<Acknowledgement_MarketDocument xmlns="urn:iec62325.351:tc57wg16:451-1:acknowledgementdocument:7:0">'
        "<Reason><code>999</code><text>No matching data found</text></Reason>"
        "</Acknowledgement_MarketDocument>"
    )
    result = parse_energy_xml(xml, "Test")
    assert result["status"] == "no_data"
    assert "No matching data" in result["message"]


def test_invalid_xml_returns_error():
    assert parse_energy_xml("<not-xml", "Test")["status"] == "error"
