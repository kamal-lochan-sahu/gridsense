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

// Types
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

const API_URL = "https://gridsense-backend-k8pa.onrender.com";

export default function Home() {
  const [energyData, setEnergyData] = useState<EnergyData[]>([]);
  const [weatherData, setWeatherData] = useState<WeatherData[]>([]);
  const [selectedCountry, setSelectedCountry] = useState("germany");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetchAllData();
  }, []);

  const fetchAllData = async () => {
    setLoading(true);
    try {
      const [energyRes, weatherRes] = await Promise.all([
        fetch(`${API_URL}/energy`),
        fetch(`${API_URL}/weather`),
      ]);
      const energy = await energyRes.json();
      const weather = await weatherRes.json();
      setEnergyData(energy);
      setWeatherData(weather);
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