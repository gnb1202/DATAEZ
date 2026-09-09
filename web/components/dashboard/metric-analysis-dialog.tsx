"use client";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog";

// Decimal strings must never pass through Number when shown as evidence.
export function exactMetricValue(value: unknown, unit?: string): string {
  if (value == null) return "계산 불가";
  const raw = String(value);
  // Group only the integer part, preserving every decimal digit.
  const parts = raw.split(".");
  const text = /^-?\d+(\.\d+)?$/.test(raw) ? parts[0].replace(/\B(?=(\d{3})+(?!\d))/g, ",") + (parts.length > 1 ? "." + parts[1] : "") : raw;
  return text + ({ KRW: "원", percent: "%", count: "건" }[unit || ""] || "");
}

function sourceChangeTime(value?: string): string {
  if (!value) return "미제공";
  if (!/(Z|[+-]\d{2}:?\d{2})$/i.test(value)) return value.replace("T", " ") + " (시간대 미제공)";
  return new Date(value).toLocaleString("ko-KR", { timeZone: "Asia/Seoul" }) + " (한국 시간)";
}

export function MetricAnalysisDialog({ data, title }: { data: Record<string, unknown>; title: string }) {
  const [page, setPage] = useState(0);
  const rows = Array.isArray(data.store_data) ? data.store_data as Record<string, unknown>[] : Array.isArray(data.data) ? data.data as Record<string, unknown>[] : [{ value: data.value, undefined_reason: data.undefined_reason }];
  const operands = (data.formula_operands || []) as { label: string; table_name: string; column?: string; operation: string; period_label: string; group_by?: string; date_grain?: string; unit: string; absolute?: boolean; value?: string | null; filters?: unknown[] }[];
  const grouped = Array.isArray(data.data) || Array.isArray(data.store_data);
  const sources = (data.sources || []) as {project_id?:string;project_name?:string;table_name:string;label:string;column:string;date_column?:string;currency_column?:string;amount_mode:string;included_rows:number;source_updated_at?:string;filters?:unknown[]}[];
  const formula = grouped && operands.length === 2;
  const execution = data.execution as { sql: string; parameters: unknown[]; timezone: string } | undefined;
  const unit = String(data.unit || data.currency || "");
  const pages = Math.max(1, Math.ceil(rows.length / 25));
  const safePage = Math.min(page, pages - 1);
  return <Dialog onOpenChange={open => { if (open) setPage(0); }}>
    <DialogTrigger asChild><Button size="sm" variant="ghost" aria-label={`${title} 집계표·SQL`}>집계표·SQL</Button></DialogTrigger>
    <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-4xl [&>*]:min-w-0">
      <DialogHeader><DialogTitle>{title || "지표"} · 분석 상세</DialogTitle></DialogHeader>
      <div className="space-y-1 text-sm text-muted-foreground">
        <p>출처: {String(data.source_table_name || "—")} · {String(data.period_label || "기간 정보 미제공")}</p>
        {!!data.calculation_label && <p className="text-foreground">{String(data.calculation_label)}</p>}
        {!!data.scope_label && <p className="font-medium text-foreground">분석 범위: {String(data.scope_label)}</p>}
        {!!data.refresh_note && <p>{String(data.refresh_note)}</p>}
        {Array.isArray(data.analysis_sources) && data.analysis_sources.map((source, i) => <p key={i}>{String(source.table_name)} · {String(source.scope_label)}</p>)}
        <p>계산 시각: {data.calculated_at ? sourceChangeTime(String(data.calculated_at)) : "—"}</p>
        {!!data.refresh_error && <p role="alert" className="text-destructive">갱신 실패 · 이전 계산 결과: {String(data.refresh_error)}</p>}
        {operands.map((o, i) => <p key={i}>{o.label}: {o.table_name} · {o.operation}({o.column || "행"}){o.absolute ? " · 절댓값 적용" : ""}{!grouped && o.value !== undefined ? ` · 입력값 ${exactMetricValue(o.value, o.unit)}` : ""} · {o.period_label}{o.group_by ? ` · ${o.group_by}${o.date_grain ? ` (${o.date_grain})` : ""}` : ""}{o.filters?.length ? ` · 필터 ${JSON.stringify(o.filters)}` : " · 필터 없음"}</p>)}
        {Array.isArray(data.warnings) && data.warnings.map((w, i) => <p key={i}>{String(w)}</p>)}
        {data.scope === "selected_stores" && <>
          <p className="text-foreground">계산 대상: {Array.isArray(data.stores) && data.stores.map(s => String(s.project_name)).join(" · ")}</p>
          {!Array.isArray(data.data) && <p>전체 합계: {exactMetricValue(data.value,unit)}{data.undefined_reason ? ` · ${String(data.undefined_reason)}` : ""}</p>}

        </>}
        {!!sources.length && <details><summary className="cursor-pointer">출처별 연결·계산 기준</summary>{sources.map((s, i) => <p key={i} className="my-2">{s.project_name ? `${s.project_name} · ` : ""}{s.label}: {s.table_name} · {s.column}{s.date_column ? ` / ${s.date_column}` : ""} · {s.amount_mode === "refund" ? "취소 차감" : "원본 부호 유지"} · {s.included_rows}행{s.filters?.length ? ` · 필터 ${JSON.stringify(s.filters)}` : " · 필터 없음"}{data.scope === "selected_stores" ? ` · ${s.currency_column ? `통화 ${s.currency_column} · KRW 검증` : "원화 장부로 지정"}` : ""} · 계산 시 확인한 장부 변경: {sourceChangeTime(s.source_updated_at)}</p>)}</details>}
      </div>
      <p className="text-xs text-muted-foreground">표는 계산 결과의 소수 정밀도를 보존합니다. 그래프 위치는 화면 표시용 근사값입니다. 계산 불가 값은 0으로 표시하지 않습니다.</p>
      <div className="overflow-x-auto rounded-md border">
        <table className="w-full text-sm" aria-label="정확한 집계 결과">
          <thead className="bg-muted"><tr>{grouped && <th className="p-3 text-left">{String(data.dimension_label || "그룹")}</th>}{formula && operands.map((o, i) => <th className="p-3 text-right" key={i}>{o.label}</th>)}<th className="p-3 text-right">결과</th><th className="p-3 text-left">계산 상태</th></tr></thead>
          <tbody>{rows.slice(safePage * 25, safePage * 25 + 25).map((r, i) => <tr key={i} className="border-t">
            {grouped && <td className="p-3 whitespace-nowrap">{r[String(data.x_key || "dimension")] == null ? "(분류 미제공)" : String(r[String(data.x_key || "dimension")])}</td>}
            {formula && ["left_value", "right_value"].map((key, j) => <td key={key} className="p-3 text-right font-sans numeric whitespace-nowrap">{r[key] == null ? "집계 없음" : exactMetricValue(r[key], operands[j].unit)}</td>)}
            <td className="p-3 text-right font-sans numeric whitespace-nowrap">{exactMetricValue(r[String(data.y_key || "value")], unit)}</td>
            <td className="p-3 text-xs">{r.undefined_reason ? String(r.undefined_reason) : r[String(data.y_key || "value")] == null ? "계산 불가" : "계산 완료"}{Array.isArray(r.zero_filled) && r.zero_filled.length > 0 && ` · 거래 없는 ${r.zero_filled.map(s => operands[s === "left" ? 0 : 1]?.label).join(", ")} 0 적용`}</td>
          </tr>)}</tbody>
        </table>
        {rows.length === 0 && <p className="p-4 text-sm">집계할 그룹이 없습니다.</p>}
      </div>
      {grouped && <div className="flex items-center justify-between text-xs"><span>{rows.length}개 그룹 · {safePage + 1}/{pages} 페이지</span><div className="flex gap-2"><Button variant="outline" size="sm" disabled={safePage === 0} onClick={() => setPage(safePage - 1)}>이전 그룹</Button><Button variant="outline" size="sm" disabled={safePage + 1 >= pages} onClick={() => setPage(safePage + 1)}>다음 그룹</Button></div></div>}
      <details className="rounded-md border p-3 text-sm"><summary className="cursor-pointer font-medium">실행 SQL과 매개변수</summary>
        {execution ? <div className="mt-3 space-y-3"><p className="text-xs text-muted-foreground">PostgreSQL · {execution.timezone} · 최근 성공한 계산의 SQL 템플릿과 별도 전달값입니다. %s는 매개변수 자리이며 %%는 드라이버 이스케이프입니다.</p><pre className="max-h-72 overflow-auto rounded bg-muted p-3 text-xs">{execution.sql}</pre><p>매개변수 (전달 순서)</p><pre className="max-h-40 overflow-auto rounded bg-muted p-3 text-xs">{JSON.stringify(execution.parameters, null, 2)}</pre></div> : <p className="mt-3 text-muted-foreground">이 결과에는 실행 SQL이 기록되지 않았습니다.</p>}
      </details>
    </DialogContent>
  </Dialog>;
}
