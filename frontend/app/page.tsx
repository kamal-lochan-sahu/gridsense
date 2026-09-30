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
import type { AnomalyData, EnergyData, ForecastData, WeatherData } from "@/lib/types";

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
  const [anomalyData, setAnomalyData] = useState<AnomalyData | null>(null);
  const [selectedCountry, setSelectedCountry] = useState("germany");
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [updatedAt, setUpdatedAt] = useState<number | null>(null);
  const [errors, setErrors] = useState<string[]>([]);
  const [refreshCount, setRefreshCount] = useState(0);

  const load = useCallback(async () => {
    const [energy, weather, forecast] = await Promise.allSettled([
      getJson<EnergyData[]>("/energy"),
      getJson<WeatherData[]>("/weather"),
      getJson<ForecastData>("/forecast"),
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

    if (forecast.status === "fulfilled" && forecast.value.status === "success") {
      setForecastData(forecast.value);
    } else {
      problems.push(
        `Forecast: ${forecast.status === "rejected" ? describeError(forecast.reason) : "model returned an error"}`
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

  const forecastChartData = forecastData?.predictions.map((p) => ({
    time: p.ds.slice(11, 16),
    predicted: Math.round(p.yhat),
    upper: Math.round(p.yhat_upper),
    lower: Math.round(p.yhat_lower),
  }));

  const forecastFirst = forecastData?.predictions[0]?.ds;
  const forecastLast = forecastData?.predictions[forecastData.predictions.length - 1]?.ds;
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
              const at = loadedPoints[a.position]?.time;
              return (
                <span
                  key={a.position}
                  className={`text-xs px-2 py-1 rounded-full ${
                    a.deviation === "HIGH"
                      ? "bg-red-700 text-red-200"
                      : "bg-yellow-800 text-yellow-200"
                  }`}
                >
                  {a.deviation} {Math.round(a.load_mw).toLocaleString()} MW
                  {at ? ` at ${formatTime(at)}` : ""} (z={a.z_score})
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
      {forecastData && (
        <div className="bg-gray-900 rounded-xl p-4 md:p-6 mb-6 border border-blue-800">
          <h2 className="text-base md:text-lg font-semibold mb-1 text-blue-400">
            ML Forecast — {forecastData.country} Energy (MW)
          </h2>
          <p className="text-gray-500 text-xs mb-4">
            Model: {forecastData.model} — {forecastData.total_predictions} predictions
          </p>
          {forecastStale && (
            <p className="mb-4 text-xs text-yellow-300 bg-yellow-950 border border-yellow-700 rounded-lg p-2">
              This forecast covers {forecastFirst?.slice(0, 16)} to {forecastLast?.slice(0, 16)} and is
              not live yet. Automatic retraining is planned.
            </p>
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
