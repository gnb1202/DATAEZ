"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { ResponsiveGridLayout, verticalCompactor } from "react-grid-layout";
import type { Layout, LayoutItem, ResponsiveLayouts } from "react-grid-layout";
import {
  LayoutDashboard,
  X,
  Loader2,
  Bot,
  GripVertical,
  TableProperties,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { EChartsChart } from "@/components/dashboard/echarts-chart";
import { MetricEditDialog } from "@/components/dashboard/metric-edit-dialog";
import { exactMetricValue, MetricAnalysisDialog } from "@/components/dashboard/metric-analysis-dialog";
import { MetricCreateForm } from "@/components/dashboard/metric-create-form";
import { GettingStarted } from "@/components/dashboard/getting-started";
import { StoreMetricForm } from "@/components/dashboard/store-metric-form";
import type { SampleReady } from "../sample-workspace-actions";
import { parseError } from "@/app/lib/api";
import { useDashboard } from "@/app/contexts/dashboard-context";
import "react-grid-layout/css/styles.css";

type DashboardWidget = {
  id: string;
  widget_type: "chart" | "kpi";
  title: string;
  widget_data: Record<string, unknown>;
  layout: { x: number; y: number; w: number; h: number };
  refresh_interval_seconds?: number;
  next_refresh_at?: string | null;
  refresh_failures?: number;
};

type LedgerSourceStatus = { id: string; table_id: string; name: string; row_count: number; last_committed_at?: string | null; baseline_at?: string | null };

function MetricSourceStatus({ widget, sources, projectId }: { widget: DashboardWidget; sources: LedgerSourceStatus[] | null; projectId: string }) {
  if (widget.widget_data.scope === "selected_stores") {
    const stores = widget.widget_data.stores as {project_id:string;project_name:string}[];
    return <p>대상 가게: {stores.map((s, i) => <span key={s.project_id}>{i > 0 ? " · " : ""}<a className="underline" href={`/dashboard?project=${s.project_id}&section=tables`}>{s.project_name}</a></span>)} · 출처별 계산 기준은 집계표에서 확인하세요.</p>;
  }
  if (widget.widget_data.scope_label === "파일 원본만") return <p>{String(widget.widget_data.refresh_note)}</p>;
  if (sources === null) return <p>장부 반영 상태를 불러오지 못했습니다.</p>;
  const definition = widget.widget_data.metric_definition as { table_id?: string; sources?: { table_id: string }[]; left?: {definition: {table_id: string}}; right?: {definition: {table_id: string}} };
  const ids = definition.left && definition.right ? [definition.left.definition.table_id, definition.right.definition.table_id] : definition.sources?.map((source) => source.table_id) || [definition.table_id];
  const linked = sources.filter((source) => ids.includes(source.table_id));
  if (!linked.length) return null;
  const latest = linked.map((source) => source.last_committed_at || source.baseline_at).filter(Boolean).sort().at(-1);
  const pending = latest && new Date(latest).getTime() > new Date(String(widget.widget_data.calculated_at)).getTime();
  return <details className="my-1">
    <summary className="cursor-pointer">장부 반영: {latest ? new Date(latest).toLocaleString("ko-KR") : "반영 전"}{pending ? " · 재계산 필요" : ""}</summary>
    {linked.map((source) => <p key={source.id}><a className="underline" href={`/dashboard?project=${projectId}&section=tables&source=${source.id}`}>{source.name}</a> · 장부 전체 {source.row_count}행</p>)}
    <p>지표는 설정한 기간·필터를 적용한 계산 결과입니다. 장부 전체 건수와 다를 수 있습니다.</p>
  </details>;
}

interface DashboardSectionProps {
  focusWidgetId?: string;
  onNavigateToChat: () => void;
  onNavigateToTables: () => void;
  onCreateStore: () => void;
  onStartMetricChat: (prompt: string) => void;
  onSampleReady: SampleReady;
  onOpenLibrary: () => void;
}

export function DashboardSection(props: DashboardSectionProps) {
  const { selectedProjectId } = useDashboard();
  return <StoreDashboardSection key={selectedProjectId} {...props} />;
}

function StoreDashboardSection({
  onNavigateToChat,
  onNavigateToTables, onCreateStore, onStartMetricChat, focusWidgetId, onSampleReady, onOpenLibrary,
}: DashboardSectionProps) {
  const { selectedProjectId, apiFetch } = useDashboard();
  const [widgets, setWidgets] = useState<DashboardWidget[]>([]);
  const [sources, setSources] = useState<LedgerSourceStatus[] | null>([]);
  const [loading, setLoading] = useState(false);
  const [tableCount, setTableCount] = useState(0);
  const [error, setError] = useState("");
  const [refreshing, setRefreshing] = useState<string | null>(null);
  const [containerWidth, setContainerWidth] = useState(0);
  // The grid mounts after loading/empty states. Observe the actual mounted node,
  // rather than a mount-only ref effect that can retain a guessed 1280px width.
  const containerRef = useCallback((node: HTMLDivElement | null) => {
    if (!node) return;
    setContainerWidth(node.clientWidth);
    const observer = new ResizeObserver(([entry]) => setContainerWidth(entry.contentRect.width));
    observer.observe(node);
    return () => observer.disconnect();
  }, []);
  const focused = useRef<string | null>(null);
  useEffect(() => {
    if (!focusWidgetId || focused.current === focusWidgetId || loading || !containerWidth || !widgets.some(w => w.id === focusWidgetId)) return;
    const frame = requestAnimationFrame(() => {
      const element = document.getElementById(`dashboard-widget-${focusWidgetId}`);
      if (element) { element.scrollIntoView({ block: "center", inline: "nearest", behavior: "instant" }); element.focus({ preventScroll: true }); focused.current = focusWidgetId; }
    });
    return () => cancelAnimationFrame(frame);
  }, [focusWidgetId, loading, containerWidth, widgets]);


  const fetchWidgets = useCallback(async (quiet = false) => {
    if (!selectedProjectId) return;
    if (!quiet) setLoading(true);
    try {
      const [res, sourceRes] = await Promise.all([
        apiFetch(`/api/dashboard/widgets?project_id=${selectedProjectId}`),
        apiFetch(`/api/projects/${selectedProjectId}/ledger-sources`).catch(() => null),
      ]);
      setSources(sourceRes?.ok ? (await sourceRes.json()).sources || [] : null);
      if (res.ok) {
        const data = await res.json();
        setError("");
        setWidgets((prev) => (data.widgets || []).map((w: DashboardWidget) => ({
          ...w, layout: quiet ? prev.find((old) => old.id === w.id)?.layout || w.layout : w.layout,
        })));
      } else {
        setError(await parseError(res));
      }
    } catch {
      setError("대시보드를 불러오지 못했습니다.");
    } finally {
      if (!quiet) setLoading(false);
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
    const timer = setInterval(() => { if (!document.hidden) fetchWidgets(true); }, 15000);
    return () => clearInterval(timer);
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
      }).then(async (res) => {
        if (!res.ok) setError(await parseError(res));
      }).catch(() => setError("배치 저장에 실패했습니다. 다시 이동하거나 크기를 조절해주세요."));
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
        } else setError(await parseError(res));
      } catch {
        setError("위젯을 삭제하지 못했습니다. 다시 시도해주세요.")
      }
    },
    [apiFetch]
  );

  async function refreshMetric(id: string) {
    setRefreshing(id);
    setError("");
    try {
      const res = await apiFetch(`/api/projects/${selectedProjectId}/metrics/${id}/refresh`, { method: "POST" });
      if (!res.ok) throw new Error(await parseError(res));
      const result = await res.json();
      setWidgets((prev) => prev.map((w) => w.id === id ? { ...w, widget_data: result.widget_data } : w));
      await fetchWidgets(true);
    } catch (err) {
      const message = err instanceof Error ? err.message : "재계산에 실패했습니다.";
      setError(message);
      setWidgets((prev) => prev.map((w) => w.id === id ? { ...w, widget_data: { ...w.widget_data, refresh_error: message } } : w));
    } finally { setRefreshing(null); }
  }

  async function changeSchedule(id: string, interval: number) {
    setRefreshing(id);
    setError("");
    try {
      const res = await apiFetch(`/api/projects/${selectedProjectId}/metrics/${id}/schedule`, {
        method: "PATCH", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ refresh_interval_seconds: interval }),
      });
      if (!res.ok) throw new Error(await parseError(res));
      const result = await res.json();
      setWidgets((prev) => prev.map((w) => w.id === id ? { ...w, ...result, refresh_failures: 0 } : w));
    } catch (err) { setError(err instanceof Error ? err.message : "갱신 주기를 저장하지 못했습니다."); }
    finally { setRefreshing(null); }
  }

  const guide = <GettingStarted completed={widgets.some(w => !!w.widget_data.metric_definition)} onCreateStore={onCreateStore} onOpenTables={onNavigateToTables} onCreated={fetchWidgets} onStartChat={onStartMetricChat} onSampleReady={onSampleReady} onOpenLibrary={onOpenLibrary} />;
  if (!selectedProjectId) return guide;

  if (loading) {
    return (
      <div className="flex items-center justify-center py-24">
        <Loader2 className="h-8 w-8 animate-spin text-accent" />
      </div>
    );
  }

  const metricCards = <div className="flex flex-wrap items-center gap-x-6 gap-y-2 border-y border-border py-3 text-xs text-muted-foreground" aria-label="대시보드 요약">
    <span>연결 장부 <strong className="ml-2 numeric text-foreground">{tableCount}</strong></span>
    <span>저장 위젯 <strong className="ml-2 numeric text-foreground">{widgets.length}</strong></span>
    <span>자동 갱신 <strong className="ml-2 numeric text-foreground">{widgets.filter(w => !!w.refresh_interval_seconds && (w.refresh_failures || 0) < 3).length}</strong></span>
  </div>;

  if (widgets.length === 0) {
    return (
      <div className="space-y-6">
        {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
        {guide}
        <MetricCreateForm onCreated={fetchWidgets} />
        <StoreMetricForm onCreated={fetchWidgets} />
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
    minH: w.widget_data.metric_definition ? (w.widget_type === "chart" ? 7 : 5) : (w.widget_type === "chart" ? 4 : 3),
  }));

  return (
    <div className="space-y-6">
      {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
      {metricCards}
      <details className="rounded-lg border border-border bg-card px-4 py-3">
        <summary className="cursor-pointer text-sm font-medium">지표 만들기·시작 안내</summary>
        <div className="mt-4 space-y-4">{guide}<MetricCreateForm onCreated={fetchWidgets} /><StoreMetricForm onCreated={fetchWidgets} /></div>
      </details>

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
            cols={{ lg: 12, md: 12, sm: 6, xs: 4, xxs: 2 }}
            rowHeight={60}
            // Opening the chat changes available width. Persist only an
            // intentional drag/resize, never the responsive layout adjustment.
            onDragStop={(layout) => handleLayoutChange(layout, {})}
            onResizeStop={(layout) => handleLayoutChange(layout, {})}
            dragConfig={{ handle: ".widget-drag-handle" }}
            compactor={verticalCompactor}
            margin={[16, 16] as const}
          >
            {widgets.map((widget) => (
              <div key={widget.id} className="group" id={`dashboard-widget-${widget.id}`} tabIndex={-1} aria-label={`${widget.title} 위젯`}>
                <div className="h-full bg-card border border-border rounded-xl overflow-hidden flex flex-col group-focus:border-accent group-focus:ring-1 group-focus:ring-accent hover:border-accent/50 transition-colors relative">
                  <div className="relative flex items-center justify-between px-3 py-2 border-b border-border/50">
                    <div className="flex items-center gap-2 min-w-0">
                      <GripVertical className="h-4 w-4 text-muted-foreground cursor-grab widget-drag-handle shrink-0" />
                      <span className="text-sm font-medium text-foreground truncate">
                        {widget.title}
                      </span>
                    </div>
                    {!!widget.widget_data.metric_definition && (
                      <Button size="sm" variant="ghost" disabled={refreshing !== null} onClick={() => refreshMetric(widget.id)} aria-label={`${widget.title} 재계산`}>
                        {refreshing === widget.id ? "계산 중…" : "재계산"}
                      </Button>
                    )}
                    {!!widget.widget_data.metric_definition && <MetricEditDialog id={widget.id} title={widget.title} onChanged={() => { void fetchWidgets(true); }} />}
                    <button
                      onClick={() => handleDeleteWidget(widget.id)}
                      aria-label="위젯 삭제"
                      className="opacity-60 hover:opacity-100 focus-visible:opacity-100 p-1 rounded hover:bg-destructive/10"
                    >
                      <X className="h-3.5 w-3.5 text-muted-foreground hover:text-destructive" />
                    </button>
                  </div>
                  <div className="shrink-0 px-4 pt-3 text-xs text-muted-foreground">
                    <p className="truncate" title={String(widget.widget_data.source_table_name || "")}>{String(widget.widget_data.period_label || "기간 정보 미제공")}{widget.widget_data.scope_label ? ` · ${String(widget.widget_data.scope_label)}` : ""}{widget.widget_data.source_table_name ? ` · ${String(widget.widget_data.source_table_name)}` : ""}</p>
                    {!!widget.widget_data.undefined_reason && <p role="status" className="mt-1">{String(widget.widget_data.undefined_reason)}</p>}
                    {!!widget.widget_data.refresh_error && <p role="alert" className="mt-1 line-clamp-2 text-destructive" title={String(widget.widget_data.refresh_error)}>갱신 실패 · 이전 결과 표시: {String(widget.widget_data.refresh_error)}</p>}
                    {(widget.refresh_failures || 0) >= 3 && !!widget.refresh_interval_seconds && <p className="text-destructive">자동 갱신 일시 중지 · 재계산 또는 주기 재설정 필요</p>}
                  </div>
                  <div className="relative flex-1 min-h-0 p-3 overflow-hidden">
                    {widget.widget_type === "kpi" ? (
                      <KpiWidget data={widget.widget_data} />
                    ) : (
                      <ChartWidget data={widget.widget_data} />
                    )}
                  </div>
                  <div className="shrink-0 border-t border-border px-3 py-2 text-xs text-muted-foreground">
                    <div className="flex flex-wrap items-center justify-between gap-1">
                      {!!widget.widget_data.metric_definition ? <label className="flex items-center gap-2">갱신
                        <select aria-label={`${widget.title} 갱신 주기`} className="rounded border bg-background p-1" disabled={refreshing !== null} value={widget.refresh_interval_seconds || 0} onChange={(e) => changeSchedule(widget.id, Number(e.target.value))}>
                          <option value={0}>수동</option><option value={3600}>매시간</option><option value={86400}>24시간마다</option>
                        </select>
                      </label> : <span>저장 당시 결과</span>}
                      <MetricAnalysisDialog data={widget.widget_data} title={widget.title} />
                    </div>
                    {!!widget.widget_data.metric_definition && <details className="mt-1 max-h-28 overflow-auto">
                      <summary className="cursor-pointer">계산·출처 상태</summary>
                      <p className="mt-2">최근 계산: {widget.widget_data.calculated_at ? new Date(String(widget.widget_data.calculated_at)).toLocaleString("ko-KR", { timeZone: "Asia/Seoul" }) : "미실행"} (한국 시간)</p>
                      {widget.next_refresh_at && <p>다음 계산: {new Date(widget.next_refresh_at).toLocaleString("ko-KR", { timeZone: "Asia/Seoul" })} (한국 시간)</p>}
                      <MetricSourceStatus widget={widget} sources={sources} projectId={selectedProjectId} />
                      {Array.isArray(widget.widget_data.warnings) && widget.widget_data.warnings.map((warning, i) => <p key={i}>{String(warning)}</p>)}
                      <p>{String(widget.widget_data.refresh_note || "새 거래는 파일 반영 또는 직접 입력 후 계산에 포함됩니다.")}</p>
                    </details>}
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
  const formatted = data.metric_definition
    ? exactMetricValue(data.value, String(data.unit || data.currency || ""))
    : String(data.formatted ?? data.value ?? "\u2014");
  const label = String(data.label ?? "");

  return (
    <div className="flex flex-col justify-center h-full">
      <p className="text-3xl font-semibold tracking-tight text-foreground font-sans numeric">{formatted}</p>
      <p className="text-xs text-muted-foreground mt-1">
        {label}

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
    <EChartsChart
      chartType={chartType}
      title=""
      xKey={xKey}
      yKey={yKey}
      data={chartData}
      fill
      unit={String(data.unit || data.currency || "")}
    />
  );
}
