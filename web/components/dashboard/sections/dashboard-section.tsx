"use client";

import { useCallback, useEffect, useState } from "react";
import { ResponsiveGridLayout, useContainerWidth, verticalCompactor } from "react-grid-layout";
import type { Layout, LayoutItem, ResponsiveLayouts } from "react-grid-layout";
import {
  LayoutDashboard,
  X,
  Loader2,
  Bot,
  GripVertical,
  TableProperties,
  BarChart3,
  TrendingUp,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { MetricCard } from "@/components/dashboard/metric-card";
import { RechartsChart } from "@/components/dashboard/recharts-chart";
import { useDashboard } from "@/app/contexts/dashboard-context";
import "react-grid-layout/css/styles.css";

type DashboardWidget = {
  id: string;
  widget_type: "chart" | "kpi";
  title: string;
  widget_data: Record<string, unknown>;
  layout: { x: number; y: number; w: number; h: number };
};

interface DashboardSectionProps {
  onNavigateToChat: () => void;
  onNavigateToTables: () => void;
}

export function DashboardSection({
  onNavigateToChat,
  onNavigateToTables,
}: DashboardSectionProps) {
  const { selectedProjectId, apiFetch } = useDashboard();
  const [widgets, setWidgets] = useState<DashboardWidget[]>([]);
  const [loading, setLoading] = useState(false);
  const [tableCount, setTableCount] = useState(0);
  const { containerRef, width: containerWidth } = useContainerWidth();

  const fetchWidgets = useCallback(async () => {
    if (!selectedProjectId) return;
    setLoading(true);
    try {
      const res = await apiFetch(
        `/api/dashboard/widgets?project_id=${selectedProjectId}`
      );
      if (res.ok) {
        const data = await res.json();
        setWidgets(data.widgets || []);
      }
    } catch {
      // ignore
    } finally {
      setLoading(false);
    }
  }, [selectedProjectId, apiFetch]);

  const fetchTableCount = useCallback(async () => {
    if (!selectedProjectId) return;
    try {
      const res = await apiFetch(
        `/api/projects/${selectedProjectId}/tables`
      );
      if (res.ok) {
        const data = await res.json();
        setTableCount((data.tables || []).length);
      }
    } catch {
      // ignore
    }
  }, [selectedProjectId, apiFetch]);

  useEffect(() => {
    fetchWidgets();
    fetchTableCount();
  }, [fetchWidgets, fetchTableCount]);

  const handleLayoutChange = useCallback(
    (newLayout: Layout, _allLayouts: ResponsiveLayouts) => {
      if (widgets.length === 0) return;
      const layouts = newLayout
        .map((l) => ({
          id: l.i,
          layout: { x: l.x, y: l.y, w: l.w, h: l.h },
        }))
        .filter((item) => widgets.some((w) => w.id === item.id));

      if (layouts.length === 0) return;

      setWidgets((prev) =>
        prev.map((w) => {
          const updated = layouts.find((l) => l.id === w.id);
          return updated ? { ...w, layout: updated.layout } : w;
        })
      );

      apiFetch("/api/dashboard/widgets/layout", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ layouts }),
      }).catch(() => {});
    },
    [widgets, apiFetch]
  );

  const handleDeleteWidget = useCallback(
    async (widgetId: string) => {
      try {
        const res = await apiFetch(`/api/dashboard/widgets/${widgetId}`, {
          method: "DELETE",
        });
        if (res.ok) {
          setWidgets((prev) => prev.filter((w) => w.id !== widgetId));
        }
      } catch {
        // ignore
      }
    },
    [apiFetch]
  );

  if (!selectedProjectId) {
    return (
      <div className="flex flex-col items-center justify-center py-24 text-center animate-in fade-in slide-in-from-bottom-4 duration-500">
        <div className="h-20 w-20 rounded-2xl bg-secondary flex items-center justify-center mb-6">
          <LayoutDashboard className="h-10 w-10 text-muted-foreground" />
        </div>
        <h3 className="text-lg font-semibold text-foreground mb-2">
          프로젝트를 먼저 선택해주세요
        </h3>
        <p className="text-sm text-muted-foreground mb-6 max-w-md">
          사이드바에서 프로젝트를 선택하면 대시보드를 확인할 수 있습니다.
        </p>
      </div>
    );
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center py-24">
        <Loader2 className="h-8 w-8 animate-spin text-accent" />
      </div>
    );
  }

  const metricCards = (
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
      <MetricCard
        title="장부 수"
        value={String(tableCount)}
        icon={TableProperties}
        delay={0}
      />
      <MetricCard
        title="위젯 수"
        value={String(widgets.length)}
        icon={BarChart3}
        delay={1}
      />
      <MetricCard
        title="차트"
        value={String(widgets.filter((w) => w.widget_type === "chart").length)}
        icon={TrendingUp}
        delay={2}
      />
      <MetricCard
        title="KPI"
        value={String(widgets.filter((w) => w.widget_type === "kpi").length)}
        icon={LayoutDashboard}
        delay={3}
      />
    </div>
  );

  if (widgets.length === 0) {
    return (
      <div className="space-y-6">
        {metricCards}
        <div
          className="flex flex-col items-center justify-center py-16 text-center border border-dashed border-border rounded-xl animate-in fade-in slide-in-from-bottom-4 duration-500"
          style={{ animationDelay: "400ms", animationFillMode: "both" }}
        >
          <div className="h-20 w-20 rounded-2xl bg-secondary flex items-center justify-center mb-6">
            <LayoutDashboard className="h-10 w-10 text-muted-foreground" />
          </div>
          <h3 className="text-lg font-semibold text-foreground mb-2">
            대시보드가 비어있습니다
          </h3>
          <p className="text-sm text-muted-foreground mb-6 max-w-md">
            AI 분석에서 생성한 차트를 대시보드에 고정하세요.
          </p>
          <div className="flex gap-3">
            <Button
              onClick={onNavigateToChat}
              variant="outline"
              className="gap-2 hover:border-accent/50 transition-colors"
            >
              <Bot className="h-4 w-4" />
              AI 분석으로 이동
            </Button>
            <Button
              onClick={onNavigateToTables}
              variant="outline"
              className="gap-2 hover:border-accent/50 transition-colors"
            >
              <TableProperties className="h-4 w-4" />
              장부 관리
            </Button>
          </div>
        </div>
      </div>
    );
  }

  const gridLayout: LayoutItem[] = widgets.map((w) => ({
    i: w.id,
    x: w.layout.x,
    y: w.layout.y,
    w: w.layout.w,
    h: w.layout.h,
    minW: 2,
    minH: 2,
  }));

  return (
    <div className="space-y-6">
      {metricCards}

      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="h-10 w-10 rounded-lg bg-accent/10 flex items-center justify-center">
            <LayoutDashboard className="h-5 w-5 text-accent" />
          </div>
          <div>
            <h2 className="text-lg font-semibold text-foreground">위젯</h2>
            <p className="text-sm text-muted-foreground">
              드래그하여 위치를 변경하고 모서리를 잡아 크기를 조절하세요
            </p>
          </div>
        </div>
        <Button
          onClick={onNavigateToChat}
          variant="outline"
          size="sm"
          className="gap-2 hover:border-accent/50 transition-colors"
        >
          <Bot className="h-4 w-4" />
          AI 분석에서 차트 추가
        </Button>
      </div>

      <div ref={containerRef}>
        {containerWidth > 0 && (
          <ResponsiveGridLayout
            className="layout"
            width={containerWidth}
            layouts={{ lg: gridLayout }}
            breakpoints={{ lg: 1200, md: 996, sm: 768, xs: 480, xxs: 0 }}
            cols={{ lg: 12, md: 10, sm: 6, xs: 4, xxs: 2 }}
            rowHeight={60}
            onLayoutChange={handleLayoutChange}
            dragConfig={{ handle: ".widget-drag-handle" }}
            compactor={verticalCompactor}
            margin={[16, 16] as const}
          >
            {widgets.map((widget) => (
              <div key={widget.id} className="group">
                <div className="h-full bg-card border border-border rounded-xl overflow-hidden flex flex-col hover:border-accent/50 transition-all duration-300 relative">
                  <div className="absolute inset-0 bg-gradient-to-br from-accent/5 to-transparent opacity-0 group-hover:opacity-100 transition-opacity duration-500 pointer-events-none" />
                  <div className="relative flex items-center justify-between px-3 py-2 border-b border-border/50">
                    <div className="flex items-center gap-2 min-w-0">
                      <GripVertical className="h-4 w-4 text-muted-foreground cursor-grab widget-drag-handle shrink-0" />
                      <span className="text-xs font-medium text-foreground truncate">
                        {widget.title}
                      </span>
                    </div>
                    <button
                      onClick={() => handleDeleteWidget(widget.id)}
                      aria-label="위젯 삭제"
                      className="opacity-0 group-hover:opacity-100 transition-opacity p-1 rounded hover:bg-destructive/10"
                    >
                      <X className="h-3.5 w-3.5 text-muted-foreground hover:text-destructive" />
                    </button>
                  </div>
                  <div className="relative flex-1 p-3 overflow-hidden">
                    {widget.widget_type === "kpi" ? (
                      <KpiWidget data={widget.widget_data} />
                    ) : (
                      <ChartWidget data={widget.widget_data} />
                    )}
                  </div>
                </div>
              </div>
            ))}
          </ResponsiveGridLayout>
        )}
      </div>
    </div>
  );
}

