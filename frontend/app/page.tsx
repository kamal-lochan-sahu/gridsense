"use client";

import { useCallback, useEffect, useState } from "react";
import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { getJson } from "@/lib/api";
import { formatDateTime, formatTime } from "@/lib/format";
import { currentHourIndex } from "@/lib/weather";
import type {
  AnomalyData,
  EnergyData,
  ForecastData,
  TrackRecordData,
  TrackRecordWindow,
  WeatherData,
} from "@/lib/types";

const REFRESH_INTERVAL = 5 * 60 * 1000;
const EXPECTED_COUNTRIES = ["Germany", "France", "Spain", "Poland"];

const TOOLTIP_STYLE = {
  backgroundColor: "#1F2937",
  border: "1px solid #374151",
  borderRadius: "8px",
  fontSize: "12px",
};

function describeError(reason: unknown): string {
  return reason instanceof Error ? reason.message : "unknown error";
}

const TRACK_ROWS: Array<{ key: string; label: string }> = [
  { key: "7d", label: "Last 7 days" },
  { key: "14d", label: "Last 14 days" },
];

function TrackRecordCard({ data }: { data: TrackRecordData }) {
  const hasTso = data.sources.includes("tso");
  const chartData = data.hourly.map((h) => ({
    time: h.ds.slice(5, 16),
    actual: h.actual,
    gridsense: h.gridsense,
    tso: h.tso ?? undefined,
  }));

  const cell = (window: TrackRecordWindow, value: number | undefined) => {
    if (value === undefined) return <td className="py-2 pr-4 text-gray-500">n/a</td>;
    const candidates = [window.gridsense, window.naive, window.tso].filter(
      (v): v is number => v !== undefined
    );
    const best = value === Math.min(...candidates);
    return (
      <td className={`py-2 pr-4 ${best ? "text-green-400 font-semibold" : "text-gray-300"}`}>
        {value.toFixed(2)}%
      </td>
    );
  };

  return (
    <div className="bg-gray-900 rounded-xl p-4 md:p-6 mb-6 border border-green-800">
      <h2 className="text-base md:text-lg font-semibold mb-1 text-green-400">
        Track record — {data.country}: day-ahead accuracy
      </h2>
      <p className="text-gray-500 text-xs mb-4">
        Each day is forecast at {data.origin_hour_utc}:00 UTC the day before
        {hasTso ? ", about when the grid operator (TSO) publishes its own forecast," : ""} and then compared with
        what really happened. Error is the average percentage miss; lower is better, green is the best.
      </p>
      <div className="overflow-x-auto mb-4">
        <table className="text-sm">
          <thead>
            <tr className="text-gray-400 text-xs text-left">
              <th className="py-2 pr-4 font-normal">Average error</th>
              <th className="py-2 pr-4 font-normal">GridSense</th>
              {hasTso && <th className="py-2 pr-4 font-normal">TSO day-ahead</th>}
              <th className="py-2 pr-4 font-normal">Same hour last week</th>
            </tr>
          </thead>
          <tbody>
            {TRACK_ROWS.filter((row) => data.summary[row.key]).map((row) => {
              const window = data.summary[row.key];
              return (
                <tr key={row.key} className="border-t border-gray-800">
                  <td className="py-2 pr-4 text-gray-400">{row.label}</td>
                  {cell(window, window.gridsense)}
                  {hasTso && cell(window, window.tso)}
                  {cell(window, window.naive)}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <p className="text-gray-500 text-xs mb-2">Last 3 days, hourly (UTC) — model: {data.model}</p>
      <ResponsiveContainer width="100%" height={250}>
        <LineChart data={chartData}>
          <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
          <XAxis dataKey="time" stroke="#9CA3AF" tick={{ fontSize: 11 }} minTickGap={40} />
          <YAxis stroke="#9CA3AF" tick={{ fontSize: 11 }} domain={["auto", "auto"]} />
          <Tooltip contentStyle={TOOLTIP_STYLE} />
          <Legend />
          <Line type="monotone" dataKey="actual" stroke="#F3F4F6" strokeWidth={2} dot={false} name="Actual (MW)" />
          <Line type="monotone" dataKey="gridsense" stroke="#60A5FA" strokeWidth={2} dot={false} name="GridSense (MW)" />
          {hasTso && (
            <Line
              type="monotone"
              dataKey="tso"
              stroke="#FB923C"
              strokeWidth={1.5}
              dot={false}
              strokeDasharray="4 3"
              name="TSO day-ahead (MW)"
            />
          )}
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

function SplashScreen() {
  const [progress, setProgress] = useState(0);
  const [text, setText] = useState("Connecting to European grid...");
  const [slow, setSlow] = useState(false);

  useEffect(() => {
    const messages = [
      "Connecting to European grid...",
      "Fetching live energy data...",
      "Loading weather systems...",
      "Preparing dashboard...",
    ];
    let step = 0;
    const interval = setInterval(() => {
      step++;
      setProgress((step / messages.length) * 100);
      if (step < messages.length) setText(messages[step]);
      if (step >= messages.length) clearInterval(interval);
    }, 600);
    const slowTimer = setTimeout(() => setSlow(true), 6000);
    return () => {
      clearInterval(interval);
      clearTimeout(slowTimer);
    };
  }, []);

  return (
    <div className="fixed inset-0 bg-gray-950 flex flex-col items-center justify-center z-50">
      <div className="mb-8 flex flex-col items-center">
        <div className="text-6xl mb-4 animate-bounce">⚡</div>
        <h1 className="text-4xl font-bold text-green-400 tracking-widest">GRIDSENSE</h1>
        <p className="text-gray-500 text-sm mt-2 tracking-wider">REAL-TIME ENERGY INTELLIGENCE</p>
      </div>
      <div className="w-64 mt-8">
        <div className="h-1 bg-gray-800 rounded-full overflow-hidden">
          <div
            className="h-full bg-green-400 rounded-full transition-all duration-500"
            style={{ width: `${progress}%` }}
          />
        </div>
        <p className="text-gray-500 text-xs mt-3 text-center">{text}</p>
        {slow && (
          <p className="text-yellow-500 text-xs mt-2 text-center">
            The server is waking up. The first load can take up to a minute.
          </p>
        )}
      </div>
    </div>
  );
}

export default function Home() {
  const [energyData, setEnergyData] = useState<EnergyData[]>([]);
  const [weatherData, setWeatherData] = useState<WeatherData[]>([]);
  const [forecastData, setForecastData] = useState<ForecastData | null>(null);
  const [forecastError, setForecastError] = useState<string | null>(null);
  const [trackRecord, setTrackRecord] = useState<TrackRecordData | null>(null);
  const [anomalyData, setAnomalyData] = useState<AnomalyData | null>(null);
  const [selectedCountry, setSelectedCountry] = useState("germany");
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [updatedAt, setUpdatedAt] = useState<number | null>(null);
  const [errors, setErrors] = useState<string[]>([]);
  const [refreshCount, setRefreshCount] = useState(0);

  const load = useCallback(async () => {
    const [energy, weather] = await Promise.allSettled([
      getJson<EnergyData[]>("/energy"),
      getJson<WeatherData[]>("/weather"),
    ]);
    const problems: string[] = [];

    if (energy.status === "fulfilled" && Array.isArray(energy.value)) {
      setEnergyData(energy.value);
      const present = energy.value.map((d) => d.country);
      const missing = EXPECTED_COUNTRIES.filter((c) => !present.includes(c));
      if (missing.length > 0) problems.push(`No energy data for: ${missing.join(", ")}`);
    } else {
      problems.push(
        `Energy data: ${energy.status === "rejected" ? describeError(energy.reason) : "unexpected response"}`
      );
    }

    if (weather.status === "fulfilled" && Array.isArray(weather.value)) {
      setWeatherData(weather.value);
    } else {
      problems.push(
        `Weather: ${weather.status === "rejected" ? describeError(weather.reason) : "unexpected response"}`
      );
    }

    setErrors(problems);
    setUpdatedAt(Date.now());
    setRefreshCount((n) => n + 1);
  }, []);

  const refresh = useCallback(async () => {
    setRefreshing(true);
    try {
      await load();
    } finally {
      setRefreshing(false);
    }
  }, [load]);

  useEffect(() => {
    void load().finally(() => setLoading(false));
    const timer = setInterval(() => void refresh(), REFRESH_INTERVAL);
    return () => clearInterval(timer);
  }, [load, refresh]);

  // Forecast and anomalies are fetched for the selected country, after each (re)load of the dashboard.
  useEffect(() => {
    if (refreshCount === 0) return;
    const controller = new AbortController();
    getJson<ForecastData>(`/forecast/${selectedCountry}`, controller.signal)
      .then((data) => {
        const ok = data.status === "success";
        setForecastData(ok ? data : null);
        setForecastError(ok ? null : "model returned an error");
      })
      .catch((reason: unknown) => {
        if (controller.signal.aborted) return;
        setForecastData(null);
        setForecastError(describeError(reason));
      });
    return () => controller.abort();
  }, [selectedCountry, refreshCount]);

  // The track record is an extra: if it is missing (404) or fails, the card is simply not shown.
  useEffect(() => {
    if (refreshCount === 0) return;
    const controller = new AbortController();
    getJson<TrackRecordData>(`/trackrecord/${selectedCountry}`, controller.signal)
      .then((data) => setTrackRecord(data.status === "success" ? data : null))
      .catch(() => {
        if (!controller.signal.aborted) setTrackRecord(null);
      });
    return () => controller.abort();
  }, [selectedCountry, refreshCount]);

  // Anomalies are fetched for the selected country, after each (re)load of the dashboard.
  useEffect(() => {
    if (refreshCount === 0) return;
    const controller = new AbortController();
    getJson<AnomalyData>(`/anomaly/${selectedCountry}`, controller.signal)
      .then(setAnomalyData)
      .catch(() => {
        if (!controller.signal.aborted) setAnomalyData(null);
      });
    return () => controller.abort();
  }, [selectedCountry, refreshCount]);

  if (loading) return <SplashScreen />;

  const selectedEnergy = energyData.find((d) => d.country.toLowerCase() === selectedCountry);
  const series = selectedEnergy?.series ?? [];
  const loadedPoints = series.filter((p) => p.load_mw !== null);

  const chartData = series.map((p) => ({
    label: formatTime(p.time),
    full: formatDateTime(p.time),
    load_mw: p.load_mw === null ? null : Math.round(p.load_mw),
  }));

  const anomaly =
    anomalyData && anomalyData.country.toLowerCase() === selectedCountry ? anomalyData : null;

  const selectedForecast =
    forecastData && forecastData.country.toLowerCase() === selectedCountry ? forecastData : null;

  const forecastChartData = selectedForecast?.predictions.map((p) => ({
    time: p.ds.slice(11, 16),
    predicted: Math.round(p.yhat),
    upper: Math.round(p.yhat_upper),
    lower: Math.round(p.yhat_lower),
  }));

  const forecastFirst = selectedForecast?.predictions[0]?.ds;
  const forecastLast = selectedForecast?.predictions[selectedForecast.predictions.length - 1]?.ds;
  const forecastEnd = forecastLast ? Date.parse(`${forecastLast.replace(" ", "T")}Z`) : NaN;
  const forecastStale = updatedAt !== null && Number.isFinite(forecastEnd) && forecastEnd < updatedAt;

  return (
    <main className="min-h-screen bg-gray-950 text-white p-4 md:p-6">
      {/* Header */}
      <div className="mb-6 flex flex-col md:flex-row md:items-center md:justify-between">
        <div>
          <h1 className="text-2xl md:text-3xl font-bold text-green-400">⚡ GridSense</h1>
          <p className="text-gray-400 text-sm mt-1">
            Real-Time Industrial Energy Intelligence Platform
          </p>
        </div>
        <div className="mt-3 md:mt-0 flex items-center gap-3">
          {updatedAt !== null && (
            <p className="text-gray-500 text-xs">
              Last updated: {new Date(updatedAt).toLocaleTimeString()}
            </p>
          )}
          <button
            onClick={() => void refresh()}
            disabled={refreshing}
            className="px-3 py-1 text-xs bg-green-400 text-gray-950 rounded-lg font-semibold hover:bg-green-300 disabled:opacity-50 transition-all"
          >
            {refreshing ? "Refreshing..." : "⟳ Refresh"}
          </button>
        </div>
      </div>

      {/* Load problems */}
      {errors.length > 0 && (
        <div role="alert" className="mb-6 p-4 bg-yellow-950 border border-yellow-600 rounded-xl">
          <h3 className="text-yellow-400 font-semibold text-sm mb-2">
            Some data could not be loaded
          </h3>
          <ul className="text-yellow-200 text-xs space-y-1 list-disc list-inside">
            {errors.map((message) => (
              <li key={message}>{message}</li>
            ))}
          </ul>
          <button
            onClick={() => void refresh()}
            disabled={refreshing}
            className="mt-3 px-3 py-1 text-xs bg-yellow-400 text-gray-950 rounded-lg font-semibold hover:bg-yellow-300 disabled:opacity-50"
          >
            {refreshing ? "Retrying..." : "Try again"}
          </button>
        </div>
      )}

      {/* Anomaly Alert */}
      {anomaly && anomaly.total_anomalies > 0 && (
        <div className="mb-6 p-4 bg-red-900 border border-red-500 rounded-xl">
          <h3 className="text-red-400 font-semibold text-sm mb-2">
            ⚠️ {anomaly.total_anomalies} {anomaly.total_anomalies === 1 ? "anomaly" : "anomalies"}{" "}
            detected in the {anomaly.country} grid
          </h3>
          <div className="flex flex-wrap gap-2">
            {anomaly.anomalies.map((a) => {
              const at = a.time ?? (a.position !== undefined ? loadedPoints[a.position]?.time : undefined);
              return (
                <span
                  key={a.time ?? a.position}
                  className={`text-xs px-2 py-1 rounded-full ${
                    a.deviation === "HIGH"
                      ? "bg-red-700 text-red-200"
                      : "bg-yellow-800 text-yellow-200"
                  }`}
                >
                  {a.deviation} {Math.round(a.load_mw).toLocaleString()} MW
                  {at ? ` at ${formatTime(at)}` : ""}
                  {a.deviation_pct !== undefined
                    ? ` (${a.deviation_pct > 0 ? "+" : ""}${a.deviation_pct}% vs forecast, z=${a.z_score})`
                    : ` (z=${a.z_score})`}
                </span>
              );
            })}
          </div>
        </div>
      )}

      {/* Energy Cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-6">
        {energyData.map((country) => {
          const selected = selectedCountry === country.country.toLowerCase();
          return (
            <button
              type="button"
              key={country.country}
              aria-pressed={selected}
              onClick={() => setSelectedCountry(country.country.toLowerCase())}
              className={`p-3 md:p-4 rounded-xl cursor-pointer border transition-all text-left ${
                selected
                  ? "border-green-400 bg-gray-800"
                  : "border-gray-700 bg-gray-900 hover:border-gray-500"
              }`}
            >
              <p className="text-gray-400 text-xs md:text-sm">{country.country}</p>
              <p className="text-xl md:text-2xl font-bold text-white mt-1">
                {Math.round(country.latest_load_mw).toLocaleString()}
              </p>
              <p className="text-green-400 text-xs mt-1">
                MW{country.latest_time ? ` at ${formatTime(country.latest_time)}` : ""}
              </p>
            </button>
          );
        })}
      </div>

      {/* Energy Chart */}
      <div className="bg-gray-900 rounded-xl p-4 md:p-6 mb-6 border border-gray-700">
        <h2 className="text-base md:text-lg font-semibold mb-1 text-green-400">
          ⚡ {selectedCountry.toUpperCase()} — Last 24hr Energy Load (MW)
        </h2>
        <p className="text-gray-500 text-xs mb-4">
          Times in your local time
          {selectedEnergy?.resolution_minutes
            ? `, ${selectedEnergy.resolution_minutes}-minute resolution`
            : ""}
        </p>
        {chartData.length === 0 ? (
          <p className="text-gray-400 text-sm py-10 text-center">
            No load data available for {selectedCountry}.
          </p>
        ) : (
          <ResponsiveContainer width="100%" height={250}>
            <LineChart data={chartData}>
              <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
              <XAxis
                dataKey="label"
                stroke="#9CA3AF"
                tick={{ fontSize: 11 }}
                minTickGap={40}
                interval="preserveStartEnd"
              />
              <YAxis stroke="#9CA3AF" tick={{ fontSize: 11 }} domain={["auto", "auto"]} />
              <Tooltip
                contentStyle={TOOLTIP_STYLE}
                labelFormatter={(_, payload) => payload?.[0]?.payload?.full ?? ""}
              />
              <Legend />
              <Line
                type="monotone"
                dataKey="load_mw"
                stroke="#4ADE80"
                strokeWidth={2}
                dot={false}
                connectNulls
                name="Load (MW)"
              />
            </LineChart>
          </ResponsiveContainer>
        )}
      </div>

      {/* Stats Row */}
      {selectedEnergy && (
        <div className="grid grid-cols-3 gap-3 mb-6">
          <div className="bg-gray-900 rounded-xl p-3 md:p-4 border border-gray-700">
            <p className="text-gray-400 text-xs">Max Load</p>
            <p className="text-base md:text-xl font-bold text-red-400">
              {Math.round(selectedEnergy.max_load_mw).toLocaleString()} MW
            </p>
          </div>
          <div className="bg-gray-900 rounded-xl p-3 md:p-4 border border-gray-700">
            <p className="text-gray-400 text-xs">Avg Load</p>
            <p className="text-base md:text-xl font-bold text-yellow-400">
              {Math.round(selectedEnergy.avg_load_mw).toLocaleString()} MW
            </p>
          </div>
          <div className="bg-gray-900 rounded-xl p-3 md:p-4 border border-gray-700">
            <p className="text-gray-400 text-xs">Min Load</p>
            <p className="text-base md:text-xl font-bold text-green-400">
              {Math.round(selectedEnergy.min_load_mw).toLocaleString()} MW
            </p>
          </div>
        </div>
      )}

      {/* ML Forecast Chart */}
      {!selectedForecast && forecastError && (
        <div className="bg-gray-900 rounded-xl p-4 md:p-6 mb-6 border border-yellow-700">
          <p className="text-yellow-300 text-xs">Forecast unavailable: {forecastError}</p>
        </div>
      )}
      {selectedForecast && (
        <div className="bg-gray-900 rounded-xl p-4 md:p-6 mb-6 border border-blue-800">
          <h2 className="text-base md:text-lg font-semibold mb-1 text-blue-400">
            ML Forecast — {selectedForecast.country} Energy (MW)
          </h2>
          <p className="text-gray-500 text-xs mb-4">
            Model: {selectedForecast.model} — {selectedForecast.total_predictions} hourly predictions (UTC)
            {selectedForecast.backtest_mape_pct !== undefined
              ? ` · backtest error ${selectedForecast.backtest_mape_pct}% MAPE`
              : ""}
          </p>
          {selectedForecast.source === "static" ? (
            <p className="mb-4 text-xs text-yellow-300 bg-yellow-950 border border-yellow-700 rounded-lg p-2">
              The live forecast is temporarily unavailable. Showing an old static forecast instead.
            </p>
          ) : (
            (forecastStale || selectedForecast.carried_over) && (
              <p className="mb-4 text-xs text-yellow-300 bg-yellow-950 border border-yellow-700 rounded-lg p-2">
                This forecast covers {forecastFirst?.slice(0, 16)} to {forecastLast?.slice(0, 16)} UTC
                and the latest scheduled update did not refresh it.
              </p>
            )
          )}
          <ResponsiveContainer width="100%" height={250}>
            <LineChart data={forecastChartData}>
              <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
              <XAxis dataKey="time" stroke="#9CA3AF" tick={{ fontSize: 11 }} />
              <YAxis stroke="#9CA3AF" tick={{ fontSize: 11 }} domain={["auto", "auto"]} />
              <Tooltip contentStyle={TOOLTIP_STYLE} />
              <Legend />
              <Line
                type="monotone"
                dataKey="predicted"
                stroke="#60A5FA"
                strokeWidth={2}
                dot={false}
                name="Predicted (MW)"
              />
              <Line
                type="monotone"
                dataKey="upper"
                stroke="#6B7280"
                strokeWidth={1}
                dot={false}
                strokeDasharray="5 5"
                name="Upper bound"
              />
              <Line
                type="monotone"
                dataKey="lower"
                stroke="#6B7280"
                strokeWidth={1}
                dot={false}
                strokeDasharray="5 5"
                name="Lower bound"
              />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* Track record: GridSense vs the TSO's own day-ahead forecast */}
      {trackRecord && trackRecord.country.toLowerCase() === selectedCountry && (
        <TrackRecordCard data={trackRecord} />
      )}

      {/* Weather Cards */}
      <div className="bg-gray-900 rounded-xl p-4 md:p-6 border border-gray-700">
        <h2 className="text-base md:text-lg font-semibold mb-4 text-blue-400">
          🌤️ Current Weather — European Cities
        </h2>
        {weatherData.length === 0 ? (
          <p className="text-gray-400 text-sm">Weather data is not available right now.</p>
        ) : (
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            {weatherData.map((city) => {
              const i =
                updatedAt === null
                  ? -1
                  : currentHourIndex(city.hourly_time, city.timezone, new Date(updatedAt));
              const temperature = i >= 0 ? city.temperature[i] : undefined;
              const wind = i >= 0 ? city.windspeed[i] : undefined;
              const cloud = i >= 0 ? city.cloudcover[i] : undefined;
              return (
                <div
                  key={city.city}
                  className="bg-gray-800 rounded-lg p-3 md:p-4 border border-gray-700"
                >
                  <p className="text-gray-400 text-xs">{city.city}</p>
                  <p className="text-xl md:text-2xl font-bold text-white mt-1">
                    {temperature !== undefined ? `${temperature}°C` : "N/A"}
                  </p>
                  <p className="text-blue-400 text-xs mt-1">
                    💨 {wind !== undefined ? `${wind} km/h` : "N/A"}
                  </p>
                  <p className="text-gray-400 text-xs mt-1">
                    ☁️ {cloud !== undefined ? `${cloud}%` : "N/A"}
                  </p>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </main>
  );
}
