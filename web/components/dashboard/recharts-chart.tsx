"use client";

import { useState, useEffect, useId, memo } from "react";
import {
  AreaChart,
  Area,
  BarChart,
  Bar,
  PieChart,
  Pie,
  Cell,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Legend,
} from "recharts";

const CHART_COLORS = [
  "oklch(0.7 0.18 220)",   // blue (primary)
  "oklch(0.7 0.18 145)",   // green
  "oklch(0.7 0.18 30)",    // orange
  "oklch(0.7 0.18 310)",   // purple
  "oklch(0.7 0.18 60)",    // yellow
  "oklch(0.7 0.18 0)",     // red
];

const TOOLTIP_STYLE = {
  backgroundColor: "oklch(0.12 0.005 260)",
  border: "1px solid oklch(0.22 0.005 260)",
  borderRadius: "8px",
  fontSize: "12px",
};

const AXIS_TICK = { fill: "oklch(0.65 0 0)", fontSize: 12 };

type RechartsChartProps = {
  chartType: "line" | "bar" | "pie";
  title: string;
  xKey: string;
  yKey: string;
  data: Record<string, unknown>[];
  height?: number;
};

export const RechartsChart = memo(function RechartsChart({
  chartType,
  title,
  xKey,
  yKey,
  data,
  height = 300,
}: RechartsChartProps) {
  const [isLoaded, setIsLoaded] = useState(false);
  const gradientId = useId().replace(/:/g, "");

  useEffect(() => {
    const timer = setTimeout(() => setIsLoaded(true), 200);
    return () => clearTimeout(timer);
  }, []);

  if (!data || data.length === 0) {
    return (
      <div className="bg-card border border-border rounded-xl p-5 flex items-center justify-center h-[200px]">
        <p className="text-sm text-muted-foreground">데이터가 없습니다</p>
      </div>
    );
  }

  const formatValue = (value: unknown): string => {
    if (typeof value !== "number") return String(value ?? "");
    if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}M`;
    if (value >= 1_000) return `${(value / 1_000).toFixed(1)}K`;
    return value.toLocaleString();
  };

  return (
    <div className="bg-card border border-border rounded-xl p-5 animate-in fade-in slide-in-from-bottom-4 duration-500">
      {title && (
        <h3 className="text-base font-semibold text-foreground mb-4">
          {title}
        </h3>
      )}

      <div
        className={`transition-opacity duration-700 ${isLoaded ? "opacity-100" : "opacity-0"}`}
        style={{ height }}
      >
        <ResponsiveContainer width="100%" height="100%">
          {chartType === "pie" ? (
            <PieChart>
              <Pie
                data={data}
                dataKey={yKey}
                nameKey={xKey}
                cx="50%"
                cy="50%"
                innerRadius="40%"
                outerRadius="75%"
                paddingAngle={2}
                isAnimationActive={false}
                label={({ name, percent }: { name?: string; percent?: number }) =>
                  `${name ?? ""} ${((percent ?? 0) * 100).toFixed(0)}%`
                }
                labelLine={{ stroke: "oklch(0.45 0 0)" }}
              >
                {data.map((_, idx) => (
                  <Cell
                    key={idx}
                    fill={CHART_COLORS[idx % CHART_COLORS.length]}
                  />
                ))}
              </Pie>
              <Tooltip
                contentStyle={TOOLTIP_STYLE}
                labelStyle={{ color: "oklch(0.95 0 0)", fontWeight: 600 }}
                itemStyle={{ color: "oklch(0.65 0 0)" }}
                formatter={(value: unknown) => [formatValue(value), ""]}
              />
              <Legend
                iconType="circle"
                iconSize={8}
                formatter={(value: string) => (
                  <span style={{ color: "oklch(0.65 0 0)", fontSize: 12 }}>
                    {value}
                  </span>
                )}
              />
            </PieChart>
          ) : chartType === "bar" ? (
            <BarChart
              data={data}
              margin={{ top: 10, right: 10, left: 0, bottom: 0 }}
            >
              <CartesianGrid
                strokeDasharray="3 3"
                stroke="oklch(0.22 0.005 260)"
                vertical={false}
              />
              <XAxis
                dataKey={xKey}
                axisLine={false}
                tickLine={false}
                tick={AXIS_TICK}
                dy={10}
              />
              <YAxis
                axisLine={false}
                tickLine={false}
                tick={AXIS_TICK}
                tickFormatter={(v: number) => formatValue(v)}
                dx={-10}
              />
              <Tooltip
                contentStyle={TOOLTIP_STYLE}
                labelStyle={{ color: "oklch(0.95 0 0)", fontWeight: 600 }}
                itemStyle={{ color: "oklch(0.65 0 0)" }}
                formatter={(value: unknown) => [formatValue(value), ""]}
              />
              <Bar
                dataKey={yKey}
                fill={CHART_COLORS[0]}
                radius={[4, 4, 0, 0]}
                maxBarSize={50}
                isAnimationActive={false}
              />
            </BarChart>
          ) : (
            /* line → AreaChart (sales-ops style) */
            <AreaChart
              data={data}
              margin={{ top: 10, right: 10, left: 0, bottom: 0 }}
            >
              <defs>
                <linearGradient
                  id={`grad_${gradientId}`}
                  x1="0"
                  y1="0"
                  x2="0"
                  y2="1"
                >
                  <stop
                    offset="0%"
                    stopColor={CHART_COLORS[0]}
                    stopOpacity={0.4}
                  />
                  <stop
                    offset="100%"
                    stopColor={CHART_COLORS[0]}
                    stopOpacity={0}
                  />
                </linearGradient>
              </defs>
              <CartesianGrid
                strokeDasharray="3 3"
                stroke="oklch(0.22 0.005 260)"
                vertical={false}
              />
              <XAxis
                dataKey={xKey}
                axisLine={false}
                tickLine={false}
                tick={AXIS_TICK}
                dy={10}
              />
              <YAxis
                axisLine={false}
                tickLine={false}
                tick={AXIS_TICK}
                tickFormatter={(v: number) => formatValue(v)}
                dx={-10}
              />
              <Tooltip
                contentStyle={TOOLTIP_STYLE}
                labelStyle={{ color: "oklch(0.95 0 0)", fontWeight: 600 }}
                itemStyle={{ color: "oklch(0.65 0 0)" }}
                formatter={(value: unknown) => [formatValue(value), ""]}
              />
              <Area
                type="monotone"
                dataKey={yKey}
                stroke={CHART_COLORS[0]}
                strokeWidth={2}
                fill={`url(#grad_${gradientId})`}
                dot={false}
                isAnimationActive={false}
              />
            </AreaChart>
          )}
        </ResponsiveContainer>
      </div>
    </div>
  );
});
