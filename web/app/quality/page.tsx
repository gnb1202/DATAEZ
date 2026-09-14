"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { useAuth } from "../hooks/use-auth";
import { parseError, type ChartData } from "../lib/api";
import { EChartsChart } from "@/components/dashboard/echarts-chart";

type Run = { id: string; user_id: string; question: string | null; status: string; observed_status?: string; started_at: string; duration_ms: number | null; error_code: string | null; version: Record<string, unknown>; review: { verdict: string; category: string; note: string } | null; rating: number | null; answer?: string; references?: unknown; steps?: unknown; charts?: ChartData[]; table_data?: unknown; usage?: unknown; feedback_reason?: string; feedback_comment?: string; candidate?: {question: string; expected_behavior: string} };
const statuses = [["all", "모든 실행"], ["failed", "실행 실패"], ["cancelled", "중단"], ["unconfirmed", "완료 여부 미확인"], ["negative", "부정 평가"], ["unreviewed", "미검토"], ["completed", "응답 완료"]];
const categories = [["", "분류 선택"], ["intent", "의도 이해"], ["calculation", "계산"], ["chart", "그래프"], ["scope", "분석 범위"], ["incomplete", "미완료"], ["other", "기타"]];
const control = "rounded border border-border bg-background px-3 py-2 text-sm disabled:opacity-50";

const primaryAction = "rounded border border-primary bg-primary px-3 py-2 text-sm font-medium text-primary-foreground transition-colors hover:bg-[var(--action-hover)] disabled:opacity-50";

