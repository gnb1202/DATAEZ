"use client";

import { uploadSourceForm } from "@/app/lib/direct-upload";

import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { useDashboard } from "@/app/contexts/dashboard-context";

type Job = {
  id: string; name: string; table_meta_id: string | null; file_id: string | null;
  status: "pending" | "processing" | "retry" | "succeeded" | "failed" | "cancelled";
  attempts: number; next_attempt_at: string; last_error: string | null; last_success_at: string | null;
};
type Health = { jobs: Job[]; counts: Record<string, number>; total: number; search_enabled: boolean; worker_enabled: boolean; max_attempts: number };
const labels = { pending: "갱신 대기", processing: "갱신 중", retry: "자동 재시도 대기", succeeded: "검색 준비 완료", failed: "확인 필요", cancelled: "처리 중단" };
const when = (value: string) => new Date(value).toLocaleString("ko-KR");

export function SearchIndexPanel() {
  const { selectedProjectId: projectId, apiFetch } = useDashboard();
  const [health, setHealth] = useState<Health | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState("");
  const [page, setPage] = useState(0);
  const [revision, setRevision] = useState(0);
  const fileInput = useRef<HTMLInputElement>(null);
  const base = `/api/projects/${projectId}/search-index`;
  const pageSize = 10;

  useEffect(() => {
    let active = true;
    let timer: ReturnType<typeof setTimeout>;
    async function refresh() {
      if (document.visibilityState === "visible") {
        try {
          const response = await apiFetch(`${base}?limit=${pageSize}&offset=${page * pageSize}`);
          if (!response.ok) throw new Error("검색 갱신 상태를 읽지 못했습니다. 잠시 후 다시 시도해 주세요.");
          const next: Health = await response.json();
          if (active) {
            setHealth(next); setError("");
            if (page > 0 && page * pageSize >= next.total) setPage(Math.max(0, Math.ceil(next.total / pageSize) - 1));
          }
        } catch (err) { if (active) setError(err instanceof Error ? err.message : "상태를 읽지 못했습니다."); }
      }
      if (active) timer = setTimeout(refresh, 5000);
    }
    void refresh();
    return () => { active = false; clearTimeout(timer); };
  }, [apiFetch, base, page, revision]);

  async function action(key: string, url: string, init: RequestInit, success: string) {
    setBusy(key); setNotice("");
    try {
      const response = await apiFetch(url, init);
      const data = await response.json();
      if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "요청을 처리하지 못했습니다.");
      setNotice(success); setRevision(v => v + 1);
      return true;
    } catch (err) { setNotice(err instanceof Error ? err.message : "요청에 실패했습니다."); return false; }
    finally { setBusy(""); }
  }

  async function upload(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const file = fileInput.current?.files?.[0];
    if (!file) return;
    setBusy("upload"); setNotice("");
    let body: FormData;
    try { body = await uploadSourceForm(apiFetch, file, projectId!); }
    catch (err) { setNotice(err instanceof Error ? err.message : "업로드에 실패했습니다."); setBusy(""); return; }
    if (await action("upload", `/api/projects/${projectId}/documents`, { method: "POST", body }, "문서를 저장했습니다. 검색 준비는 자동으로 진행됩니다.")) {
      if (fileInput.current) fileInput.current.value = "";
      setPage(0);
    }
  }

  return <section aria-label="검색 갱신 상태" className="rounded-xl border border-border bg-card p-5 space-y-4">
    <div className="flex flex-wrap items-center justify-between gap-3">
      <div><h3 className="font-semibold">검색 갱신 상태</h3><p className="text-sm text-muted-foreground mt-1">장부 변경과 참고 문서를 대화에서 찾을 수 있도록 자동으로 갱신합니다.</p></div>
      <Button variant="outline" size="sm" onClick={() => setRevision(v => v + 1)}>상태 새로고침</Button>
    </div>
    {health && <p className="text-sm">준비 완료 {health.counts.succeeded || 0}개 · 대기·처리 중 {(health.counts.pending || 0) + (health.counts.processing || 0) + (health.counts.retry || 0)}개 · 확인 필요 {health.counts.failed || 0}개</p>}
    {health && !health.worker_enabled && <p role="status" className="text-sm text-amber-700 dark:text-amber-300">{health.search_enabled ? "자동 갱신이 일시 중지되어 있습니다. 서버에서 갱신 작업을 켜면 대기 중인 자료를 처리합니다." : "의미 검색이 꺼져 있습니다. 자료는 저장되며, 검색을 켜면 대기 중인 자료를 처리합니다."}</p>}
    {error && <p role="alert" className="text-sm text-destructive">{error} {health ? "아래는 마지막으로 확인한 상태입니다." : ""}</p>}
    {notice && <p role="status" className="text-sm">{notice}</p>}
    <form aria-label="검색 참고 문서 업로드" onSubmit={upload} className="flex flex-wrap items-end gap-3 rounded-lg bg-secondary/30 p-3">
      <label className="text-sm flex-1 min-w-48">참고 문서 (PDF·MD·TXT)<input aria-label="검색 참고 문서" ref={fileInput} type="file" accept=".pdf,.md,.txt" required disabled={!!busy} className="block mt-2 w-full text-sm" /></label>
      <Button type="submit" variant="outline" size="sm" disabled={!!busy}>{busy === "upload" ? "저장 중…" : "문서 올리기"}</Button>
      <p className="w-full text-xs text-muted-foreground">환불 규정·정산 안내처럼 대화에서 참고할 문서를 올려 주세요. 결제 CSV·엑셀은 위의 출처별 파일 반영에서 올립니다.</p>
    </form>
    {!health && !error && <p className="text-sm text-muted-foreground">상태를 확인하고 있습니다…</p>}
    {health?.total === 0 && <p className="text-sm text-muted-foreground">아직 검색할 자료가 없습니다. 장부나 참고 문서를 등록하면 여기에 표시됩니다.</p>}
    <ul className="divide-y divide-border">
      {health?.jobs.map(job => <li key={job.id} className="py-3 flex flex-wrap justify-between gap-3" aria-label={job.name}>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2"><span className="text-xs text-muted-foreground">{job.file_id ? "문서" : "장부"}</span><span className="font-medium text-sm break-all">{job.name}</span><span className={job.status === "failed" ? "text-sm text-destructive" : "text-sm text-muted-foreground"}>{labels[job.status]}</span></div>
          {job.status === "retry" && <p className="text-xs text-muted-foreground mt-1">{job.attempts}/{health.max_attempts}회 시도 · 다음 시도 {when(job.next_attempt_at)}</p>}
          {job.status === "failed" && <p className="text-xs mt-1">검색 준비를 완료하지 못했습니다. 원인을 확인한 뒤 다시 시도해 주세요.</p>}
          {job.last_error && <p className="text-sm mt-1">{job.last_error}</p>}
          {job.last_success_at && <p className="text-xs text-muted-foreground mt-1">최근 완료 {when(job.last_success_at)}{job.status !== "succeeded" ? " · 이전 검색 내용은 유지됩니다." : ""}</p>}
        </div>
        <div className="flex gap-2 items-start">
          {(job.status === "failed" || job.status === "succeeded") && <Button size="sm" variant="outline" disabled={!!busy} onClick={() => action(job.id, `${base}/${job.id}/retry`, { method: "POST" }, "검색 갱신을 요청했습니다.")}>{busy === job.id ? "요청 중…" : job.status === "failed" ? "다시 시도" : "검색 다시 갱신"}</Button>}
          {job.file_id && <Button size="sm" variant="ghost" disabled={!!busy} aria-label={`${job.name} 문서 삭제`} onClick={() => { if (window.confirm(`${job.name} 문서를 검색 자료에서 삭제할까요?`)) void action(`delete-${job.id}`, `/api/projects/${projectId}/documents/${job.file_id}`, { method: "DELETE" }, "문서를 삭제했습니다."); }}>삭제</Button>}
        </div>
      </li>)}
    </ul>
    {health && health.total > pageSize && <div className="flex items-center justify-end gap-3 text-sm">
      <Button size="sm" variant="outline" disabled={page === 0} onClick={() => setPage(v => v - 1)}>이전 검색 자료</Button><span>{page + 1} / {Math.ceil(health.total / pageSize)}</span><Button size="sm" variant="outline" disabled={(page + 1) * pageSize >= health.total} onClick={() => setPage(v => v + 1)}>다음 검색 자료</Button>
    </div>}
  </section>;
}
