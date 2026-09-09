"use client";

import { FormEvent, useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useDashboard } from "@/app/contexts/dashboard-context";
import { parseError, type TableMeta } from "@/app/lib/api";
import { MultiMetricForm } from "./multi-metric-form";

export function MetricCreateForm({ onCreated }: { onCreated: () => void }) {
  const { selectedProjectId, apiFetch } = useDashboard();
  const [tables, setTables] = useState<TableMeta[]>([]);
  const [title, setTitle] = useState("");
  const [tableId, setTableId] = useState("");
  const [operation, setOperation] = useState("sum");
  const [column, setColumn] = useState("");
  const [groupBy, setGroupBy] = useState("");
  const [grain, setGrain] = useState("");
  const [period, setPeriod] = useState("all");
  const [dateColumn, setDateColumn] = useState("");
  const [interval, setInterval] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let active = true;
    apiFetch(`/api/projects/${selectedProjectId}/tables`)
      .then(async (res) => {
        if (!res.ok) throw new Error(await parseError(res));
        const data = await res.json();
        if (active) setTables(data.tables || []);
      })
      .catch((err) => { if (active) setError(String(err.message)); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [selectedProjectId, apiFetch]);

  const table = tables.find((t) => t.id === tableId);
  const numeric = table?.columns_schema.filter((c) => /^(NUMERIC|DECIMAL|BIGINT|INTEGER|SMALLINT|REAL|DOUBLE|INT)/i.test(c.type)) || [];
  const isDate = table?.columns_schema.some((c) => c.name === groupBy && /^(DATE|TIMESTAMP)/i.test(c.type));
  const selectClass = "w-full rounded-md border border-input bg-background p-2 text-sm";

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const res = await apiFetch(`/api/projects/${selectedProjectId}/metrics`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title, refresh_interval_seconds: interval, definition: {
          table_id: tableId, operation, column: operation === "count" ? null : column,
          group_by: groupBy || null, date_grain: isDate && grain ? grain : null,
          chart_type: "bar",
          time_range: period, date_column: period === "all" ? null : dateColumn,
        } }),
      });
      if (!res.ok) throw new Error(await parseError(res));
      setTitle("");
      onCreated();
    } catch (err) {
      setError(err instanceof Error ? err.message : "지표를 저장하지 못했습니다.");
    } finally { setBusy(false); }
  }

  return (
    <>
    <details className="rounded-xl border border-border bg-card p-4">
      <summary className="cursor-pointer font-medium">갱신 가능한 지표 만들기</summary>
      <p className="my-3 text-sm text-muted-foreground">현재 가게의 장부로 지표를 만들고 갱신 주기를 정하세요. 채팅에서도 원하는 지표를 요청할 수 있습니다.</p>
      {error && <p role="alert" className="mb-3 text-sm text-destructive">{error}</p>}
      {loading ? <p>장부를 불러오는 중입니다.</p> : !tables.length ? <p className="text-sm">장부 관리에서 이 가게의 데이터를 먼저 등록해주세요.</p> : (
        <form onSubmit={submit} className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          <label className="space-y-1 text-sm">지표 이름<Input required maxLength={120} value={title} onChange={(e) => setTitle(e.target.value)} placeholder="예: 결제수단별 결제액" /></label>
          <label className="space-y-1 text-sm">장부<select aria-label="장부" required className={selectClass} value={tableId} onChange={(e) => { setTableId(e.target.value); setColumn(""); setGroupBy(""); setGrain(""); setDateColumn(""); }}><option value="">장부 선택</option>{tables.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}</select></label>
          <label className="space-y-1 text-sm">계산<select aria-label="계산" className={selectClass} value={operation} onChange={(e) => setOperation(e.target.value)}>{Object.entries({ sum: "합계", count: "행 건수", avg: "평균", min: "최솟값", max: "최댓값" }).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
          {operation !== "count" && <label className="space-y-1 text-sm">숫자 컬럼<select aria-label="숫자 컬럼" required className={selectClass} value={column} onChange={(e) => setColumn(e.target.value)}><option value="">컬럼 선택</option>{numeric.map((c) => <option key={c.name}>{c.name}</option>)}</select></label>}
          <label className="space-y-1 text-sm">묶어서 보기<select aria-label="묶어서 보기" className={selectClass} value={groupBy} onChange={(e) => { setGroupBy(e.target.value); setGrain(""); }}><option value="">전체 합산 (KPI)</option>{table?.columns_schema.map((c) => <option key={c.name}>{c.name}</option>)}</select></label>
          {isDate && <label className="space-y-1 text-sm">날짜 단위<select aria-label="날짜 단위" className={selectClass} value={grain} onChange={(e) => setGrain(e.target.value)}><option value="">원본 값</option><option value="day">일별</option><option value="week">주별</option><option value="month">월별</option></select></label>}
          <label className="space-y-1 text-sm">기간<select aria-label="기간" className={selectClass} value={period} onChange={(e) => setPeriod(e.target.value)}><option value="all">전체 기간</option><option value="this_month">이번 달</option><option value="last_month">지난달</option><option value="last_30_days">최근 30일</option></select></label>
          {period !== "all" && <label className="space-y-1 text-sm">기간 기준 컬럼<select aria-label="기간 기준 컬럼" required className={selectClass} value={dateColumn} onChange={(e) => setDateColumn(e.target.value)}><option value="">날짜 컬럼 선택</option>{table?.columns_schema.filter((c) => /^(DATE|TIMESTAMP)/i.test(c.type)).map((c) => <option key={c.name}>{c.name}</option>)}</select></label>}
          <label className="space-y-1 text-sm">자동 갱신<select aria-label="자동 갱신" className={selectClass} value={interval} onChange={(e) => setInterval(Number(e.target.value))}><option value={0}>수동</option><option value={3600}>매시간</option><option value={86400}>24시간마다</option></select></label>
          <div className="flex items-end"><Button disabled={busy || !tableId || !title.trim()} type="submit">{busy ? "계산 중…" : "계산하고 대시보드에 추가"}</Button></div>
        </form>
      )}
    </details>
    <MultiMetricForm tables={tables} onCreated={onCreated} />
    </>
  );
}
