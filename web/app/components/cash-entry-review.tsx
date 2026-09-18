"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { CheckCircle2, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { parseError, type AgentStep } from "../lib/api";

type ApiFetch = (path: string, init?: RequestInit) => Promise<Response>;
type Payload = { amount: string; occurred_on: string; kind: "payment" | "refund"; channel: string | null; memo: string; original_event_id: string | null };
type Entry = { id: string; project_id: string; status: "draft" | "committed" | "cancelled"; payload: Payload;
  is_expired: boolean; confirmation_token?: string; similar?: { count: number; entries: { id: string; payload: Payload }[] } };
export type CashReviewOptions = { projectId: string; storeName: string; revision: number; onCommitted: () => void; disabled: boolean };
const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const cashTools = new Set(["draft_cash_entry", "get_cash_entry"]);
const amountText = (amount: string) => {
  const [whole, fraction] = amount.split(".");
  return whole.replace(/\B(?=(\d{3})+(?!\d))/g, ",") + (fraction === undefined ? "" : `.${fraction}`);
};

export function CashEntryReviews({ steps, apiFetch, options }: { steps?: AgentStep[] | null; apiFetch: ApiFetch; options: CashReviewOptions }) {
  const ids = new Set<string>();
  for (const step of steps || []) {
    const output = step.tool_output;
    if ((step.type !== "tool_call" && step.type !== "tool_result") || !cashTools.has(step.tool_name || "") || !output || output.error) continue;
    if (output.project_id === options.projectId && typeof output.id === "string" && uuid.test(output.id)) ids.add(output.id);
  }
  return [...ids].map(id => <CashEntryReview key={`${options.projectId}:${id}`} entryId={id} apiFetch={apiFetch} options={options} />);
}