export default function QualityPage() {
  const { isAuthenticated, initializing, apiFetchWithRefresh: apiFetch } = useAuth();
  const [allowed, setAllowed] = useState(false);
  const [status, setStatus] = useState("all");
  const [owner, setOwner] = useState("");
  const [ownerFilter, setOwnerFilter] = useState("");
  const [offset, setOffset] = useState(0);
  const [runs, setRuns] = useState<Run[]>([]);
  const [total, setTotal] = useState(0);
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [selected, setSelected] = useState<Run | null>(null);
  const [verdict, setVerdict] = useState("needs_review");
  const [category, setCategory] = useState("");
  const [note, setNote] = useState("");
  const [question, setQuestion] = useState("");
  const [expected, setExpected] = useState("");
  const [synthetic, setSynthetic] = useState(false);
  const request = useCallback(async (path: string, init?: RequestInit) => {
    const res = await apiFetch(path, { ...init, cache: "no-store" });
    if (!res.ok) throw new Error(await parseError(res));
    return res.json();
  }, [apiFetch]);
  useEffect(() => {
    let alive = true;
    if (isAuthenticated) request("/api/quality/access").then(data => { if (alive) { setAllowed(data.admin); if (!data.admin) setNotice("관리자로 지정된 계정만 열 수 있습니다."); } }).catch(e => { if (alive) setNotice(e.message); });
    return () => { alive = false; };
  }, [isAuthenticated, request]);
  const load = useCallback(async () => {
    const data = await request(`/api/quality/runs?status=${status}&limit=30&offset=${offset}${ownerFilter ? `&user_id=${encodeURIComponent(ownerFilter)}` : ""}`);
    setRuns(data.runs); setTotal(data.total);
  }, [request, status, offset, ownerFilter]);
  useEffect(() => {
    let alive = true;
    if (allowed && isAuthenticated) request(`/api/quality/runs?status=${status}&limit=30&offset=${offset}${ownerFilter ? `&user_id=${encodeURIComponent(ownerFilter)}` : ""}`).then(data => { if (alive) { setRuns(data.runs); setTotal(data.total); } }).catch(e => { if (alive) setNotice(e.message); });
    return () => { alive = false; };
  }, [allowed, isAuthenticated, request, status, offset, ownerFilter]);
  async function action(fn: () => Promise<void>) {
    setBusy(true); setNotice("");
    try { await fn(); } catch (e) { setNotice(e instanceof Error ? e.message : "요청에 실패했습니다."); }
    finally { setBusy(false); }
  }
  async function open(id: string) {
    const data = await request(`/api/quality/runs/${id}`);
    setSelected(data); setVerdict(data.review?.verdict || "needs_review"); setCategory(data.review?.category || ""); setNote(data.review?.note || "");
    setQuestion(data.candidate?.question || ""); setExpected(data.candidate?.expected_behavior || ""); setSynthetic(false);
  }
  const put = (path: string, body: unknown) => request(path, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  return <main className="min-h-screen bg-background p-5 text-foreground md:p-10">
    <div className="mx-auto max-w-7xl space-y-6"><Link href="/" className="text-sm text-accent">← DATA:EZ로 돌아가기</Link>
      <header><p className="text-xs text-muted-foreground">관리자 전용 · 대화 품질</p><h1 className="mt-2 text-3xl font-semibold">질문에서 결과까지</h1><p className="mt-2 text-sm text-muted-foreground">응답 완료는 정답 판정이 아닙니다. 파일 범위, 도구와 수치를 검토해주세요.</p></header>
      <p role="status">{notice}</p>
      {initializing ? <p>계정을 확인하는 중…</p> : !isAuthenticated ? <p>먼저 <Link href="/" className="text-accent underline">로그인</Link>해주세요.</p> : allowed && <>
        <div className="flex flex-wrap gap-3"><label>검사 대상 <select className={control} value={status} onChange={e => { setStatus(e.target.value); setOffset(0); }}>{statuses.map(([v,l]) => <option key={v} value={v}>{l}</option>)}</select></label>
          <form className="flex flex-wrap gap-2" onSubmit={e => { e.preventDefault(); setOwnerFilter(owner); setOffset(0); }}><input className={control} aria-label="사용자 ID" placeholder="사용자 UUID (선택)" value={owner} onChange={e => setOwner(e.target.value)} /><button className={control}>사용자 필터</button></form>
          <button disabled={busy} className={control} onClick={() => void action(load)}>새로고침</button></div>
        <div className="grid min-w-0 gap-6 lg:grid-cols-[340px_minmax(0,1fr)]">
          <section className="min-w-0 space-y-2" aria-label="실행 목록"><p className="text-sm text-muted-foreground">{total}건 · {offset + 1}부터</p>
            {runs.map(run => <button key={run.id} disabled={busy} className={`block w-full rounded-xl border p-4 text-left ${selected?.id === run.id ? "border-accent/60 bg-[var(--accent-surface)]" : "border-border bg-card hover:bg-secondary"}`} onClick={() => void action(() => open(run.id))}>
              <span className="block text-xs text-muted-foreground">{run.status} {run.rating === -1 ? "· 👎" : ""} · {new Date(run.started_at).toLocaleString()}</span>
              <span className="mt-2 block break-words text-sm">{run.question || "질문 저장 전 종료"}</span><span className="mt-2 block text-xs text-muted-foreground">{run.duration_ms == null ? "소요 시간 미확인" : `${(run.duration_ms / 1000).toFixed(1)}초`} · {run.review?.verdict || "미검토"}</span></button>)}
            {!runs.length && <p className="rounded border border-border p-5">조건에 맞는 실행 기록이 없습니다. 새 기록은 관측 기능 적용 이후 생성됩니다.</p>}
            <div className="flex gap-2"><button className={control} disabled={offset === 0 || busy} onClick={() => setOffset(Math.max(0,offset-30))}>이전</button><button className={control} disabled={offset+30 >= total || busy} onClick={() => setOffset(offset+30)}>다음</button></div>
          </section>
          <section className="min-w-0 space-y-5" aria-label="실행 검토">{selected ? <>
            <div className="rounded-xl border border-border bg-card p-5"><h2 className="font-semibold">질문과 답변</h2><p className="mt-2 break-all text-xs text-muted-foreground">실행 {selected.id} · 사용자 {selected.user_id} · {selected.observed_status}</p><p className="mt-4 whitespace-pre-wrap break-words">{selected.question || "저장된 질문 없음"}</p><hr className="my-4 border-border" /><p className="whitespace-pre-wrap break-words">{selected.answer || "저장된 최종 답변 없음"}</p>{selected.error_code && <p className="mt-3">오류: {selected.error_code}</p>}
              {selected.rating && <p className="mt-4 whitespace-pre-wrap break-words">사용자 평가: {selected.rating === 1 ? "좋아요" : "아쉬워요"} · {selected.feedback_reason} {selected.feedback_comment}</p>}</div>
            {selected.charts?.map((chart,i) => <EChartsChart key={i} chartType={chart.chart_type as "line"|"bar"|"pie"} title={chart.title} xKey={chart.x_key} yKey={chart.y_key} data={chart.data} unit={chart.unit} height={260} />)}
            {[["모델·프롬프트 버전",selected.version],["선택 자료", selected.references],["도구 호출·SQL (긴 출력은 잘릴 수 있음)",selected.steps],["집계표",selected.table_data],["호출별 사용량·시간",selected.usage]].map(([label,data]) => <details key={String(label)} className="rounded border border-border bg-card p-3"><summary className="cursor-pointer">{String(label)}</summary><pre className="mt-3 max-h-96 overflow-auto text-xs">{JSON.stringify(data ?? null,null,2)}</pre></details>)}
            <form className="space-y-3 rounded-xl border border-border bg-card p-5" onSubmit={e => { e.preventDefault(); void action(async () => { await put(`/api/quality/runs/${selected.id}/review`, {verdict,category,note}); setSelected({...selected,review:{verdict,category,note}}); await load(); setNotice("검토를 저장했습니다."); }); }}>
              <h2 className="font-semibold">검토 판정</h2><div className="flex flex-wrap gap-2"><select aria-label="검토 판정" className={control} value={verdict} onChange={e => setVerdict(e.target.value)}><option value="needs_review">추가 검토</option><option value="pass">통과</option><option value="fail">실패</option></select><select aria-label="문제 분류" className={control} value={category} onChange={e => setCategory(e.target.value)}>{categories.map(([v,l])=><option key={v} value={v}>{l}</option>)}</select></div>
              <textarea aria-label="검토 근거" className={`${control} w-full`} maxLength={2000} value={note} onChange={e => setNote(e.target.value)} placeholder="정답 수치와 관측값, 실패 원인을 적어주세요." /><button disabled={busy} className={primaryAction}>검토 저장</button>
            </form>
            {selected.review?.verdict === "fail" && <form className="space-y-3 rounded-xl border border-border bg-card p-5" onSubmit={e => { e.preventDefault(); void action(async () => { await put(`/api/quality/runs/${selected.id}/candidate`, {question,expected_behavior:expected,synthetic_confirmed:synthetic}); setSelected({...selected,candidate:{question,expected_behavior:expected}}); setNotice("합성 회귀 후보를 저장했습니다. 테스트 편입 전 데이터와 정답 정의가 필요합니다."); }); }}>
              <h2 className="font-semibold">합성 회귀 질문 후보</h2><p className="text-xs text-muted-foreground">원본 대화를 복사하지 않습니다. 실제 이름·파일명·매출액을 합성 사례로 바꾸세요.</p>
              <label className="block text-sm">합성 질문<textarea required minLength={5} maxLength={2000} className={`${control} mt-1 w-full`} value={question} onChange={e => setQuestion(e.target.value)} /></label>
              <label className="block text-sm">기대 동작<textarea required minLength={5} maxLength={3000} className={`${control} mt-1 w-full`} value={expected} onChange={e => setExpected(e.target.value)} /></label>
              <label className="flex gap-2 text-sm"><input type="checkbox" required checked={synthetic} onChange={e => setSynthetic(e.target.checked)} />개인정보·실제 매출 자료를 제거한 합성 사례입니다.</label><button disabled={busy} className={primaryAction}>후보 저장</button>
              {selected.candidate && <button type="button" disabled={busy} className={`${control} ml-2`} onClick={() => void action(async () => { const data = await request(`/api/quality/runs/${selected.id}/candidate`); const url = URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:"application/json"})); const a=document.createElement("a"); a.href=url; a.download="regression-candidate.json"; a.click(); setTimeout(()=>URL.revokeObjectURL(url),1000); setNotice("저장된 합성 후보를 내보냈습니다."); })}>저장된 후보 JSON 내보내기</button>}
            </form>}
          </> : <p className="rounded-xl border border-dashed border-border p-8 text-muted-foreground">왼쪽에서 검토할 실행을 선택하세요.</p>}</section>
        </div>
      </>}
    </div>
  </main>;
}
