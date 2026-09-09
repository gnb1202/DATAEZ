"use client";

import { useEffect, useRef, useState } from "react";
import type { ChartData } from "@/app/lib/api";
import { parseError } from "@/app/lib/api";
import type { ChartSaveOptions, ChartSaveState } from "@/app/hooks/use-chart-saving";
import { useDashboard } from "@/app/contexts/dashboard-context";
import { Button } from "@/components/ui/button";
import { EChartsChart } from "./echarts-chart";
import { MetricAnalysisDialog, exactMetricValue } from "./metric-analysis-dialog";

type Definition = Record<string, unknown>;
const field = "mt-1 block w-full rounded-lg border border-input bg-[var(--surface-input)] px-3 py-2 text-sm";
const periods = { all: "전체 기간", this_month: "이번 달", last_month: "지난달", last_30_days: "최근 30일" };
function periodSources(def: Definition): { path: string; label: string; value: string; enabled: boolean }[] {
  if (def.left && def.right) return ["left", "right"].map(side => {
    const operand = def[side] as { label: string; definition: Definition };
    return { path: side, label: `${operand.label} 기간`, value: String(operand.definition.time_range || "all"), enabled: !!operand.definition.date_column };
  });
  const sources = def.sources as { date_column?: string }[] | undefined;
  const stores = def.stores as { sources: { date_column?: string }[] }[] | undefined;
  return [{ path: "", label: "집계 기간", value: String(def.time_range || "all"), enabled: !!def.date_column || !!sources?.every(s => s.date_column) || !!stores?.every(s => s.sources.every(source => source.date_column)) }];
}

