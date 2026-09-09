"use client";
import { FormEvent, useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useDashboard } from "@/app/contexts/dashboard-context";
import { parseError, type TableMeta } from "@/app/lib/api";
import { MetricAnalysisDialog, exactMetricValue } from "./metric-analysis-dialog";
import { EChartsChart } from "./echarts-chart";

type Store = { id: string; name: string; description?: string };
type Source = { table_id: string; label: string; column: string; date_column: string; amount_mode: string; currency: "KRW"; currency_column: string };
type Selection = { project_id: string; sources: Source[] };
const empty = (): Source => ({ table_id: "", label: "", column: "", date_column: "", amount_mode: "signed", currency: "KRW", currency_column: "" });

export function StoreMetricForm({ onCreated }: { onCreated: () => void }) {
  const { selectedProjectId, apiFetch } = useDashboard();
  const [projects, setProjects] = useState<Store[]>([]);
  const [more, setMore] = useState(true);
  const [pageBusy, setPageBusy] = useState(false);
  const [tables, setTables] = useState<Record<string, TableMeta[]>>({});
  const [selection, setSelection] = useState<Selection[]>([]);
  const [title, setTitle] = useState("");
  const [group, setGroup] = useState("store");
  const [period, setPeriod] = useState("this_month");
  const [interval, setInterval] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const [preview, setPreview] = useState<{ key: string; data: Record<string, unknown> } | null>(null);
  const definition = { version: 5, operation: "sum", group_by: group, time_range: period, stores: selection.map(s => ({ ...s, sources: s.sources.map(t => ({ ...t, date_column: t.date_column || null, currency_column: t.currency_column || null })) })) };
  const key = JSON.stringify(definition);
  const result = preview?.key === key ? preview.data : null;
  const field = "w-full rounded-md border border-input bg-background p-2 text-sm";

  useEffect(() => {
    let active = true;
    apiFetch("/api/projects?limit=20&offset=0").then(async res => {
      if (!res.ok) throw new Error(await parseError(res));
      const value = await res.json();
      if (active) { setProjects(value.projects); setMore(value.projects.length === 20); }
    }).catch(e => { if (active) setError(e.message); });
    return () => { active = false; };
  }, [apiFetch]);
  async function loadMore() {
    setPageBusy(true);
    try {
      const res = await apiFetch(`/api/projects?limit=20&offset=${projects.length}`);
      if (!res.ok) throw new Error(await parseError(res));
      const value = await res.json(); setProjects(prev => [...prev, ...value.projects.filter((p: Store) => !prev.some(s => s.id === p.id))]); setMore(value.projects.length === 20);
    } catch (e) { setError(e instanceof Error ? e.message : "가게를 불러오지 못했습니다."); }
    finally { setPageBusy(false); }
  }
  async function toggle(store: Store, checked: boolean) {
    setConfirmed(false);
    setSelection(prev => checked ? [...prev, { project_id: store.id, sources: [empty()] }] : prev.filter(s => s.project_id !== store.id));
    if (!checked || tables[store.id]) return;
    try {
      const res = await apiFetch(`/api/projects/${store.id}/tables`);
      if (!res.ok) throw new Error(await parseError(res));
      const value = await res.json(); setTables(prev => ({ ...prev, [store.id]: value.tables }));
    } catch (e) { setError(e instanceof Error ? e.message : "장부를 불러오지 못했습니다."); }
  }
  function update(pid: string, index: number, change: Partial<Source>) {
    setConfirmed(false); setSelection(prev => prev.map(s => s.project_id === pid ? { ...s, sources: s.sources.map((t, i) => i === index ? { ...t, ...change } : t) } : s));
  }
  async function calculate(event: FormEvent) {
    event.preventDefault(); setBusy(true); setError(""); setConfirmed(false); setPreview(null);
    try {
      const res = await apiFetch(`/api/projects/${selectedProjectId}/metrics/preview`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ definition }) });
      if (!res.ok) throw new Error(await parseError(res));
      setPreview({ key, data: await res.json() });
    } catch (e) { setError(e instanceof Error ? e.message : "비교를 계산하지 못했습니다."); }
    finally { setBusy(false); }
  }
  async function save() {
    if (!confirmed || !result || !title.trim()) return;
    setBusy(true); setError("");
    try {
      const res = await apiFetch(`/api/projects/${selectedProjectId}/metrics`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ title, definition, refresh_interval_seconds: interval }) });
      if (!res.ok) throw new Error(await parseError(res));
      setPreview(null); setTitle(""); onCreated();
    } catch (e) { setError(e instanceof Error ? e.message : "저장하지 못했습니다."); }
    finally { setBusy(false); }
  }
  return <details className="rounded-xl border bg-card p-4" aria-label="여러 가게 지표 만들기">
    <summary className="cursor-pointer font-medium">여러 가게 순결제액 비교·합산</summary>
    <p className="my-3 text-sm text-muted-foreground">선택한 가게의 결제·취소 발생일 기준 원화 순결제액을 계산합니다. 수수료 차감 전 금액이며, 현재 가게의 대시보드에 저장됩니다.</p>
    {error && <p role="alert" className="my-2 text-sm text-destructive">{error}</p>}
    <form onSubmit={calculate} className="space-y-4"><fieldset disabled={busy} className="space-y-4">
      <label className="block text-sm">여러 가게 지표 이름<Input required maxLength={120} value={title} onChange={e => setTitle(e.target.value)} placeholder="예: 두 지점 순결제액 비교" /></label>
      <fieldset className="rounded-md border p-3"><legend className="px-1 text-sm">대상 가게 ({selection.length}/10)</legend>
        <div className="grid gap-2 sm:grid-cols-2">{projects.map(p => <label className="flex items-start gap-2 text-sm" key={p.id}><input type="checkbox" checked={selection.some(s => s.project_id === p.id)} disabled={selection.length >= 10 && !selection.some(s => s.project_id === p.id)} onChange={e => void toggle(p, e.target.checked)} />{p.name}{p.description ? ` · ${p.description}` : ""}</label>)}</div>
        {more && <Button type="button" variant="ghost" disabled={pageBusy} onClick={loadMore}>가게 더 보기</Button>}
      </fieldset>
      {selection.map(store => <fieldset key={store.project_id} className="rounded-md border p-3 space-y-3"><legend className="px-1 text-sm font-medium">{projects.find(p => p.id === store.project_id)?.name}</legend>
        {!tables[store.project_id] ? <p className="text-sm">장부를 불러오는 중입니다.</p> : tables[store.project_id].length === 0 ? <p className="text-sm">장부가 없습니다. 이 가게에 파일을 먼저 등록하세요.</p> : store.sources.map((source, index) => {
          const options = tables[store.project_id]; const table = options.find(t => t.id === source.table_id);
          return <div key={index} className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <label className="text-sm">장부 {index + 1}<select aria-label={`장부 ${index + 1}`} required className={field} value={source.table_id} onChange={e => update(store.project_id, index, { table_id: e.target.value, label: (options.find(t => t.id === e.target.value)?.name || "").slice(0, 80), column: "", date_column: "", currency_column: options.find(t => t.id === e.target.value)?.columns_schema.some(c => c.name === "currency") ? "currency" : "" })}><option value="">선택</option>{options.map(t => <option key={t.id} value={t.id} disabled={store.sources.some((s, j) => j !== index && s.table_id === t.id)}>{t.name}</option>)}</select></label>
            <label className="text-sm">금액 컬럼<select aria-label="금액 컬럼" required className={field} value={source.column} onChange={e => update(store.project_id, index, { column: e.target.value })}><option value="">선택</option>{table?.columns_schema.filter(c => /^(NUMERIC|DECIMAL|BIGINT|INTEGER|SMALLINT|REAL|DOUBLE|INT)/i.test(c.type)).map(c => <option key={c.name}>{c.name}</option>)}</select></label>
            <label className="text-sm">결제·취소 발생일<select aria-label="결제·취소 발생일" required={period !== "all"} className={field} value={source.date_column} onChange={e => update(store.project_id, index, { date_column: e.target.value })}><option value="">선택</option>{table?.columns_schema.filter(c => /^(DATE|TIMESTAMP)/i.test(c.type)).map(c => <option key={c.name}>{c.name}</option>)}</select></label>
            <label className="text-sm">통화 컬럼<select aria-label="통화 컬럼" className={field} value={source.currency_column} onChange={e => update(store.project_id, index, { currency_column: e.target.value })}><option value="">통화 컬럼 없음 · 원화 장부 확인</option>{table?.columns_schema.filter(c => /^(TEXT|VARCHAR|CHAR)/i.test(c.type)).map(c => <option key={c.name}>{c.name}</option>)}</select></label>
            <label className="text-sm">금액 처리<select aria-label="금액 처리" className={field} value={source.amount_mode} onChange={e => update(store.project_id, index, { amount_mode: e.target.value })}><option value="signed">원본 부호 유지</option><option value="refund">별도 취소 장부 차감</option></select></label>
            {store.sources.length > 1 && <Button type="button" variant="ghost" onClick={() => { setConfirmed(false); setSelection(prev => prev.map(s => s.project_id === store.project_id ? { ...s, sources: s.sources.filter((_, i) => i !== index) } : s)); }}>장부 {index + 1} 제외</Button>}
          </div>;
        })}
        {store.sources.length < 5 && selection.reduce((n, s) => n + s.sources.length, 0) < 20 && <Button type="button" variant="outline" onClick={() => { setConfirmed(false); setSelection(prev => prev.map(s => s.project_id === store.project_id ? { ...s, sources: [...s.sources, empty()] } : s)); }}>이 가게에 장부 추가</Button>}
      </fieldset>)}
      <div className="grid gap-3 sm:grid-cols-3">
        <label className="text-sm">비교 방식<select aria-label="비교 방식" className={field} value={group} onChange={e => setGroup(e.target.value)}><option value="store">가게별 막대 비교</option><option value="none">선택 가게 전체 합계</option></select></label>
        <label className="text-sm">공통 기간<select aria-label="공통 기간" className={field} value={period} onChange={e => setPeriod(e.target.value)}><option value="this_month">이번 달</option><option value="last_month">지난달</option><option value="last_30_days">최근 30일</option><option value="all">전체 기간</option></select></label>
        <label className="text-sm">갱신 주기<select aria-label="갱신 주기" className={field} value={interval} onChange={e => setInterval(Number(e.target.value))}><option value={0}>수동</option><option value={3600}>매시간</option><option value={86400}>24시간마다</option></select></label>
      </div>
      <Button type="submit" disabled={selection.length < 2 || selection.some(s => !tables[s.project_id]?.length)}>여러 가게 결과 미리보기</Button>
    </fieldset></form>
    {result && <div className="mt-4 space-y-3 border-t pt-4">
      {group === "store" ? <EChartsChart chartType="bar" title={title} xKey="dimension" yKey="value" data={result.data as Record<string, unknown>[]} unit="KRW" height={240} /> : <p className="font-sans numeric text-lg">{exactMetricValue(result.value, "KRW")}</p>}
      {!!result.undefined_reason && <p role="status" className="text-sm">{String(result.undefined_reason)}</p>}
      <MetricAnalysisDialog data={result} title={title} />
      <label className="flex gap-2 text-sm"><input type="checkbox" checked={confirmed} onChange={e => setConfirmed(e.target.checked)} />각 가게의 원화 결제·취소 원장이며 서로 겹치지 않는 출처입니다. 정산 입금액·내부 이체·집계 파일을 포함하지 않았습니다.</label>
      <Button disabled={!confirmed || busy || !title.trim()} onClick={save}>여러 가게 지표 저장</Button>
    </div>}
  </details>;
}
