"use client";

import { useEffect, useState } from "react";
import { parseError } from "../lib/api";

export type QualityFetch = (path: string, init?: RequestInit) => Promise<Response>;
const reasons = [["intent", "질문 의도"], ["calculation", "계산 결과"], ["chart", "그래프"], ["scope", "자료 범위"], ["incomplete", "답변 미완료"], ["other", "기타"]];

export function AnswerFeedback({ messageId, apiFetch }: { messageId: string; apiFetch: QualityFetch }) {
  const [rating, setRating] = useState<number | null>(null);
  const [reason, setReason] = useState("");
  const [comment, setComment] = useState("");
  const [editing, setEditing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const [ready, setReady] = useState(false);
  useEffect(() => {
    let alive = true;
    apiFetch(`/api/quality/messages/${messageId}/feedback`).then(async res => {
      if (!res.ok) throw new Error(await parseError(res));
      const { feedback } = await res.json();
      if (alive) { setRating(feedback?.rating ?? null); setReason(feedback?.reason || ""); setComment(feedback?.comment || ""); setReady(true); }
    }).catch(() => { if (alive) setNotice("평가를 불러오지 못했습니다. 대화를 다시 열어주세요."); });
    return () => { alive = false; };
  }, [messageId, apiFetch]);
  async function save(value: number) {
    setBusy(true); setNotice("");
    try {
      const res = await apiFetch(`/api/quality/messages/${messageId}/feedback`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ rating: value, reason: value === 1 ? "" : reason, comment: value === 1 ? "" : comment }) });
      if (!res.ok) throw new Error(await parseError(res));
      setRating(value); setEditing(false); setNotice("평가를 저장했습니다.");
    } catch (err) { setNotice(err instanceof Error ? err.message : "저장하지 못했습니다. 다시 시도해주세요."); }
    finally { setBusy(false); }
  }
  return <div className="space-y-2 border-t border-border pt-3 text-xs">
    <div className="flex flex-wrap items-center gap-3"><span className="text-muted-foreground">도움이 되었나요?</span>
      <button disabled={!ready || busy} aria-pressed={rating === 1} className="rounded border border-border px-2 py-1 hover:bg-secondary aria-pressed:border-accent aria-pressed:bg-[var(--accent-surface)] aria-pressed:text-[var(--accent-text)] disabled:opacity-50" onClick={() => void save(1)}>👍 좋아요</button>
      <button disabled={!ready || busy} aria-pressed={rating === -1} className="rounded border border-border px-2 py-1 hover:bg-secondary aria-pressed:border-accent aria-pressed:bg-[var(--accent-surface)] aria-pressed:text-[var(--accent-text)] disabled:opacity-50" onClick={() => setEditing(!editing)}>👎 아쉬워요</button>
    </div>
    {editing && <form className="space-y-2" onSubmit={e => { e.preventDefault(); void save(-1); }}>
      <label className="block">어떤 부분이 아쉬웠나요?<select className="mt-1 block w-full rounded border border-border bg-background p-2" value={reason} onChange={e => setReason(e.target.value)}><option value="">선택 안 함</option>{reasons.map(([v, label]) => <option key={v} value={v}>{label}</option>)}</select></label>
      <label className="block">의견 (선택)<textarea maxLength={1000} value={comment} onChange={e => setComment(e.target.value)} className="mt-1 block w-full rounded border border-border bg-background p-2" placeholder="개인정보나 계좌번호는 적지 마세요." /></label>
      <button disabled={busy} className="rounded bg-primary px-3 py-2 text-primary-foreground transition-colors hover:bg-[var(--action-hover)] disabled:opacity-50">{busy ? "저장 중…" : "평가 저장"}</button>
    </form>}
    <p role="status" className="text-muted-foreground">{notice}</p>
  </div>;
}