export function MetricSaveSettings({ chart, state, onSave, onClose }: {
  chart: ChartData; state: ChartSaveState; onSave: (options: ChartSaveOptions) => Promise<void>; onClose: () => void;
}) {
  const { apiFetch, selectedProjectId } = useDashboard();
  const [title, setTitle] = useState(state.settings?.title || chart.title || "매출 분석");
  const [definition, setDefinition] = useState<Definition | undefined>(() => state.settings?.definition || (chart.metric_definition ? { ...chart.metric_definition } : undefined));
  const [interval, setInterval] = useState(state.settings?.refresh_interval_seconds || 0);
  const [preview, setPreview] = useState<{ key: string; data: Record<string, unknown> }>();
  const [loading, setLoading] = useState(false), [error, setError] = useState("");
  const request = useRef(0), alive = useRef(true);
  useEffect(() => { alive.current = true; const invalidate = () => { alive.current = false; request.current++; }; return invalidate; }, []);
  const key = JSON.stringify(definition);
  const result = preview && preview.key === key ? preview.data : undefined;
  const frozen = !!state.settings;
  const isSingle = definition && (!definition.version || definition.version === 1);
  const updatePeriod = (path: string, time_range: string) => setDefinition(current => {
    if (!current) return current;
    if (!path) return { ...current, time_range };
    const operand = current[path] as { definition: Definition };
    return { ...current, [path]: { ...operand, definition: { ...operand.definition, time_range } } };
  });
  async function calculate() {
    const id = ++request.current; setLoading(true); setError("");
    try {
      const response = await apiFetch(`/api/projects/${selectedProjectId}/metrics/preview`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ definition }) });
      if (!response.ok) throw new Error(await parseError(response));
      const data = await response.json();
      if (alive.current && request.current === id) setPreview({ key, data });
    } catch (err) { if (alive.current && request.current === id) setError(err instanceof Error ? err.message : "미리보기를 계산하지 못했습니다."); }
    finally { if (alive.current && request.current === id) setLoading(false); }
  }
  const data = chart as ChartData & Record<string, unknown>;
  return <div aria-label="지표 저장 설정" className="space-y-4 border-t border-border bg-secondary/40 p-5 sm:p-6">
    <div className="flex items-center justify-between gap-3"><h4 className="text-sm font-semibold">대시보드에 저장할 내용</h4><Button size="sm" variant="ghost" disabled={state.status === "saving"} onClick={onClose}>설정 닫기</Button></div>
    <p className="text-xs leading-5 text-muted-foreground">{String(data.scope_label || "분석에 사용한 출처 유지")} · {String(data.refresh_note || (definition ? "새로고침할 때 같은 출처와 계산 기준을 사용합니다." : "현재 결과를 고정해 저장합니다."))}</p>
    <fieldset disabled={frozen || loading} className="grid gap-4 sm:grid-cols-2">
      <label className="text-xs sm:col-span-2">지표 이름<input aria-label="저장 지표 이름" value={title} onChange={e => setTitle(e.target.value)} maxLength={120} className={field} /></label>
      {definition && <>
        {periodSources(definition).map(period => <label key={period.path} className="text-xs">{period.label}<select aria-label={`저장 ${period.label}`} className={field} value={period.value} disabled={!period.enabled} onChange={e => updatePeriod(period.path, e.target.value)}>{Object.entries(periods).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select>{!period.enabled && <span className="mt-1 block text-muted-foreground">기간을 바꾸려면 날짜 컬럼이 필요합니다.</span>}</label>)}
        <label className="text-xs">표시 단위{isSingle ? <select aria-label="저장 표시 단위" className={field} value={definition.operation === "count" ? "count" : String(definition.unit || "")} disabled={definition.operation === "count"} onChange={e => setDefinition({ ...definition, unit: e.target.value || null })}><option value="">단위 미지정</option><option value="KRW">원 (KRW)</option><option value="count">건</option><option value="number">일반 숫자</option></select> : <p className={field}>{({ KRW: "원 (KRW)", count: "건", percent: "%", number: "일반 숫자" } as Record<string, string>)[chart.unit || ""] || "계산식의 단위 유지"}</p>}<span className="mt-1 block text-muted-foreground">단위 표시는 금액을 환산하지 않습니다.</span></label>
        <label className="text-xs">갱신 주기<select aria-label="저장 갱신 주기" value={interval} onChange={e => setInterval(Number(e.target.value))} className={field}><option value={0}>수동</option><option value={3600}>매시간</option><option value={86400}>24시간마다</option></select></label>
      </>}
    </fieldset>
    {definition && !frozen && <Button size="sm" variant="outline" disabled={loading} onClick={() => void calculate()}>{loading ? "다시 계산하는 중…" : "설정으로 미리보기"}</Button>}
    {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
    {result && <div aria-label="저장 전 미리보기" className="rounded-lg border border-border bg-card p-3">
      {Array.isArray(result.data) ? <EChartsChart chartType={String(result.chart_type || "bar") as "line" | "bar" | "pie"} title={title} xKey={String(result.x_key || "dimension")} yKey={String(result.y_key || "value")} data={result.data as Record<string, unknown>[]} unit={String(result.unit || "")} height={230} /> : <p className="numeric py-5 text-2xl">{exactMetricValue(result.value, String(result.unit || ""))}</p>}
      <MetricAnalysisDialog data={result} title={title} />
    </div>}
    {frozen && state.status === "error" && <p className="text-xs text-muted-foreground">응답 확인이 끝나지 않아 제출한 설정을 유지합니다. 다시 시도하면 같은 저장 요청을 확인합니다.</p>}
    <div className="flex flex-wrap items-center gap-3"><Button disabled={!title.trim() || loading || state.status === "saving" || (!!definition && !result && !frozen)} onClick={() => void onSave({ title: title.trim(), definition, refresh_interval_seconds: interval })}>{state.status === "saving" ? "저장 중…" : frozen ? "같은 설정으로 다시 시도" : "이 설정으로 저장"}</Button>{definition && !result && !frozen && <p className="text-xs text-muted-foreground">현재 설정으로 계산 결과를 확인한 뒤 저장하세요.</p>}</div>
  </div>;
}
