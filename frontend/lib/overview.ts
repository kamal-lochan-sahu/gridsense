import type { AnomalyData, ForecastData } from "./types";

/** What the country cards show at a glance, for every country and not only the selected one. */
export interface CountryOverview {
  anomalies: number | null; // null = unknown (the request failed)
  peak: { mw: number; time: string } | null; // highest forecast hour, time as "YYYY-MM-DD HH:MM:SS" UTC
}

export function summarizeCountry(
  anomaly: AnomalyData | null,
  forecast: ForecastData | null
): CountryOverview {
  const anomalies = anomaly && anomaly.status === "success" ? anomaly.total_anomalies : null;
  let peak: CountryOverview["peak"] = null;
  if (forecast && forecast.status === "success") {
    for (const point of forecast.predictions) {
      if (!peak || point.yhat > peak.mw) peak = { mw: point.yhat, time: point.ds };
    }
  }
  return { anomalies, peak };
}

/** "2026-11-04 19:00:00" -> "19:00 UTC" (the forecast chart is in UTC too). */
export function peakTimeLabel(time: string): string {
  return `${time.slice(11, 16)} UTC`;
}
