"use client";

import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { parseError } from "@/app/lib/api";
import type { ImportBatch } from "./ledger-import-panel";

type Event = { event_id: string | null; original_event_id: string | null; event_kind: string; amount: string; occurred_at: string; currency: string;
  payment_method?: string; channel?: string; fee?: string };
const attributes = (event: Event) => `결제수단 ${event.payment_method ?? "미제공"} · 채널 ${event.channel ?? "미제공"} · 수수료 ${event.fee == null ? "미제공" : `${event.fee}원`}`;
type ReviewRow = {
  row_number: number; normalized: Event; classification: string; reason: string; decision: string | null;
  target_row_id: number | null;
  matched?: { batch_id: string | null; filename: string; row_number: number; target_row_id: number | null; normalized: Event };
};
const labels: Record<string, string> = { new: "신규", duplicate: "중복 제외", candidate: "확인 필요", conflict: "내용 충돌" };

export function EventReviewPanel({ base, batch, apiFetch, busy, run, onBatch }: {
  base: string; batch: ImportBatch; apiFetch: (path: string, init?: RequestInit) => Promise<Response>;
  busy: boolean; run: (action: () => Promise<void>) => Promise<void>; onBatch: (batch: ImportBatch) => void;
}) {
  const [filter, setFilter] = useState("");
  const [page, setPage] = useState(0);
  const [rows, setRows] = useState<ReviewRow[]>([]);
  const [total, setTotal] = useState(0);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const alive = useRef(true);
  useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);
  useEffect(() => {
    let cancelled = false;
    setLoading(true); setError(""); setRows([]);
    apiFetch(`${base}/imports/${batch.id}/rows?limit=20&offset=${page * 20}${filter ? `&classification=${filter}` : ""}`).then(async (res) => {
      if (!res.ok) throw new Error(await parseError(res));
      const data = await res.json();
      if (!cancelled) { setRows(data.rows); setTotal(data.total); }
    }).catch((e: Error) => { if (!cancelled) setError(e.message); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [base, batch.id, batch.preview_token, batch.status, filter, page, apiFetch]);

  const decide = (row: ReviewRow, decision: string) => run(async () => {
    const res = await apiFetch(`${base}/imports/${batch.id}/decisions`, { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ preview_token: batch.preview_token, decisions: [{ row_number: row.row_number, decision }] }) });
    if (!res.ok) throw new Error(await parseError(res));
    const data = await res.json();
    if (alive.current) onBatch(data);
  });
  return <div aria-label="거래별 검토" className="space-y-3">
    <div className="flex flex-wrap items-center justify-between gap-2"><h5 className="text-sm font-semibold">거래별 판정과 원본</h5>
      <label className="text-sm">판정 보기 <select className="rounded border border-border bg-background px-2 py-1" value={filter} disabled={busy} onChange={(e) => { setFilter(e.target.value); setPage(0); }}>
        <option value="">전체</option>{Object.entries(labels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
      </select></label></div>
    {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
    {loading ? <p className="text-sm text-muted-foreground">거래를 불러오는 중…</p> : <div className="overflow-x-auto"><table className="w-full min-w-[660px] text-left text-sm">
      <thead className="text-muted-foreground"><tr><th className="py-2">원본 행 / ID</th><th>금액 / 일시</th><th className="w-1/2">판정 이유와 비교 대상</th><th>처리</th></tr></thead>
      <tbody>{rows.map((row) => <tr key={row.row_number} className="border-t border-border align-top">
        <td className="py-3 pr-3">{row.row_number}행<div className="max-w-40 break-all text-muted-foreground">{row.normalized.event_id ?? "ID 없음"}</div></td>
        <td className="py-3 pr-3 tabular-nums">{row.normalized.amount}원<div className="text-xs text-muted-foreground">{new Date(row.normalized.occurred_at).toLocaleString("ko-KR", { timeZone: "Asia/Seoul" })}</div><p className="mt-1 text-xs text-muted-foreground">{attributes(row.normalized)}</p></td>
        <td className="py-3 pr-3"><span className={row.classification === "conflict" ? "font-semibold text-destructive" : "font-medium"}>{labels[row.classification]}</span><p className="mt-1 text-xs text-muted-foreground">{row.reason}</p>
          {row.matched && <details className="mt-2 text-xs"><summary className="cursor-pointer">{row.matched.filename} · {row.matched.row_number}행 비교</summary>
            <p className="mt-1 break-all text-muted-foreground">기존 금액 {row.matched.normalized.amount}원 · {row.matched.normalized.occurred_at} · 원거래 {row.matched.normalized.original_event_id ?? "없음"}</p>
            <p className="mt-1 text-muted-foreground">{attributes(row.matched.normalized)}</p></details>}
          {row.target_row_id != null && <p className="mt-1 text-xs text-muted-foreground">장부 행 {row.target_row_id}</p>}
        </td>
        <td className="py-3">{row.classification === "candidate" && batch.status !== "committed" ? <select aria-label={`${row.row_number}행 처리`} className="rounded border border-border bg-background p-1" disabled={busy || loading || batch.status !== "ready"} value={row.decision || ""} onChange={(e) => { if (e.target.value) void decide(row, e.target.value); }}>
          <option value="">선택 필요</option><option value="include">별개 거래로 포함</option><option value="exclude">중복으로 제외</option>
        </select> : <span className="text-xs">{row.decision === "exclude" ? "사용자 제외" : row.decision === "include" ? "사용자 포함" : labels[row.classification]}</span>}</td>
      </tr>)}</tbody></table>{rows.length === 0 && <p className="py-4 text-sm text-muted-foreground">이 판정에 해당하는 거래가 없습니다.</p>}</div>}
    {total > 20 && <div className="flex items-center gap-3"><Button size="sm" variant="outline" disabled={busy || loading || page === 0} onClick={() => setPage((v) => v - 1)}>이전 거래</Button><span className="text-xs">{page + 1} / {Math.ceil(total / 20)}</span><Button size="sm" variant="outline" disabled={busy || loading || (page + 1) * 20 >= total} onClick={() => setPage((v) => v + 1)}>다음 거래</Button></div>}
  </div>;
}
