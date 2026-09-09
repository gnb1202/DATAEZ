"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { useDashboard } from "@/app/contexts/dashboard-context";
import { parseError } from "@/app/lib/api";
import { Button } from "@/components/ui/button";

type Payload = { amount: string; occurred_on: string; kind: "payment" | "refund"; channel: string | null; memo: string; original_event_id: string | null };
type Entry = { id: string; status: "draft" | "committed" | "cancelled"; payload: Payload; is_expired: boolean; committed_at?: string;
  confirmation_token?: string; event_id?: string; similar?: { count: number; entries: { id: string; payload: Payload }[] } };
const field = "w-full rounded-lg border border-border bg-background px-3 py-2 text-sm";
const amountText = (value: string) => value.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
const statusText = (entry: Entry) => entry.status === "committed" ? "반영 완료" : entry.status === "cancelled" ? "초안 취소" : entry.is_expired ? "초안 만료" : "반영 전";

export function CashEntryPanel({ onTablesChange }: { onTablesChange: () => void }) {
  const { selectedProjectId: projectId, apiFetch } = useDashboard();
  const base = `/api/projects/${projectId}/cash-entries`;
  const [today, setToday] = useState("");
  const [entry, setEntry] = useState<Entry | null>(null);
  const [history, setHistory] = useState<Entry[]>([]);
  const [page, setPage] = useState(0);
  const [total, setTotal] = useState(0);
  const [version, setVersion] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [historyError, setHistoryError] = useState("");
  const [separate, setSeparate] = useState(false);
  const request = useRef<{ signature: string; key: string } | null>(null);
  const alive = useRef(true);
  const json = useCallback(async (path: string, init?: RequestInit) => {
    const res = await apiFetch(path, init);
    if (!res.ok) throw new Error(await parseError(res));
    return res.json();
  }, [apiFetch]);
  const post = (path: string, payload: unknown) => json(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
  useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);
  useEffect(() => {
    let active = true;
    const params = new URLSearchParams(window.location.search);
    const id = params.get("project") === projectId ? params.get("cash_draft") : null;
    if (id) json(`${base}/${encodeURIComponent(id)}`).then(value => {
      if (active) { setEntry(value); document.getElementById("cash-entry-panel")?.scrollIntoView({ block: "start" }); }
    }).catch(err => { if (active) setError(err.message); });
    return () => { active = false; };
  }, [base, json, projectId]);
  useEffect(() => {
    let active = true; setHistoryError("");
    json(`${base}?limit=20&offset=${page * 20}`).then(value => {
      if (active) { setHistory(value.entries); setTotal(value.total); setToday(value.today); }
    }).catch(err => { if (active) setHistoryError(err.message); });
    return () => { active = false; };
  }, [base, json, page, version]);
  async function run(action: () => Promise<void>) {
    setBusy(true); setError("");
    try { await action(); }
    catch (err) { if (alive.current) setError(err instanceof Error ? err.message : "현금 입력에 실패했습니다."); }
    finally { if (alive.current) { setBusy(false); setVersion(v => v + 1); } }
  }
  async function create(form: HTMLFormElement) {
    const data = new FormData(form);
    const payload = { amount: String(data.get("amount") || "").trim(), occurred_on: data.get("occurred_on"), kind: data.get("kind"),
      channel: data.get("channel") || null, memo: data.get("memo") || "", original_event_id: data.get("original_event_id") || null };
    const signature = JSON.stringify(payload);
    if (request.current?.signature !== signature) request.current = { signature, key: crypto.randomUUID() };
    const value = await post(`${base}/drafts`, { ...payload, request_key: request.current.key });
    if (alive.current) { setEntry(value); setSeparate(false); setPage(0); }
  }
  async function confirm() {
    if (!entry) return;
    try {
      const value = await post(`${base}/${entry.id}/commit`, { confirmation_token: entry.confirmation_token, separate_transaction: separate });
      if (alive.current) { setEntry(value); setPage(0); onTablesChange(); }
    } catch (err) {
      // A concurrent entry can create a new duplicate warning; a lost success
      // response can already be committed. Read the durable state before retry.
      const current = await json(`${base}/${entry.id}`).catch(() => null);
      if (current && alive.current) { setEntry(current); setSeparate(false); if (current.status === "committed") { onTablesChange(); return; } }
      throw err;
    }
  }
  return <section id="cash-entry-panel" aria-label="현금 직접 입력" className="rounded-xl border border-border bg-card p-5 space-y-4 scroll-mt-6">
    <div><h2 className="font-semibold text-lg">현금 직접 입력</h2><p className="text-sm text-muted-foreground mt-1">선택한 가게의 현금 수납과 취소를 기록합니다. 내용을 확인한 뒤 장부에 반영하세요.</p></div>
    {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
    {!entry ? <form onSubmit={event => { event.preventDefault(); const form = event.currentTarget; void run(() => create(form)); }} className="space-y-3">
      <fieldset disabled={busy} className="grid gap-3 sm:grid-cols-3 disabled:opacity-60">
        <label className="text-sm space-y-1"><span>거래 일자 (한국 날짜)</span><input required type="date" name="occurred_on" key={today} defaultValue={today} className={field} /></label>
        <label className="text-sm space-y-1"><span>종류</span><select name="kind" className={field}><option value="payment">현금 수납</option><option value="refund">현금 취소·환불 기록</option></select></label>
        <label className="text-sm space-y-1"><span>금액 (원)</span><input required name="amount" inputMode="decimal" placeholder="예: 30000" maxLength={50} className={field} /></label>
        <label className="text-sm space-y-1"><span>판매 채널 (선택)</span><input name="channel" maxLength={80} placeholder="예: 매장" className={field} /></label>
        <label className="text-sm space-y-1 sm:col-span-2"><span>메모 (선택)</span><input name="memo" maxLength={500} placeholder="예: 점심 현금 매출" className={field} /></label>
        <label className="text-sm space-y-1 sm:col-span-3"><span>취소 원거래 ID (선택)</span><input name="original_event_id" maxLength={120} placeholder="취소 기록에서만 입력" className={field} /></label>
      </fieldset>
      <p className="text-xs text-muted-foreground">금액은 양수로 입력하세요. 취소 기록은 장부에 음수로 반영됩니다. 거래 시각과 PG 수수료는 수집하지 않으며, 실제 환불을 실행하지 않습니다.</p>
      <Button type="submit" disabled={busy || !today}>{busy ? "처리 중…" : "입력 내용 확인"}</Button>
    </form> : <div className="rounded-lg border border-border bg-background p-4 space-y-3">
      <p className="text-sm font-medium">{statusText(entry)} · {entry.payload.occurred_on} · {entry.payload.kind === "refund" ? "현금 취소" : "현금 수납"}</p>
      <p className="text-2xl font-semibold tabular-nums">{entry.payload.kind === "refund" ? "−" : ""}{amountText(entry.payload.amount)}원</p>
      <dl className="text-sm grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 break-words"><dt>채널</dt><dd>{entry.payload.channel || "미입력"}</dd><dt>메모</dt><dd className="whitespace-pre-wrap">{entry.payload.memo || "미입력"}</dd>{entry.payload.original_event_id && <><dt>원거래</dt><dd>{entry.payload.original_event_id}</dd></>}</dl>
      {entry.status === "committed" && <><p role="status" className="text-sm">현금 장부에 반영했습니다. 대시보드에서 재계산하거나 다음 자동 갱신을 기다려 주세요.</p><p className="text-xs break-all text-muted-foreground">거래 ID: {entry.event_id}</p></>}
      {entry.status === "draft" && !entry.is_expired && <>
        {!!entry.similar?.count && <div className="rounded-lg border border-amber-500/50 p-3 space-y-2 text-sm"><p>같은 날짜·종류·금액의 현금 기록 {entry.similar.count}건이 있습니다.</p>
          <ul className="list-disc pl-5">{entry.similar.entries.map(item => <li key={item.id}>{item.payload.channel || "채널 미입력"} · {item.payload.memo || "메모 없음"}</li>)}</ul>
          <label className="flex gap-2 items-start"><input type="checkbox" checked={separate} disabled={busy} onChange={event => setSeparate(event.target.checked)} /><span>기존 기록을 확인했으며 별도 거래입니다.</span></label></div>}
        <p className="text-xs text-muted-foreground">초안은 작성 후 24시간 동안 반영할 수 있습니다.</p>
        <div className="flex flex-wrap gap-2"><Button disabled={busy || (!!entry.similar?.count && !separate)} onClick={() => void run(confirm)}>현금 장부에 반영</Button>
          <Button variant="outline" disabled={busy} onClick={() => void run(async () => { await json(`${base}/${entry.id}`, { method: "DELETE" }); if (alive.current) { setEntry(null); request.current = null; } })}>초안 취소</Button></div>
      </>}
      <Button variant="ghost" disabled={busy} onClick={() => { setEntry(null); setSeparate(false); setError(""); request.current = null; }}>새 거래 입력</Button>
    </div>}
    <details><summary className="cursor-pointer text-sm font-medium">현금 입력 이력 ({total}건)</summary>
      {historyError && <p role="alert" className="text-sm text-destructive">{historyError}</p>}
      <div className="mt-3 space-y-2">{history.length ? history.map(item => <div key={item.id} className="flex flex-wrap justify-between items-center gap-2 border-b border-border pb-2 text-sm">
        <div><p>{item.payload.occurred_on} · {item.payload.kind === "refund" ? "취소 −" : "수납 "}{amountText(item.payload.amount)}원 · {statusText(item)}</p><p className="text-muted-foreground break-all">{item.payload.memo || "메모 없음"}</p></div>
        <Button size="sm" variant="outline" disabled={busy} onClick={() => void run(async () => { const value = await json(`${base}/${item.id}`); if (alive.current) { setEntry(value); setSeparate(false); } })}>기록 확인</Button>
      </div>) : <p className="text-sm text-muted-foreground">현금 입력 이력이 없습니다.</p>}</div>
      <div className="flex items-center gap-3 mt-3 text-sm"><Button size="sm" variant="outline" disabled={!page || busy} onClick={() => setPage(p => p - 1)}>이전</Button><span>{page + 1} / {Math.max(1, Math.ceil(total / 20))}</span><Button size="sm" variant="outline" disabled={(page + 1) * 20 >= total || busy} onClick={() => setPage(p => p + 1)}>다음</Button></div>
    </details>
  </section>;
}
