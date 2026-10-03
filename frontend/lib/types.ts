export interface SeriesPoint {
  time: string; // ISO-8601 UTC, e.g. 2026-09-30T00:45Z
  load_mw: number | null; // null = real gap in the source data
}

export interface EnergyData {
  country: string;
  status: string;
  resolution_minutes?: number;
  expected_points?: number;
  total_points: number;
  missing_points?: number;
  filled_points?: number;
  latest_time?: string;
  latest_load_mw: number;
  max_load_mw: number;
  min_load_mw: number;
  avg_load_mw: number;
  all_loads: number[];
  series?: SeriesPoint[];
}

export interface WeatherData {
  city: string;
  timezone: string;
  hourly_time: string[];
  temperature: number[];
  windspeed: number[];
  cloudcover: number[];
}

export interface ForecastPoint {
  ds: string;
  yhat: number;
  yhat_lower: number;
  yhat_upper: number;
}

export interface ForecastData {
  status: string;
  country: string;
  model: string;
  total_predictions: number;
  predictions: ForecastPoint[];
  source?: "pipeline" | "static";
  backtest_mape_pct?: number; // accuracy of the chosen model over the last backtest days
  generated_at?: string; // ISO-8601 UTC, when the pipeline produced this forecast
  data_until?: string;
  carried_over?: boolean; // the last pipeline run failed for this country; older forecast shown
}

export interface AnomalyPoint {
  position?: number; // live z-score fallback: index into the non-null values of the energy series
  time?: string; // pipeline method: ISO-8601 UTC hour, e.g. 2026-10-02T10:00Z
  load_mw: number;
  expected_mw?: number; // what the forecast model predicted for that hour
  deviation_pct?: number; // actual vs expected, in percent
  z_score: number;
  deviation: "HIGH" | "LOW";
}

export interface AnomalyData {
  status: string;
  country: string;
  total_anomalies: number;
  mean_load?: number;
  std_load?: number;
  source?: "pipeline" | "live-zscore";
  method?: string;
  typical_error_pct?: number;
  anomalies: AnomalyPoint[];
}
