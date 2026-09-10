"use client";

import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogTitle, DialogDescription } from "@/components/ui/dialog";
import { useDashboard } from "@/app/contexts/dashboard-context";
import { parseError, type Project } from "@/app/lib/api";
import type { LibraryFile } from "@/app/lib/file-library";

export type SampleReady = (project: Project, file: LibraryFile, view?: "analysis" | "dashboard") => void;

export function SampleWorkspaceActions({onSampleReady, onOpenLibrary, compact = false}: {onSampleReady: SampleReady; onOpenLibrary: () => void; compact?: boolean}) {
  const {apiFetch, selectedProjectId} = useDashboard();
  const [current, setCurrent] = useState<Project | null>(null);
  const [busy, setBusy] = useState(false), [error, setError] = useState("");
  const [target, setTarget] = useState<{project: Project; requestId: string} | null>(null);
  const pending = useRef(false);
  const mounted = useRef(true);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  useEffect(() => {
    let active = true;
    apiFetch("/api/library/files/sample-workspace").then(async response => {
      if (!response.ok) throw new Error(await parseError(response));
      const data = await response.json(); if (active) setCurrent(data.project);
    }).catch(() => { /* Starting a sample retries the same authenticated lookup. */ });
    return () => { active = false; };
  }, [apiFetch]);

  async function perform(mode: "analysis" | "dashboard" | "restart") {
    if (pending.current) return;
    pending.current = true; setBusy(true); setError("");
    try {
      const post = async (path: string, body?: object) => {
        const response = await apiFetch(`/api/library/files/sample-workspace${path}`, {
          method: "POST", headers: {"Content-Type":"application/json"}, body: body ? JSON.stringify(body) : undefined,
        });
        if (!response.ok) throw new Error(await parseError(response));
        return response.json();
      };
      let data;
      if (mode === "restart") {
        if (!target) return;
        data = await post("/restart", {expected_project_id: target.project.id, request_id: target.requestId});
      } else {
        data = await post("");
        if (mode === "dashboard") data = await post("/dashboard", {project_id: data.project.id});
      }
      if (!mounted.current) return;
      setCurrent(data.project); setTarget(null);
      onSampleReady(data.project, data.file, mode === "dashboard" ? "dashboard" : "analysis");
    } catch (e) {
      if (mounted.current) setError(e instanceof Error ? e.message : "샘플을 준비하지 못했습니다.");
    } finally {
      pending.current = false; if (mounted.current) setBusy(false);
    }
  }

  return <div className="space-y-3 rounded-lg bg-secondary p-4">
    <p className="text-sm font-medium">{compact ? "다음 분석을 시작하세요" : "파일이 없어도 먼저 경험해보세요"}</p>
    {!compact && <p className="text-xs leading-5 text-muted-foreground">가상 카드·현금·취소 거래 8행, 합계 690,200원입니다. 샘플을 준비하면 원본 파일과 질문 초안을 확인한 뒤 직접 전송할 수 있습니다.</p>}
    <div className="flex flex-wrap gap-2">
      <Button disabled={busy} onClick={() => void perform("analysis")}>샘플 데이터로 시작</Button>
      <Button variant="outline" disabled={busy} onClick={() => void perform("dashboard")}>예시 대시보드 보기</Button>
      {!!selectedProjectId && <Button variant="outline" disabled={busy} onClick={onOpenLibrary}>내 파일로 시작</Button>}
    </div>
    <p className="text-[11px] leading-5 text-muted-foreground">예시 대시보드는 원본 전체 기간의 합계·일별·결제수단별 지표 3개를 미리 정의해 저장합니다. AI 생성 결과가 아니며, 버튼을 다시 눌러도 중복 저장하지 않습니다.</p>
    {current && <Button variant="ghost" className="h-auto px-0 text-xs" disabled={busy} onClick={() => {setError(""); setTarget({project: current, requestId: crypto.randomUUID()});}}>샘플 체험 다시 시작</Button>}
    {busy && <p role="status" className="text-xs">샘플을 준비하고 있습니다…</p>}
    {error && !target && <p role="alert" className="text-sm text-destructive">{error}</p>}
    <Dialog open={!!target} onOpenChange={open => {if (!open && !busy) setTarget(null);}}>
      <DialogContent>
        <DialogTitle>새 샘플 가게에서 체험하기</DialogTitle>
        <DialogDescription>현재 샘플: {target?.project.name}. 새 샘플 가게와 원본 파일을 준비합니다. 이전 샘플의 파일·대화·대시보드는 그대로 보관하며, 일반 가게와 다른 계정의 자료도 유지합니다.</DialogDescription>
        <p className="text-sm text-muted-foreground">같은 체험을 이어가려면 취소 후 ‘샘플 데이터로 시작’을 누르세요.</p>
        {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
        <div className="flex justify-end gap-2"><Button variant="outline" disabled={busy} onClick={() => setTarget(null)}>취소</Button><Button disabled={busy} onClick={() => void perform("restart")}>{busy ? "준비 중…" : "새 샘플 만들기"}</Button></div>
      </DialogContent>
    </Dialog>
  </div>;
}
