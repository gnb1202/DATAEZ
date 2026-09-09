"use client";

import { memo, useEffect, useId, useRef, useState } from "react";
import { useTheme } from "next-themes";
import type { EChartsType } from "./echarts-runtime";
import { exactMetricValue } from "./metric-analysis-dialog";

type Props = {
  chartType: "line" | "bar" | "pie";
  title: string; xKey: string; yKey: string; data: Record<string, unknown>[];
  height?: number; fill?: boolean; unit?: string;
};

function tick(value: number, unit?: string) {
  if (unit === "percent") return `${value.toLocaleString("ko-KR", { maximumFractionDigits: 2 })}%`;
  const n = Math.abs(value);
  return n >= 100_000_000 ? `${+(value / 100_000_000).toFixed(1)}억` : n >= 10_000 ? `${+(value / 10_000).toFixed(1)}만` : value.toLocaleString("ko-KR", { maximumFractionDigits: 2 });
}

export const EChartsChart = memo(function EChartsChart({ chartType, title, xKey, yKey, data, height = 300, fill = false, unit }: Props) {
  const { resolvedTheme } = useTheme();
  const host = useRef<HTMLDivElement>(null);
  const instance = useRef<EChartsType | null>(null);
  const [focusedPoint, setFocusedPoint] = useState<number | null>(null);
  const [failed, setFailed] = useState(false);
  const helpId = useId();
  const number = (value: unknown) => value == null || value === "" || !Number.isFinite(Number(value)) ? null : Number(value);
  const hasValue = data.some((row) => number(row[yKey]) !== null);
  const negativePie = chartType === "pie" && data.some((row) => (number(row[yKey]) ?? 0) < 0);
  const type = negativePie ? "bar" : chartType;
  const zeroPie = type === "pie" && hasValue && data.every((row) => !number(row[yKey]));
  const noChart = !data.length || !hasValue || zeroPie;

  useEffect(() => {
    const element = host.current;
    if (!element || noChart) return;
    let disposed = false;
    let observer: ResizeObserver | undefined;
    let frame = 0;
    let chart: EChartsType | null = null;
    const start = async () => {
      try {
        const engine = await import("./echarts-runtime");
        if (disposed) return;
        const styles = getComputedStyle(element);
        const color = (token: string) => styles.getPropertyValue(token).trim();
        const colors = ["--chart-primary", "--chart-secondary", "--chart-cancel", "--success-text", "--accent-strong"].map(color);
        const points = data.map((row) => ({ name: String(row[xKey] ?? "(분류 미제공)"), value: number(row[yKey]) }));
        const tooltip = (params: unknown) => {
          const point = (Array.isArray(params) ? params[0] : params) as { dataIndex?: number } | undefined;
          const row = data[point?.dataIndex ?? 0];
          const node = document.createElement("div");
          const name = document.createElement("div"), value = document.createElement("strong");
          name.textContent = String(row?.[xKey] ?? "(분류 미제공)");
          value.textContent = exactMetricValue(row?.[yKey], unit);
          name.style.cssText = "font-size:11px;margin-bottom:6px;opacity:.8";
          value.style.cssText = "font-size:14px;font-variant-numeric:tabular-nums";
          node.append(name, value);
          return node;
        };
        const paint = () => {
          if (disposed || !element.clientWidth || !element.clientHeight) return;
          if (chart) { chart.resize(); return; }
          chart = engine.init(element, undefined, { renderer: "svg" });
          instance.current = chart;
          chart.setOption({
            animation: !window.matchMedia("(prefers-reduced-motion: reduce)").matches,
            animationDuration: 320, animationDurationUpdate: 180,
            color: colors, backgroundColor: "transparent", textStyle: { fontFamily: styles.fontFamily },
            aria: { enabled: true, label: { description: `${title || "분석 그래프"}. ${data.length}개 집계 항목. 좌우 방향키로 정확한 값을 확인할 수 있습니다.` } },
            tooltip: { trigger: type === "pie" ? "item" : "axis", confine: true, renderMode: "html", formatter: tooltip,
              className: "dataez-chart-tooltip", backgroundColor: color("--tooltip-bg"), borderColor: color("--tooltip-line"), borderWidth: 1,
              padding: [10, 14], textStyle: { color: color("--text"), fontFamily: styles.fontFamily },
              axisPointer: { type: type === "bar" ? "shadow" : "line", shadowStyle: { color: color("--accent-surface") }, lineStyle: { color: colors[0], type: "dashed" } } },
            ...(type === "pie" ? {
              legend: { type: "scroll", bottom: 0, icon: "circle", itemWidth: 8, itemHeight: 8, textStyle: { color: color("--text-secondary"), fontSize: 11 } },
              series: [{ type: "pie", radius: ["48%", "73%"], center: ["50%", "44%"], stillShowZeroSum: false,
                avoidLabelOverlap: true, label: { show: false }, itemStyle: { borderRadius: 4, borderColor: color("--panel"), borderWidth: 3 },
                emphasis: { scaleSize: 4 }, data: points }],
            } : {
              grid: { left: 12, right: 16, top: 16, bottom: data.length > 24 ? 58 : 12, containLabel: true },
              xAxis: { type: "category", data: points.map((point) => point.name), boundaryGap: type === "bar",
                axisTick: { show: false }, axisLine: { show: false }, axisLabel: { color: color("--text-muted"), margin: 16, hideOverlap: true, width: 90, overflow: "truncate", fontSize: 11 } },
              yAxis: { type: "value", splitNumber: 4, axisLabel: { color: color("--text-muted"), formatter: (v: number) => tick(v, unit), fontSize: 11 },
                splitLine: { lineStyle: { color: color("--chart-grid"), type: "dashed", opacity: 0.65 } } },
              ...(data.length > 24 ? { dataZoom: [{ type: "slider", bottom: 2, height: 18, start: 0, end: 100, borderColor: "transparent", textStyle: { color: color("--text-muted") }, fillerColor: color("--accent-surface") }] } : {}),
              series: [{ type, name: yKey, data: points, barMaxWidth: 44, barMinHeight: 0,
                itemStyle: { color: colors[0], borderRadius: type === "bar" ? 3 : 0 },
                lineStyle: { width: 2.5 }, symbol: "circle", symbolSize: 6, showSymbol: data.length <= 12, connectNulls: false,
                ...(type === "line" ? { areaStyle: { color: { type: "linear", x: 0, y: 0, x2: 0, y2: 1, colorStops: [{ offset: 0, color: color("--chart-area-start") }, { offset: 1, color: color("--chart-area-end") }] } } } : {}),
                emphasis: { focus: "series" } }],
            }),
          }, { notMerge: true });
          element.dataset.chartReady = "true";
        };
        observer = new ResizeObserver(() => { cancelAnimationFrame(frame); frame = requestAnimationFrame(paint); });
        observer.observe(element);
        paint();
        void document.fonts.ready.then(() => { if (!disposed) chart?.resize(); });
      } catch { if (!disposed) setFailed(true); }
    };
    void start();
    return () => { disposed = true; observer?.disconnect(); cancelAnimationFrame(frame); chart?.dispose(); instance.current = null; delete element.dataset.chartReady; };
  }, [data, type, xKey, yKey, title, unit, resolvedTheme, noChart]);

  const selected = focusedPoint === null ? null : data[Math.min(focusedPoint, data.length - 1)];
  return <div className={fill ? "flex h-full min-h-0 flex-col" : "min-w-0 rounded-xl border border-border bg-card p-4 sm:p-5"} data-chart-kind={type}>
    {title && <h3 className="mb-4 text-sm font-medium">{title}</h3>}
    {noChart || failed ? <div className="flex min-h-32 flex-1 items-center justify-center text-sm text-muted-foreground" role="status">{failed ? "그래프를 표시하지 못했습니다. 집계표에서 값을 확인해주세요." : zeroPie ? "합계가 0이어서 비율을 표시하지 않습니다." : !data.length ? "조건에 맞는 데이터가 없습니다." : "계산 가능한 값이 없습니다."}</div> : <div
      ref={host} className={`min-w-0 rounded-lg outline-none focus-visible:ring-2 focus-visible:ring-ring ${fill ? "min-h-0 flex-1" : ""}`}
      style={fill ? undefined : { height }} data-chart-engine="echarts" role="group" tabIndex={0} aria-label={`${title || "분석"} 그래프`} aria-describedby={helpId}
      onKeyDown={(event) => {
        if (!["ArrowLeft", "ArrowRight", "Home", "End", "Escape"].includes(event.key)) return;
        event.preventDefault();
        if (event.key === "Escape") { setFocusedPoint(null); instance.current?.dispatchAction({ type: "hideTip" }); return; }
        const point = event.key === "Home" ? 0 : event.key === "End" ? data.length - 1 : Math.max(0, Math.min(data.length - 1, (focusedPoint ?? (event.key === "ArrowRight" ? -1 : 1)) + (event.key === "ArrowRight" ? 1 : -1)));
        setFocusedPoint(point); instance.current?.dispatchAction({ type: "showTip", seriesIndex: 0, dataIndex: point });
      }} onBlur={() => { setFocusedPoint(null); instance.current?.dispatchAction({ type: "hideTip" }); }} />}
    <p id={helpId} className="sr-only">좌우 방향키로 항목 이동, Home과 End로 처음과 끝, Escape로 툴팁 닫기.</p>
    {selected && <p role="status" className="shrink-0 pt-2 text-xs numeric">{String(selected[xKey] ?? "(분류 미제공)")} · {exactMetricValue(selected[yKey], unit)}</p>}
    {negativePie && <p className="pt-2 text-xs text-muted-foreground">음수 값이 포함되어 막대그래프로 표시합니다.</p>}
  </div>;
});