function KpiWidget({ data }: { data: Record<string, unknown> }) {
  const formatted = String(data.formatted ?? data.value ?? "\u2014");
  const label = String(data.label ?? "");
  const changeType = data.change_type as string | undefined;

  return (
    <div className="flex flex-col justify-center h-full">
      <p className="text-2xl font-bold text-foreground font-mono">{formatted}</p>
      <p className="text-xs text-muted-foreground mt-1">
        {label}
        {changeType && changeType !== "unchanged" && (
          <span
            className={
              changeType === "increase"
                ? "text-success ml-2"
                : "text-destructive ml-2"
            }
          >
            {changeType === "increase" ? "+" : "-"}
          </span>
        )}
      </p>
    </div>
  );
}

function ChartWidget({ data }: { data: Record<string, unknown> }) {
  const chartType = String(data.chart_type ?? "bar") as "line" | "bar" | "pie";
  const xKey = String(data.x_key ?? "");
  const yKey = String(data.y_key ?? "");
  const chartData = (data.data as Record<string, unknown>[]) ?? [];

  if (!chartData.length) {
    return (
      <div className="flex items-center justify-center h-full text-xs text-muted-foreground">
        데이터 없음
      </div>
    );
  }

  return (
    <RechartsChart
      chartType={chartType}
      title=""
      xKey={xKey}
      yKey={yKey}
      data={chartData}
      height={200}
    />
  );
}