function CashEntryReview({ entryId, apiFetch, options }: { entryId: string; apiFetch: ApiFetch; options: CashReviewOptions }) {
  const { projectId, storeName, revision, onCommitted, disabled } = options;
  const path = `/api/projects/${encodeURIComponent(projectId)}/cash-entries/${entryId}`;
  const [entry, setEntry] = useState<Entry | null>(null);
  const [loading, setLoading] = useState(true), [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [verified, setVerified] = useState(false), [separate, setSeparate] = useState(false);
  const [retry, setRetry] = useState(0);
  const alive = useRef(true), pending = useRef(false), readVersion = useRef(0);
  useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);
  const read = useCallback(async (): Promise<Entry> => {
    const res = await apiFetch(path);
    if (!res.ok) throw new Error(await parseError(res));
    const value: Entry = await res.json();
    if (value.id !== entryId || value.project_id !== projectId) throw new Error("현재 가게의 현금 입력을 확인하지 못했습니다.");
    return value;
  }, [apiFetch, path, entryId, projectId]);

  useEffect(() => {
    const request = ++readVersion.current;
    if (disabled) { setLoading(false); return; }
    setLoading(true); setVerified(false); setSeparate(false); setError("");
    void read().then(value => {
      if (alive.current && request === readVersion.current) { setEntry(value); setVerified(true); }
    }).catch(err => {
      if (alive.current && request === readVersion.current) setError(err instanceof Error ? err.message : "현금 입력 상태를 확인하지 못했습니다.");
    }).finally(() => { if (alive.current && request === readVersion.current) setLoading(false); });
  }, [read, revision, retry, disabled]);

  async function confirm() {
    if (pending.current || disabled || loading || !verified || !entry || entry.status !== "draft" || entry.is_expired || !entry.confirmation_token || (entry.similar?.count && !separate)) return;
    pending.current = true; readVersion.current++;
    setBusy(true); setError("");
    try {
      const res = await apiFetch(`${path}/commit`, { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ confirmation_token: entry.confirmation_token, separate_transaction: separate }) });
      if (!res.ok) throw new Error(await parseError(res));
      const current: Entry = await res.json();
      if (current.id !== entryId || current.project_id !== projectId || current.status !== "committed") throw new Error("반영 결과를 확인하지 못했습니다.");
      if (alive.current) { setEntry(current); onCommitted(); }
    } catch (err) {
      // Reconcile an uncertain write before allowing a retry. The server
      // commits the same draft/token once, even across tabs or lost responses.
      const current = await read().catch(() => null);
      if (!alive.current) return;
      setSeparate(false); setVerified(!!current);
      if (current) setEntry(current);
      if (current?.status === "committed") { onCommitted(); return; }
      setError(current ? (err instanceof Error ? err.message : "반영하지 못했습니다.") : "반영 결과를 확인하지 못했습니다. 현재 상태를 다시 확인해주세요.");
    } finally { pending.current = false; if (alive.current) setBusy(false); }
  }

  const active = verified && entry?.status === "draft" && !entry.is_expired;
  return <section aria-label="현금 입력 반영 확인" className="space-y-3 rounded-xl border border-accent/30 bg-card p-3 text-sm">
    <div><h3 className="font-semibold">현금 입력 확인</h3><p className="mt-1 break-words text-xs text-muted-foreground">{storeName} · 현금 장부</p></div>
    {loading && <p role="status" className="flex items-center gap-2 text-xs text-muted-foreground"><Loader2 className="h-3.5 w-3.5 animate-spin" />현재 반영 상태 확인 중…</p>}
    {entry && <>
      <p className="text-xs text-muted-foreground">{entry.payload.occurred_on} · {entry.payload.kind === "refund" ? "현금 취소·환불 기록" : "현금 수납"}</p>
      <p className="break-all text-2xl font-semibold tabular-nums">{entry.payload.kind === "refund" ? "−" : ""}{amountText(entry.payload.amount)}원</p>
      <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-3 gap-y-1 text-xs leading-5"><dt className="text-muted-foreground">채널</dt><dd className="break-words">{entry.payload.channel || "미입력"}</dd><dt className="text-muted-foreground">메모</dt><dd className="whitespace-pre-wrap break-words">{entry.payload.memo || "미입력"}</dd>{entry.payload.original_event_id && <><dt className="text-muted-foreground">원거래</dt><dd className="break-all">{entry.payload.original_event_id}</dd></>}</dl>
      {verified && entry.status === "committed" && <p role="status" className="flex items-start gap-2 text-xs leading-5 text-success"><CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0" />반영 완료 · 대시보드에서 재계산하면 새 거래가 포함됩니다.</p>}
      {verified && (entry.status === "cancelled" || (entry.status === "draft" && entry.is_expired)) && <p role="status" className="text-xs text-muted-foreground">{entry.status === "cancelled" ? "취소된 초안입니다." : "24시간이 지나 만료된 초안입니다."} 새 초안을 요청해주세요.</p>}
      {active && <>
        {!!entry.similar?.count && <div className="space-y-2 rounded-lg border border-amber-500/50 p-3 text-xs leading-5">
          <p>같은 날짜·종류·금액의 현금 기록 {entry.similar.count}건이 있습니다.</p>
          <ul className="space-y-1">{entry.similar.entries.map(item => <li key={item.id} className="break-words">{item.payload.channel || "채널 미입력"} · {item.payload.memo || "메모 없음"}</li>)}</ul>
          <label className="flex items-start gap-2"><input type="checkbox" className="mt-1" checked={separate} disabled={busy || disabled} onChange={event => setSeparate(event.target.checked)} /><span>기존 기록을 확인했으며 별도 거래입니다.</span></label>
        </div>}
        <p className="text-xs leading-5 text-muted-foreground">위 내용을 확인하고 확정하면 현금 장부에 반영됩니다.{entry.payload.kind === "refund" && " 실제 환불은 실행하지 않습니다."}</p>
        <Button type="button" className="w-full" disabled={busy || disabled || loading || !entry.confirmation_token || (!!entry.similar?.count && !separate)} onClick={() => void confirm()}>{busy ? "반영 중…" : "반영 확정"}</Button>
      </>}
    </>}
    {error && <p role="alert" className="break-words text-xs leading-5 text-destructive">{error}</p>}
    {!verified && !loading && <Button type="button" size="sm" variant="outline" className="w-full" disabled={busy || disabled} onClick={() => setRetry(value => value + 1)}>현재 상태 다시 확인</Button>}
  </section>;
}
