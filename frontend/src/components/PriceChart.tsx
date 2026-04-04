import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  BarChart,
  Bar,
} from "recharts";
import type { PricePoint } from "../types/api";

interface Props {
  data: PricePoint[];
  symbol: string;
}

export function PriceChart({ data, symbol }: Props) {
  if (!data.length) return null;

  const chartData = data.map((p) => ({
    date: new Date(p.date).toLocaleDateString("en-US", {
      month: "short",
      day: "numeric",
    }),
    price: p.close,
    volume: p.volume,
    high: p.high,
    low: p.low,
  }));

  const minPrice = Math.min(...chartData.map((d) => d.low)) * 0.98;
  const maxPrice = Math.max(...chartData.map((d) => d.high)) * 1.02;

  const priceChange = chartData[chartData.length - 1].price - chartData[0].price;
  const isPositive = priceChange >= 0;
  const color = isPositive ? "#22c55e" : "#ef4444";

  return (
    <div>
      <div style={{ marginBottom: 12 }}>
        <span style={{ fontSize: "1.1rem", fontWeight: 700 }}>{symbol}</span>
        <span
          style={{ marginLeft: 12, fontWeight: 600 }}
          className={isPositive ? "text-green" : "text-red"}
        >
          ${chartData[chartData.length - 1].price.toFixed(2)}
        </span>
      </div>

      <ResponsiveContainer width="100%" height={250}>
        <AreaChart data={chartData}>
          <defs>
            <linearGradient id="priceGradient" x1="0" y1="0" x2="0" y2="1">
              <stop offset="5%" stopColor={color} stopOpacity={0.3} />
              <stop offset="95%" stopColor={color} stopOpacity={0} />
            </linearGradient>
          </defs>
          <CartesianGrid strokeDasharray="3 3" stroke="#2a3548" />
          <XAxis
            dataKey="date"
            tick={{ fill: "#64748b", fontSize: 11 }}
            tickLine={false}
          />
          <YAxis
            domain={[minPrice, maxPrice]}
            tick={{ fill: "#64748b", fontSize: 11 }}
            tickLine={false}
            tickFormatter={(v: number) => `$${v.toFixed(0)}`}
          />
          <Tooltip
            contentStyle={{
              background: "#1a2332",
              border: "1px solid #2a3548",
              borderRadius: 8,
              fontSize: "0.8rem",
            }}
            labelStyle={{ color: "#94a3b8" }}
            formatter={(value) => [`$${Number(value).toFixed(2)}`, "Price"]}
          />
          <Area
            type="monotone"
            dataKey="price"
            stroke={color}
            strokeWidth={2}
            fill="url(#priceGradient)"
          />
        </AreaChart>
      </ResponsiveContainer>

      <ResponsiveContainer width="100%" height={80}>
        <BarChart data={chartData}>
          <XAxis dataKey="date" hide />
          <YAxis hide />
          <Tooltip
            contentStyle={{
              background: "#1a2332",
              border: "1px solid #2a3548",
              borderRadius: 8,
              fontSize: "0.8rem",
            }}
            formatter={(value) => [
              Number(value).toLocaleString(),
              "Volume",
            ]}
          />
          <Bar dataKey="volume" fill="#3b82f6" opacity={0.5} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
