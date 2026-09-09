"use client";

import { useId, memo } from "react";
import { exactMetricValue } from "./metric-analysis-dialog";
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

const CHART_COLORS = ["var(--chart-1)", "var(--chart-2)", "var(--chart-3)", "var(--chart-4)", "var(--chart-5)"];
const TOOLTIP_STYLE = {
  backgroundColor: "var(--tooltip-bg)", color: "var(--foreground)",
  border: "1px solid var(--tooltip-line)", borderRadius: "8px", fontSize: "12px",
};
const AXIS_TICK = { fill: "var(--muted-foreground)", fontSize: 12 };

type RechartsChartProps = {
  chartType: "line" | "bar" | "pie";
  title: string;
  xKey: string;
  yKey: string;
  data: Record<string, unknown>[];
  height?: number;
  fill?: boolean;
  unit?: string;
};

export const RechartsChart = memo(function RechartsChart({
  chartType,
  title,
  xKey,
  yKey,
  data,
  height = 300,
  fill = false,
  unit,
}: RechartsChartProps) {
  const gradientId = useId().replace(/:/g, "");

  if (!data || data.length === 0) {
    return (
      <div className="bg-card border border-border rounded-xl p-5 flex items-center justify-center h-[200px]">
        <p className="text-sm text-muted-foreground">데이터가 없습니다</p>
      </div>
    );
  }

  const formatValue = (value: unknown): string => {
    if (typeof value !== "number") return String(value ?? "");
    if (Math.abs(value) >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}M`;
    if (Math.abs(value) >= 1_000) return `${(value / 1_000).toFixed(1)}K`;
    return value.toLocaleString();
  };

  // Metric amounts remain exact decimal strings in storage/API. Recharts
  // (especially Pie) requires numbers for geometry; convert only at rendering.
  const plotData = data.map((row) => {
    const value = row[yKey];
    const numeric = value == null || value === "" ? null : Number(value);
    return { ...row, [xKey]: row[xKey] ?? "(분류 미제공)", [yKey]: numeric !== null && Number.isFinite(numeric) ? numeric : null, __exactValue: value };
  });

  return (
    <div className={`bg-card border border-border rounded-xl animate-in fade-in slide-in-from-bottom-4 duration-500 ${fill ? "h-full min-h-0 flex flex-col p-2" : "p-5"}`}>
      {title && (
        <h3 className="text-base font-semibold text-foreground mb-4">
          {title}
        </h3>
      )}

      <div
        className={fill ? "flex-1 min-h-0" : ""}
        style={fill ? undefined : { height }}
      >
        <ResponsiveContainer width="100%" height="100%">
          {chartType === "pie" ? (
            <PieChart>
              <Pie
                data={plotData}
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
                labelLine={{ stroke: "var(--muted-foreground)" }}
              >
                {data.map((_, idx) => (
                  <Cell
                    key={idx}
                    fill={CHART_COLORS[idx % CHART_COLORS.length]}
                  />
                ))}
              </Pie>
              <Tooltip
                cursor={{ fill: "var(--accent-surface)", stroke: "var(--line-strong)" }}
                contentStyle={TOOLTIP_STYLE}
                labelStyle={{ color: "var(--foreground)", fontWeight: 700 }}
                itemStyle={{ color: "var(--muted-foreground)" }}
                formatter={(value: unknown, _name, item) => [exactMetricValue(item.payload?.__exactValue ?? value, unit), ""]}
              />
              <Legend
                iconType="circle"
                iconSize={8}
                formatter={(value: string) => (
                  <span style={{ color: "var(--muted-foreground)", fontSize: 12 }}>
                    {value}
                  </span>
                )}
              />
            </PieChart>
          ) : chartType === "bar" ? (
            <BarChart
              data={plotData}
              margin={{ top: 10, right: 10, left: 0, bottom: 0 }}
            >
              <CartesianGrid
                strokeDasharray="3 3"
                stroke="var(--chart-grid)"
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
                cursor={{ fill: "var(--accent-surface)", stroke: "var(--line-strong)" }}
                contentStyle={TOOLTIP_STYLE}
                labelStyle={{ color: "var(--foreground)", fontWeight: 700 }}
                itemStyle={{ color: "var(--muted-foreground)" }}
                formatter={(value: unknown, _name, item) => [exactMetricValue(item.payload?.__exactValue ?? value, unit), ""]}
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
              data={plotData}
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
                    stopOpacity={0.16}
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
                stroke="var(--chart-grid)"
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
                cursor={{ fill: "var(--accent-surface)", stroke: "var(--line-strong)" }}
                contentStyle={TOOLTIP_STYLE}
                labelStyle={{ color: "var(--foreground)", fontWeight: 700 }}
                itemStyle={{ color: "var(--muted-foreground)" }}
                formatter={(value: unknown, _name, item) => [exactMetricValue(item.payload?.__exactValue ?? value, unit), ""]}
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
