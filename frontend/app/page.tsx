"use client";

import { useEffect, useState } from "react";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Legend,
} from "recharts";

interface EnergyData {
  country: string;
  status: string;
  total_points: number;
  latest_load_mw: number;
  max_load_mw: number;
  min_load_mw: number;
  avg_load_mw: number;
  all_loads: number[];
}

interface WeatherData {
  city: string;
  timezone: string;
  hourly_time: string[];
  temperature: number[];
  windspeed: number[];
  cloudcover: number[];
}

interface ForecastPoint {
  ds: string;
  yhat: number;
  yhat_lower: number;
  yhat_upper: number;
}

interface ForecastData {
  status: string;
  country: string;
  model: string;
  total_predictions: number;
  predictions: ForecastPoint[];
}

const API_URL = "https://gridsense-backend-k8pa.onrender.com";

function SplashScreen() {
  const [progress, setProgress] = useState(0);
  const [text, setText] = useState("Connecting to European grid...");

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
    return () => clearInterval(interval);
  }, []);

  return (
    <div className="fixed inset-0 bg-gray-950 flex flex-col items-center justify-center z-50">
      <div className="mb-8 flex flex-col items-center">
        <div className="text-6xl mb-4 animate-bounce">⚡</div>
        <h1 className="text-4xl font-bold text-green-400 tracking-widest">
          GRIDSENSE
        </h1>
        <p className="text-gray-500 text-sm mt-2 tracking-wider">
          REAL-TIME ENERGY INTELLIGENCE
        </p>
      </div>
      <div className="w-64 mt-8">
        <div className="h-1 bg-gray-800 rounded-full overflow-hidden">
          <div
            className="h-full bg-green-400 rounded-full transition-all duration-500"
            style={{ width: `${progress}%` }}
          />
        </div>
        <p className="text-gray-500 text-xs mt-3 text-center">{text}</p>
      </div>
    </div>
  );
}

