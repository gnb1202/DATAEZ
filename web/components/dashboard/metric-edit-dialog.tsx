"use client";
import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { useDashboard } from "@/app/contexts/dashboard-context";
import { parseError } from "@/app/lib/api";

type Revision = { revision: number; title: string; definition: Record<string, unknown>; created_at: string; restored_from_revision?: number };
type History = { metric: { title: string; definition_revision: number; widget_data: { metric_definition: Record<string, unknown>; calculation_label?: string } }; revisions: Revision[]; total: number };

export function MetricEditDialog({ id, title, onChanged }: { id: string; title: string; onChanged: () => void }) {
  const { selectedProjectId, apiFetch } = useDashboard();
  const [open, setOpen] = useState(false);
  const [history, setHistory] = useState<History | null>(null);
  const [name, setName] = useState(title);
  const [definition, setDefinition] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [revision, setRevision] = useState(0);
  const loaded = useRef(false);
  const [editingRevision, setEditingRevision] = useState(1);
  const [page, setPage] = useState(0);
  const base = `/api/projects/${selectedProjectId}/metrics/${id}`;
  useEffect(() => {
    if (!open) return;
    let active = true;
    apiFetch(`${base}/history?limit=10&offset=${page * 10}`).then(async res => {
      if (!res.ok) throw new Error(await parseError(res));
      const value: History = await res.json();
      if (active) {
        setHistory(value);
        // Pagination must not discard unsaved edits.
        if (!loaded.current) { loaded.current = true; setEditingRevision(value.metric.definition_revision); setName(value.metric.title); setDefinition(JSON.stringify(value.metric.widget_data.metric_definition, null, 2)); }
      }
    }).catch(err => { if (active) setError(err.message); });
    return () => { active = false; };
  }, [open, apiFetch, base, page, revision]);
  async function apply(restore?: number) {
    if (!history) return;
    setBusy(true); setError(""); setNotice("");
    try {
      const payload = { expected_revision: restore ? history.metric.definition_revision : editingRevision, request_key: crypto.randomUUID(),
        ...(restore ? { revision: restore } : { title: name, definition: JSON.parse(definition) }) };
      const res = await apiFetch(base + (restore ? "/restore" : ""), { method: restore ? "POST" : "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
      if (!res.ok) throw new Error(await parseError(res));
      setNotice(restore ? "이전 정의로 복원하고 현재 데이터로 계산했습니다." : "지표를 수정했습니다. 배치와 갱신 주기는 유지됩니다.");
      loaded.current = false; setPage(0); setRevision(v => v + 1); onChanged();
    } catch (err) { setError(err instanceof Error ? err.message : "지표 변경에 실패했습니다."); }
    finally { setBusy(false); }
  }
  return <Dialog open={open} onOpenChange={value => { setOpen(value); if (value) { loaded.current = false; setError(""); setNotice(""); setPage(0); setHistory(null); setRevision(v => v + 1); } }}>
    <DialogTrigger asChild><Button variant="ghost" size="sm" aria-label={`${title} 수정·이력`}>수정·이력</Button></DialogTrigger>
    <DialogContent className="max-h-[85vh] overflow-y-auto sm:max-w-2xl"><DialogHeader><DialogTitle>지표 수정과 변경 이력</DialogTitle></DialogHeader>
      {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
      {notice && <p role="status" className="text-sm">{notice}</p>}
      {!history ? <p>지표를 불러오고 있습니다.</p> : <>
        <p className="text-sm">{history.metric.title} · 버전 {history.metric.definition_revision}</p>
        <p className="text-sm text-muted-foreground">{history.metric.widget_data.calculation_label}</p>
        <p className="text-sm">AI 분석에서 지표 이름과 바꿀 조건을 말하면 수정할 수 있습니다. 직접 정의를 편집하려면 아래 고급 편집을 사용하세요.</p>
        <details className="border rounded-lg p-3"><summary className="cursor-pointer text-sm font-medium">고급 정의 편집</summary>
          <form onSubmit={e => { e.preventDefault(); void apply(); }} className="space-y-3 mt-3">
            <label className="block text-sm">지표 제목<input aria-label="수정할 지표 제목" value={name} onChange={e => setName(e.target.value)} required maxLength={120} className="block w-full mt-1 p-2 border rounded bg-background" /></label>
            <label className="block text-sm">지표 정의 (JSON)<textarea aria-label="수정할 지표 정의" value={definition} onChange={e => setDefinition(e.target.value)} rows={14} className="block w-full mt-1 p-2 border rounded bg-background font-mono text-xs" /></label>
            <p className="text-xs text-muted-foreground">계산할 수 있는 정의만 저장합니다. 원본 장부의 거래는 바뀌지 않습니다.</p>
            <Button type="submit" disabled={busy}>{busy ? "처리 중…" : "변경 내용 저장·재계산"}</Button>
          </form>
        </details>
        <div className="flex items-center justify-between"><h4 className="font-medium">변경 이력</h4><Button variant="ghost" size="sm" disabled={busy} onClick={() => { loaded.current = false; setPage(0); setRevision(v => v + 1); setError(""); }}>최신 정의 다시 불러오기</Button></div>
        <ul className="divide-y">{history.revisions.map(item => <li key={item.revision} className="py-3 space-y-2">
          <div className="flex justify-between gap-2"><p className="text-sm">버전 {item.revision} · {item.title}<span className="block text-xs text-muted-foreground">{new Date(item.created_at).toLocaleString("ko-KR")}{item.restored_from_revision ? ` · 버전 ${item.restored_from_revision}에서 복원` : ""}</span></p>
            {item.revision !== history.metric.definition_revision && <Button size="sm" variant="outline" disabled={busy} aria-label={`버전 ${item.revision} 정의 복원`} onClick={() => apply(item.revision)}>이 정의로 복원</Button>}</div>
          <details><summary className="text-xs cursor-pointer">정의 보기</summary><pre className="mt-2 text-xs overflow-auto p-2 rounded bg-secondary/30">{JSON.stringify(item.definition, null, 2)}</pre></details>
        </li>)}</ul>
        {history.total > 10 && <div className="flex justify-end gap-3 items-center text-sm"><Button size="sm" variant="outline" disabled={page===0 || busy} onClick={() => setPage(v => v-1)}>이전 이력</Button>{page+1} / {Math.ceil(history.total/10)}<Button size="sm" variant="outline" disabled={(page+1)*10>=history.total || busy} onClick={() => setPage(v => v+1)}>다음 이력</Button></div>}
        <p className="text-xs text-muted-foreground">복원은 선택한 정의로 현재 원본을 다시 계산하며 새 버전으로 기록합니다. 과거 계산 결과와 값이 다를 수 있습니다.</p>
      </>}
    </DialogContent>
  </Dialog>;
}
