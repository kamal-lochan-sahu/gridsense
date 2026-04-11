import xml.etree.ElementTree as ET

# ENTSO-E XML ka namespace
NAMESPACE = {"ns": "urn:iec62325.351:tc57wg16:451-6:generationloaddocument:3:0"}


def parse_energy_xml(xml_text: str, country: str):
    """
    ENTSO-E ka raw XML parse karke clean data nikalo
    """
    try:
        root = ET.fromstring(xml_text)

        # Saare time periods aur values nikalo
        time_series_data = []

        for timeseries in root.findall("ns:TimeSeries", NAMESPACE):
            for period in timeseries.findall("ns:Period", NAMESPACE):

                # Time interval nikalo
                start_time = period.find(
                    "ns:timeInterval/ns:start", NAMESPACE
                ).text

                # Resolution nikalo (PT60M = 60 min interval)
                resolution = period.find("ns:resolution", NAMESPACE).text

                # Har point ki value nikalo
                points = []
                for point in period.findall("ns:Point", NAMESPACE):
                    position = point.find("ns:position", NAMESPACE).text
                    quantity = point.find("ns:quantity", NAMESPACE).text
                    points.append({
                        "position": int(position),
                        "load_mw": float(quantity)
                    })

                time_series_data.append({
                    "start_time": start_time,
                    "resolution": resolution,
                    "points": points
                })

        # Latest values nikalo
        all_loads = []
        for ts in time_series_data:
            for point in ts["points"]:
                all_loads.append(point["load_mw"])

        if all_loads:
            return {
                "country": country,
                "status": "success",
                "total_points": len(all_loads),
                "latest_load_mw": all_loads[-1],
                "max_load_mw": max(all_loads),
                "min_load_mw": min(all_loads),
                "avg_load_mw": round(sum(all_loads) / len(all_loads), 2),
                "all_loads": all_loads
            }
        else:
            return {
                "country": country,
                "status": "no_data",
                "message": "No time series data found"
            }

    except Exception as e:
        return {
            "country": country,
            "status": "error",
            "message": str(e)
        }


# Test karne ke liye
if __name__ == "__main__":
    from fetcher import get_energy_data

    print("⚡ Parsing Germany energy data...\n")
    raw = get_energy_data("Germany", "10Y1001A1001A83F")

    if raw["status"] == "success":
        result = parse_energy_xml(raw["raw_xml"], "Germany")
        print(f"Country: {result['country']}")
        print(f"Total data points: {result['total_points']}")
        print(f"Latest load: {result['latest_load_mw']} MW")
        print(f"Max load: {result['max_load_mw']} MW")
        print(f"Min load: {result['min_load_mw']} MW")
        print(f"Average load: {result['avg_load_mw']} MW")