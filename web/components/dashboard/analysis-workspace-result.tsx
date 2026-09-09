"use client";

import { useState } from "react";
import { MetricSaveSettings } from "./metric-save-settings";
import { ArrowUpRight, Check, Loader2, Plus } from "lucide-react";
import type { ChartData, Message } from "@/app/lib/api";
import type { ChartSaveOptions, ChartSaveState } from "@/app/hooks/use-chart-saving";
import MessageBubble from "@/app/components/message-bubble";
import { Button } from "@/components/ui/button";
import { EChartsChart } from "./echarts-chart";
import { MetricAnalysisDialog } from "./metric-analysis-dialog";

export function AnalysisWorkspaceResult({ message, storeName, onOpenLibrary, state, onSave, onOpenWidget }: {
  message: Message; storeName: string; onOpenLibrary: (search?: string) => void;
  state: (index: number) => ChartSaveState; onSave: (index: number, chart: ChartData, options?: ChartSaveOptions) => Promise<void>;
  onOpenWidget: (id: string) => void;
}) {
  const [editing, setEditing] = useState<string>();
  if (!message.charts?.length) return <MessageBubble message={message} onOpenLibrary={onOpenLibrary} />;
  return <div className="space-y-6">
    {message.charts.map((chart, index) => {
      const saved = state(index), data = chart as ChartData & Record<string, unknown>;
      const stores = data.scope === "selected_stores" && Array.isArray(data.stores) ? data.stores.map((store) => String(store.project_name)).join(" · ") : storeName;
      const busy = saved.status === "saving" || saved.status === "checking";
      return <section key={`${message.message_id}:${index}`} className="min-w-0 overflow-hidden rounded-xl border border-border bg-card" aria-label={`${chart.title} 분석 결과`}>
        <div className="flex flex-wrap items-start justify-between gap-4 px-5 pt-5 sm:px-6">
          <div className="min-w-0 basis-full sm:basis-auto sm:flex-1"><h3 className="font-semibold">{chart.title}</h3><p className="mt-2 break-words text-xs leading-5 text-muted-foreground">{stores} · {String(data.period_label || "기간 정보 미제공")} · {String(data.scope_label || "분석 출처 확인")}{data.source_table_name ? ` · ${String(data.source_table_name)}` : ""}</p></div>
          <div className="flex flex-wrap items-center gap-2">
            {saved.status === "saved" && <span role="status" className="flex items-center gap-1 text-xs text-success"><Check size={13} />저장 완료</span>}
            <Button size="sm" variant={saved.status === "saved" ? "outline" : "default"} disabled={busy}
              onClick={() => saved.id ? onOpenWidget(saved.id) : setEditing(`${message.message_id}:${index}`)}>
              {busy ? <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" /> : saved.id ? <ArrowUpRight className="mr-1 h-3.5 w-3.5" /> : <Plus className="mr-1 h-3.5 w-3.5" />}
              {saved.status === "saving" ? "저장 중…" : saved.status === "checking" ? "저장 상태 확인 중…" : saved.id ? "대시보드에서 보기" : saved.status === "error" ? "다시 시도" : "대시보드에 저장"}
            </Button>
          </div>
        </div>
        {saved.error && <p role="alert" className="px-6 pt-3 text-sm text-destructive">{saved.error}</p>}
        {!!data.calculation_label && <p className="px-6 pt-4 text-sm">{String(data.calculation_label)}</p>}
        <div className="h-[340px] px-3 pb-2 pt-5 sm:h-[380px] sm:px-5"><EChartsChart chartType={chart.chart_type as "line" | "bar" | "pie"} title="" xKey={chart.x_key} yKey={chart.y_key} data={chart.data} unit={chart.unit} fill /></div>
        <div className="flex flex-wrap items-center justify-between gap-2 border-t border-border px-5 py-3 text-xs text-muted-foreground">
          <p>{chart.data.length.toLocaleString("ko-KR")}개 집계 항목 · {chart.metric_definition ? "저장 후 재계산·갱신 주기 설정 가능" : "현재 결과를 저장"}</p>
          <MetricAnalysisDialog data={data} title={chart.title} />
        </div>
        {editing === `${message.message_id}:${index}` && saved.status !== "saved" && <MetricSaveSettings key={editing} chart={chart} state={saved} onSave={options => onSave(index, chart, options)} onClose={() => setEditing(undefined)} />}
      </section>;
    })}
    <details className="rounded-xl border border-border bg-card px-5 py-4" open>
      <summary className="cursor-pointer text-sm font-medium">AI 설명과 분석 출처</summary>
      <div className="mt-4"><MessageBubble message={{ ...message, charts: undefined }} onOpenLibrary={onOpenLibrary} /></div>
    </details>
  </div>;
}