export default function Home() {
  const [energyData, setEnergyData] = useState<EnergyData[]>([]);
  const [weatherData, setWeatherData] = useState<WeatherData[]>([]);
  const [forecastData, setForecastData] = useState<ForecastData | null>(null);
  const [selectedCountry, setSelectedCountry] = useState("germany");
  const [loading, setLoading] = useState(true);
  const [showSplash, setShowSplash] = useState(true);

  useEffect(() => {
    const splashTimer = setTimeout(() => setShowSplash(false), 2500);
    fetchAllData();
    return () => clearTimeout(splashTimer);
  }, []);

  const fetchAllData = async () => {
    setLoading(true);
    try {
      const [energyRes, weatherRes, forecastRes] = await Promise.all([
        fetch(`${API_URL}/energy`),
        fetch(`${API_URL}/weather`),
        fetch(`${API_URL}/forecast`),
      ]);
      const energy = await energyRes.json();
      const weather = await weatherRes.json();
      const forecast = await forecastRes.json();
      setEnergyData(energy);
      setWeatherData(weather);
      setForecastData(forecast);
    } catch (error) {
      console.error("Error fetching data:", error);
    }
    setLoading(false);
  };

  const selectedEnergy = energyData.find(
    (d) => d.country.toLowerCase() === selectedCountry
  );

  const chartData = selectedEnergy?.all_loads.slice(-24).map((load, i) => ({
    hour: `${i + 1}h`,
    load_mw: Math.round(load),
  }));

  const forecastChartData = forecastData?.predictions.map((p) => ({
    time: p.ds.split(" ")[1]?.slice(0, 5) || p.ds,
    predicted: Math.round(p.yhat),
    upper: Math.round(p.yhat_upper),
    lower: Math.round(p.yhat_lower),
  }));

  if (showSplash) return <SplashScreen />;

  return (
    <main className="min-h-screen bg-gray-950 text-white p-6">
      {/* Header */}
      <div className="mb-8">
        <h1 className="text-3xl font-bold text-green-400">⚡ GridSense</h1>
        <p className="text-gray-400 mt-1">
          Real-Time Industrial Energy Intelligence Platform
        </p>
      </div>

      {loading ? (
        <div className="flex items-center justify-center h-64">
          <p className="text-gray-400 text-xl">Loading live data...</p>
        </div>
      ) : (
        <>
          {/* Energy Cards */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-8">
            {energyData.map((country) => (
              <div
                key={country.country}
                onClick={() =>
                  setSelectedCountry(country.country.toLowerCase())
                }
                className={`p-4 rounded-xl cursor-pointer border transition-all ${
                  selectedCountry === country.country.toLowerCase()
                    ? "border-green-400 bg-gray-800"
                    : "border-gray-700 bg-gray-900 hover:border-gray-500"
                }`}
              >
                <p className="text-gray-400 text-sm">{country.country}</p>
                <p className="text-2xl font-bold text-white mt-1">
                  {Math.round(country.latest_load_mw).toLocaleString()}
                </p>
                <p className="text-green-400 text-xs mt-1">MW — Live</p>
              </div>
            ))}
          </div>

          {/* Energy Chart */}
          <div className="bg-gray-900 rounded-xl p-6 mb-8 border border-gray-700">
            <h2 className="text-lg font-semibold mb-4 text-green-400">
              ⚡ {selectedCountry.toUpperCase()} — Last 24hr Energy Load (MW)
            </h2>
            <ResponsiveContainer width="100%" height={300}>
              <LineChart data={chartData}>
                <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
                <XAxis dataKey="hour" stroke="#9CA3AF" />
                <YAxis stroke="#9CA3AF" />
                <Tooltip
                  contentStyle={{
                    backgroundColor: "#1F2937",
                    border: "1px solid #374151",
                    borderRadius: "8px",
                  }}
                />
                <Legend />
                <Line
                  type="monotone"
                  dataKey="load_mw"
                  stroke="#4ADE80"
                  strokeWidth={2}
                  dot={false}
                  name="Load (MW)"
                />
              </LineChart>
            </ResponsiveContainer>
          </div>

          {/* Stats Row */}
          {selectedEnergy && (
            <div className="grid grid-cols-3 gap-4 mb-8">
              <div className="bg-gray-900 rounded-xl p-4 border border-gray-700">
                <p className="text-gray-400 text-sm">Max Load</p>
                <p className="text-xl font-bold text-red-400">
                  {Math.round(selectedEnergy.max_load_mw).toLocaleString()} MW
                </p>
              </div>
              <div className="bg-gray-900 rounded-xl p-4 border border-gray-700">
                <p className="text-gray-400 text-sm">Avg Load</p>
                <p className="text-xl font-bold text-yellow-400">
                  {Math.round(selectedEnergy.avg_load_mw).toLocaleString()} MW
                </p>
              </div>
              <div className="bg-gray-900 rounded-xl p-4 border border-gray-700">
                <p className="text-gray-400 text-sm">Min Load</p>
                <p className="text-xl font-bold text-green-400">
                  {Math.round(selectedEnergy.min_load_mw).toLocaleString()} MW
                </p>
              </div>
            </div>
          )}

          {/* Forecast Chart */}
          {forecastChartData && (
            <div className="bg-gray-900 rounded-xl p-6 mb-8 border border-purple-800">
              <h2 className="text-lg font-semibold mb-1 text-purple-400">
                🤖 ML Forecast — Germany Next 24hr (Prophet Model)
              </h2>
              <p className="text-gray-500 text-xs mb-4">
                Predicted energy consumption based on historical patterns
              </p>
              <ResponsiveContainer width="100%" height={300}>
                <LineChart data={forecastChartData}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
                  <XAxis dataKey="time" stroke="#9CA3AF" />
                  <YAxis stroke="#9CA3AF" />
                  <Tooltip
                    contentStyle={{
                      backgroundColor: "#1F2937",
                      border: "1px solid #374151",
                      borderRadius: "8px",
                    }}
                  />
                  <Legend />
                  <Line
                    type="monotone"
                    dataKey="predicted"
                    stroke="#A855F7"
                    strokeWidth={2}
                    dot={false}
                    name="Predicted (MW)"
                  />
                  <Line
                    type="monotone"
                    dataKey="upper"
                    stroke="#6B21A8"
                    strokeWidth={1}
                    dot={false}
                    strokeDasharray="4 4"
                    name="Upper Bound"
                  />
                  <Line
                    type="monotone"
                    dataKey="lower"
                    stroke="#6B21A8"
                    strokeWidth={1}
                    dot={false}
                    strokeDasharray="4 4"
                    name="Lower Bound"
                  />
                </LineChart>
              </ResponsiveContainer>
            </div>
          )}

          {/* Weather Cards */}
          <div className="bg-gray-900 rounded-xl p-6 border border-gray-700">
            <h2 className="text-lg font-semibold mb-4 text-blue-400">
              🌤️ Live Weather — European Cities
            </h2>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
              {weatherData.map((city) => (
                <div
                  key={city.city}
                  className="bg-gray-800 rounded-lg p-4 border border-gray-700"
                >
                  <p className="text-gray-400 text-sm">{city.city}</p>
                  <p className="text-2xl font-bold text-white mt-1">
                    {city.temperature[0]}°C
                  </p>
                  <p className="text-blue-400 text-xs mt-1">
                    💨 {city.windspeed[0]} km/h
                  </p>
                  <p className="text-gray-400 text-xs mt-1">
                    ☁️ {city.cloudcover[0]}%
                  </p>
                </div>
              ))}
            </div>
          </div>
        </>
      )}
    </main>
  );
}