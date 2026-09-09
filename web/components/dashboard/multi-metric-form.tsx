"use client";

import { FormEvent, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useDashboard } from "@/app/contexts/dashboard-context";
import { parseError, type TableMeta } from "@/app/lib/api";

type Source = { tableId: string; column: string; dateColumn: string; label: string; mode: string };
const emptySource = (): Source => ({ tableId: "", column: "", dateColumn: "", label: "", mode: "signed" });
type Preview = { value?: string | null; data?: { dimension: string; value: string }[]; sources?: { label: string; included_rows: number }[] };

export function MultiMetricForm({ tables, onCreated }: { tables: TableMeta[]; onCreated: () => void }) {
  const { selectedProjectId, apiFetch } = useDashboard();
  const [sources, setSources] = useState<Source[]>([emptySource(), emptySource()]);
  const [title, setTitle] = useState("");
  const [group, setGroup] = useState("date");
  const [grain, setGrain] = useState("day");
  const [period, setPeriod] = useState("all");
  const [interval, setInterval] = useState(0);
  const [confirmed, setConfirmed] = useState(false);
  const [preview, setPreview] = useState<{ key: string; result: Preview } | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const needsDate = group === "date" || period !== "all";
  const selectClass = "w-full rounded-md border border-input bg-background p-2 text-sm";
  const definition = { version: 2, operation: "sum", group_by: group, date_grain: grain, time_range: period,
    sources: sources.map((s) => ({ table_id: s.tableId, column: s.column, date_column: s.dateColumn || null,
      label: s.label, amount_mode: s.mode, currency: "KRW" })) };
  const definitionKey = JSON.stringify(definition);
  const currentPreview = preview?.key === definitionKey ? preview.result : null;

  function updateSource(index: number, patch: Partial<Source>) {
    setSources((prev) => prev.map((source, i) => i === index ? { ...source, ...patch } : source));
    setConfirmed(false);
  }

  async function run(event: FormEvent) {
    event.preventDefault();
    setBusy(true); setError(""); setPreview(null); setConfirmed(false);
    try {
      const res = await apiFetch(`/api/projects/${selectedProjectId}/metrics/preview`, {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ definition }),
      });
      if (!res.ok) throw new Error(await parseError(res));
      setPreview({ key: definitionKey, result: await res.json() });
    } catch (err) { setError(err instanceof Error ? err.message : "통합 지표를 계산하지 못했습니다."); }
    finally { setBusy(false); }
  }

  async function save() {
    if (!currentPreview || !confirmed || !title.trim()) return;
    setBusy(true); setError("");
    try {
      const res = await apiFetch(`/api/projects/${selectedProjectId}/metrics`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title, definition, refresh_interval_seconds: interval }),
      });
      if (!res.ok) throw new Error(await parseError(res));
      setPreview(null); setTitle(""); onCreated();
    } catch (err) { setError(err instanceof Error ? err.message : "저장하지 못했습니다."); }
    finally { setBusy(false); }
  }

  if (tables.length < 2) return null;
  return (
    <details className="rounded-xl border border-border bg-card p-4">
      <summary className="cursor-pointer font-medium">여러 장부의 결제액 합치기</summary>
      <p className="my-3 text-sm text-muted-foreground">같은 가게의 현금·카드 장부를 연결해 원화 결제액을 집계합니다. 거래별 내역을 선택하고, 정산 입금액이나 이미 합산된 통계 파일은 함께 넣지 마세요.</p>
      {error && <p role="alert" className="mb-3 text-sm text-destructive">{error}</p>}
      <form onSubmit={run} className="space-y-4">
        <fieldset disabled={busy} className="space-y-4">
          <label className="block space-y-1 text-sm">지표 이름<Input required value={title} maxLength={120} onChange={(e) => setTitle(e.target.value)} placeholder="예: 현금·카드 통합 결제액" /></label>
          {sources.map((source, i) => {
            const table = tables.find((t) => t.id === source.tableId);
            return <fieldset key={i} className="grid gap-3 border-t border-border pt-3 sm:grid-cols-2 lg:grid-cols-3">
              <legend className="text-sm font-medium">장부 {i + 1}</legend>
              <label className="space-y-1 text-sm">장부<select required className={selectClass} value={source.tableId} onChange={(e) => updateSource(i, { tableId: e.target.value, column: "", dateColumn: "", label: tables.find((t) => t.id === e.target.value)?.name || "" })}><option value="">선택</option>{tables.map((t) => <option key={t.id} value={t.id} disabled={sources.some((s, j) => j !== i && s.tableId === t.id)}>{t.name}</option>)}</select></label>
              <label className="space-y-1 text-sm">표시 이름<Input required maxLength={80} value={source.label} onChange={(e) => updateSource(i, { label: e.target.value })} placeholder="현금 / 카드 / 취소" /></label>
              <label className="space-y-1 text-sm">금액 컬럼<select required className={selectClass} value={source.column} onChange={(e) => updateSource(i, { column: e.target.value })}><option value="">선택</option>{table?.columns_schema.filter((c) => /^(NUMERIC|DECIMAL|BIGINT|INTEGER|SMALLINT|REAL|DOUBLE|INT)/i.test(c.type)).map((c) => <option key={c.name}>{c.name}</option>)}</select></label>
              {needsDate && <label className="space-y-1 text-sm">결제·취소일 컬럼<select required className={selectClass} value={source.dateColumn} onChange={(e) => updateSource(i, { dateColumn: e.target.value })}><option value="">선택</option>{table?.columns_schema.filter((c) => /^(DATE|TIMESTAMP)/i.test(c.type)).map((c) => <option key={c.name}>{c.name}</option>)}</select></label>}
              <label className="space-y-1 text-sm">금액 처리<select className={selectClass} value={source.mode} onChange={(e) => updateSource(i, { mode: e.target.value })}><option value="signed">원본 금액의 부호 유지</option><option value="refund">별도 취소 장부 (차감)</option></select></label>
              {sources.length > 2 && <Button type="button" variant="ghost" onClick={() => { setSources((prev) => prev.filter((_, j) => j !== i)); setConfirmed(false); }}>장부 {i + 1} 제외</Button>}
            </fieldset>;
          })}
          {sources.length < 5 && <Button type="button" variant="outline" onClick={() => { setSources((prev) => [...prev, emptySource()]); setConfirmed(false); }}>장부 추가</Button>}
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <label className="space-y-1 text-sm">집계<select className={selectClass} value={group} onChange={(e) => setGroup(e.target.value)}><option value="none">전체 합계</option><option value="date">날짜별 합계</option><option value="source">장부별 합계</option></select></label>
            {group === "date" && <label className="space-y-1 text-sm">날짜 단위<select className={selectClass} value={grain} onChange={(e) => setGrain(e.target.value)}><option value="day">일별</option><option value="week">주별</option><option value="month">월별</option></select></label>}
            <label className="space-y-1 text-sm">기간<select className={selectClass} value={period} onChange={(e) => setPeriod(e.target.value)}><option value="all">전체</option><option value="this_month">이번 달</option><option value="last_month">지난달</option><option value="last_30_days">최근 30일</option></select></label>
            <label className="space-y-1 text-sm">갱신<select className={selectClass} value={interval} onChange={(e) => setInterval(Number(e.target.value))}><option value={0}>수동</option><option value={3600}>매시간</option><option value={86400}>24시간마다</option></select></label>
          </div>
          <Button type="submit">{busy ? "계산 중…" : "통합 결과 미리보기"}</Button>
        </fieldset>
      </form>
      {currentPreview && <div className="mt-4 space-y-3 border-t border-border pt-4">
        <p className="font-medium">계산 결과 {group === "none" ? `${currentPreview.value ?? "데이터 없음"}${currentPreview.value == null ? "" : "원"}` : "(원)"}</p>
        <p className="text-sm text-muted-foreground">{currentPreview.sources?.map((s) => `${s.label}: ${s.included_rows}행`).join(" · ")}</p>
        {currentPreview.data && <div className="max-h-56 overflow-auto"><table className="w-full text-sm"><thead><tr><th className="text-left">구분</th><th className="text-right">금액</th></tr></thead><tbody>{currentPreview.data.map((row) => <tr key={row.dimension}><td>{row.dimension}</td><td className="text-right font-sans numeric">{row.value ?? "데이터 없음"}</td></tr>)}</tbody></table></div>}
        <label className="flex items-start gap-2 text-sm"><input type="checkbox" checked={confirmed} onChange={(e) => setConfirmed(e.target.checked)} />서로 겹치지 않는 원화 결제·취소 이벤트 장부입니다. 별도 파일의 중복 거래는 자동 제거되지 않습니다.</label>
        <Button disabled={!confirmed || busy || !title.trim()} onClick={save}>대시보드에 저장</Button>
      </div>}
    </details>
  );
}
