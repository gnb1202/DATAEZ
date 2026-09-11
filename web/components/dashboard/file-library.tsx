"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Archive, Download, FileSpreadsheet, FileText, Search, Upload, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useDashboard } from "@/app/contexts/dashboard-context";
import { parseError } from "@/app/lib/api";
import { uploadLibraryFile, downloadLibraryFile } from "@/app/lib/direct-upload";
import { referenceScope, referenceKey, type LibraryFile, type LibraryReference } from "@/app/lib/file-library";

const statusLabels: Record<string, string> = { stored: "보관 중", linked: "분석 가능", document_ready: "검색 가능", index_pending: "문서 준비 중", index_failed: "문서 준비 실패" };
type Preview = { columns?: { name: string; type?: string }[]; rows?: Record<string, unknown>[]; row_count?: number; text?: string; file?: LibraryFile };

export function FileLibrary({ initial = [], initialSearch = "", onSelect, onPrepared, picker = false, disabled = false }: {
  initial?: LibraryReference[]; initialSearch?: string; onSelect: (files: LibraryReference[]) => void;
  onPrepared?: () => void; picker?: boolean; disabled?: boolean;
}) {
  const { apiFetch, selectedProjectId } = useDashboard();
  const [files, setFiles] = useState<LibraryFile[]>([]);
  const [total, setTotal] = useState(0);
  const [search, setSearch] = useState(initialSearch);
  const [query, setQuery] = useState(initialSearch);
  const [accountWide, setAccountWide] = useState(!!initialSearch);
  const [kind, setKind] = useState("");
  const [offset, setOffset] = useState(0);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [selected, setSelected] = useState(initial);
  const [confirmed, setConfirmed] = useState(false);
  const [scopes, setScopes] = useState<Record<string, LibraryReference["scope"]>>({});
  const [preview, setPreview] = useState<{ file: LibraryFile; data: Preview } | null>(null);
  const [removeTarget, setRemoveTarget] = useState<LibraryFile | null>(null);
  const [unassigned, setUnassigned] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  const request = useRef(0);
  const alive = useRef(true);
  useEffect(() => { alive.current = true; const invalidate = () => { alive.current = false; request.current++; }; return invalidate; }, []);
  const read = useCallback(async (path: string, init?: RequestInit) => {
    const response = await apiFetch(path, init);
    if (!response.ok) throw new Error(await parseError(response));
    return response;
  }, [apiFetch]);
  const load = useCallback(async () => {
    const id = ++request.current;
    setLoading(true); setError("");
    const params = new URLSearchParams({ search: query, kind, offset: String(offset), limit: "30" });
    if (!accountWide && selectedProjectId) params.set("project_id", selectedProjectId);
    try {
      const data = await (await read(`/api/library/files?${params}`)).json();
      if (alive.current && id === request.current) { setFiles(data.files); setTotal(data.total); }
    } catch (err) { if (alive.current && id === request.current) setError(err instanceof Error ? err.message : "파일 목록을 불러오지 못했습니다."); }
    finally { if (alive.current && id === request.current) setLoading(false); }
  }, [read, query, kind, offset, accountWide, selectedProjectId]);
  useEffect(() => { void load(); }, [load]);
  const action = async (work: () => Promise<void>) => {
    if (busy) return;
    setBusy(true); setError(""); setNotice("");
    try { await work(); }
    catch (err) { if (alive.current) { setNotice(""); setError(err instanceof Error ? err.message : "파일 작업을 완료하지 못했습니다."); } }
    finally { if (alive.current) setBusy(false); }
  };
  const upload = (file: File) => action(async () => {
    const data = await uploadLibraryFile(apiFetch, file, !unassigned ? selectedProjectId || undefined : undefined,
      message => { if (alive.current) setNotice(message); });
    if (!alive.current) return;
    setNotice(data.replayed ? "같은 파일이 이미 보관되어 있습니다." : "원본을 보관했습니다. 미리보기에서 검사 후 분석에 연결하세요.");
    if (unassigned && !accountWide) setAccountWide(true);
    else await load();
  });
  const showPreview = (file: LibraryFile) => action(async () => {
    const data = await (await read(`/api/library/files/${file.file_id}/preview`)).json();
    if (alive.current) setPreview({ file, data });
  });
  const prepare = (file: LibraryFile) => action(async () => {
    await read(`/api/library/files/${file.file_id}/prepare`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ project_id: file.project_id || selectedProjectId }) });
    if (!alive.current) return;
    setPreview(null); setNotice(file.kind === "table" ? "분석 장부에 연결했습니다. 같은 파일을 다시 선택해도 행이 추가되지 않습니다." : "문서를 준비하고 있습니다. 새로고침으로 상태를 확인하세요.");
    onPrepared?.(); await load();
  });
  const download = (file: LibraryFile) => action(async () => {
    const blob = await downloadLibraryFile(apiFetch, file.file_id);
    if (!alive.current) return;
    const url = URL.createObjectURL(blob); const anchor = document.createElement("a");
    anchor.href = url; anchor.download = file.filename; anchor.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
  });
  const remove = (file: LibraryFile) => action(async () => {
    await read(`/api/library/files/${file.file_id}`, { method: "DELETE" });
    if (!alive.current) return;
    setRemoveTarget(null); setSelected((items) => items.filter((item) => item.file_id !== file.file_id)); setConfirmed(false);
    setNotice("보관함에서 제외했습니다. 연결된 장부와 원본 기록은 유지됩니다."); await load();
  });
  const toggle = (reference: LibraryReference) => {
    const exists = selected.some((item) => referenceKey(item) === referenceKey(reference));
    if (!exists && selected.length >= 10) { setError("한 번에 파일 10개까지 선택할 수 있습니다."); return; }
    // One explicit binding per file avoids ambiguous cumulative ledgers.
    setSelected((items) => exists ? items.filter((item) => referenceKey(item) !== referenceKey(reference)) : [...items.filter((item) => item.file_id !== reference.file_id), reference]);
    setConfirmed(false);
  };

  return <section aria-label="파일 보관함" className="min-w-0 space-y-5">
    {!picker && <div><h2 className="text-xl font-bold">파일 보관함</h2><p className="mt-2 text-sm text-muted-foreground">원본을 보관하고, 필요한 파일을 AI 채팅에서 다시 사용하세요.</p></div>}
    <div className="flex flex-wrap items-center justify-between gap-3">
      <div className="flex gap-1 rounded-lg border border-border p-1 text-sm">
        {[false, true].map((wide) => <button key={String(wide)} aria-pressed={accountWide === wide} onClick={() => { setAccountWide(wide); setOffset(0); }} className={`rounded-md px-3 py-1.5 ${accountWide === wide ? "bg-secondary text-foreground" : "text-muted-foreground"}`}>{wide ? "내 계정 전체" : "현재 가게"}</button>)}
      </div>
      <div className="flex flex-wrap items-center gap-3">
        <label className="flex items-center gap-2 text-xs text-muted-foreground"><input type="checkbox" checked={unassigned} onChange={(e) => setUnassigned(e.target.checked)} />가게 미지정으로 보관</label>
        <input ref={input} type="file" aria-label="보관할 파일" accept=".csv,.xlsx,.xls,.pdf,.md,.txt" className="hidden" onChange={(e) => { const file = e.target.files?.[0]; e.target.value = ""; if (file) void upload(file); }} />
        <Button variant="outline" disabled={busy} onClick={() => input.current?.click()} className="gap-2"><Upload size={15} />파일 보관</Button>
      </div>
    </div>
    <form className="flex flex-wrap gap-2" onSubmit={(e) => { e.preventDefault(); setQuery(search); setOffset(0); }}>
      <label className="flex min-w-[150px] flex-1 items-center gap-2 rounded-lg border border-input bg-[var(--surface-input)] px-3"><Search size={15} className="text-muted-foreground" /><input aria-label="보관함 파일명 검색" placeholder="파일명으로 검색" value={search} onChange={(e) => setSearch(e.target.value)} className="min-w-0 flex-1 bg-transparent py-2 text-sm outline-none" /></label>
      <select aria-label="파일 종류" value={kind} onChange={(e) => { setKind(e.target.value); setOffset(0); }} className="rounded-lg border border-input bg-card px-2 text-sm"><option value="">모든 종류</option><option value="table">CSV · Excel</option><option value="document">문서</option></select>
      <Button type="submit" variant="outline">검색</Button><Button type="button" variant="ghost" disabled={loading || busy} onClick={() => void load()}>새로고침</Button>
    </form>
    {error && <p role="alert" className="rounded-lg border border-destructive/40 bg-destructive/10 p-3 text-sm text-destructive">{error}</p>}
    {notice && <p role="status" className="rounded-lg border border-border bg-secondary p-3 text-sm">{notice}</p>}
    {loading ? <p role="status" className="py-8 text-center text-sm text-muted-foreground">파일을 불러오는 중…</p> : <div className="divide-y divide-border rounded-xl border border-border bg-card">
      {!files.length && <div className="px-5 py-12 text-center"><Archive className="mx-auto mb-4 h-7 w-7 text-muted-foreground" /><p className="text-sm">{query ? "일치하는 파일이 없습니다." : "아직 보관한 파일이 없습니다."}</p><p className="mt-2 text-xs text-muted-foreground">CSV, Excel, PDF, Markdown, 텍스트 파일을 보관할 수 있습니다.</p></div>}
      {files.map((file) => <article key={file.file_id} className="p-4" aria-label={file.filename}>
        <div className="flex flex-wrap items-start justify-between gap-3"><div className="flex min-w-0 flex-1 gap-3">{file.kind === "table" ? <FileSpreadsheet size={19} className="mt-1 shrink-0 text-accent" /> : <FileText size={19} className="mt-1 shrink-0 text-accent" />}<div className="min-w-0"><h3 className="break-all text-sm font-medium">{file.filename}</h3><p className="mt-1 text-xs text-muted-foreground">{file.project_name || file.bindings[0]?.project_name || "가게 미지정"} · {new Date(file.created_at).toLocaleDateString("ko-KR")} · {Math.max(1, Math.round(file.size_bytes / 1024)).toLocaleString()} KB</p></div></div><span className="rounded-md bg-secondary px-2 py-1 text-[11px] text-muted-foreground">{statusLabels[file.status] || file.status}</span></div>
        <div className="mt-3 flex flex-wrap items-center gap-2"><Button size="sm" variant="outline" disabled={busy} onClick={() => void showPreview(file)}>미리보기</Button><Button size="sm" variant="ghost" disabled={busy} onClick={() => void download(file)} className="gap-1.5"><Download size={13} />원본</Button>{!picker && <Button size="sm" variant="ghost" disabled={busy} onClick={() => setRemoveTarget(file)}>보관함에서 제외</Button>}</div>
        {file.bindings.map((binding) => {
          const key = `${file.file_id}:${binding.table_id || binding.project_id}`;
          const prior = selected.find(item => referenceKey(item) === key);
          const scope = scopes[key] || prior?.scope || (binding.kind === "ledger" ? "original_file" : "document");
          const reference: LibraryReference = { ...binding, scope, file_id: file.file_id, filename: file.filename, content_hash: file.content_hash, include_other_store: binding.project_id !== selectedProjectId };
          const ready = binding.kind === "ledger" || binding.index_status === "succeeded";
          return <div key={key} className="mt-3 space-y-3 rounded-lg border border-border px-3 py-3 text-xs leading-5">
            <label className="flex items-start gap-2"><input type="checkbox" className="mt-1" disabled={!ready || busy || disabled} checked={!!prior} onChange={() => toggle(reference)} aria-label={`${file.filename} 분석에 선택`} /><span><span className="font-medium">{binding.project_name}{reference.include_other_store ? " · 다른 가게 포함" : ""}</span><br />{binding.kind === "ledger" ? `${binding.table_name} · 누적 ${binding.row_count?.toLocaleString() ?? "—"}행` : ready ? "선택 문서에서 검색" : "문서 검색 준비가 필요합니다."}</span></label>
            {binding.kind === "ledger" && <label className="block">분석 범위<select aria-label={`${file.filename} 분석 범위`} value={scope} disabled={busy || disabled} className="ml-2 rounded-md border border-input bg-card px-2 py-1.5 text-foreground" onChange={e => {
              const next = e.target.value as LibraryReference["scope"]; setScopes(prev => ({...prev,[key]:next}));
              setSelected(items => items.map(item => referenceKey(item) === key ? {...reference,scope:next} : item)); setConfirmed(false);
            }}><option value="original_file">파일 원본만</option><option value="linked_ledger">누적 장부 전체</option></select><span className="mt-2 block text-muted-foreground">{scope === "original_file" ? "업로드 당시 파일의 행만 계산합니다. 이후 장부에 추가한 거래는 제외합니다." : "이 파일과 연결된 장부의 모든 거래를 계산합니다. 새로고침 시 추가 거래도 반영합니다."}</span></label>}
          </div>;
        })}
        {!file.bindings.length && <p className="mt-3 text-xs text-muted-foreground">미리보기에서 파일을 검사하고 분석에 연결할 수 있습니다.</p>}
      </article>)}
    </div>}
    <div className="flex items-center justify-between text-xs text-muted-foreground"><span>총 {total.toLocaleString()}개</span><div className="flex gap-2"><Button variant="ghost" size="sm" disabled={offset === 0 || loading} onClick={() => setOffset(Math.max(0, offset - 30))}>이전</Button><Button variant="ghost" size="sm" disabled={offset + 30 >= total || loading} onClick={() => setOffset(offset + 30)}>다음</Button></div></div>
    {preview && <div className="space-y-3 rounded-xl border border-[var(--line-strong)] bg-secondary p-4" aria-label="파일 미리보기"><div className="flex justify-between gap-3"><h3 className="break-all text-sm font-medium">{preview.file.filename}</h3><button aria-label="미리보기 닫기" onClick={() => setPreview(null)}><X size={17} /></button></div>
      {preview.data.rows && <><p className="text-xs text-muted-foreground">전체 {preview.data.row_count?.toLocaleString()}행 · 앞부분 미리보기</p><div className="max-h-56 overflow-auto"><table className="w-full text-left text-xs"><thead><tr>{preview.data.columns?.map((col) => <th key={col.name} className="whitespace-nowrap border-b border-border p-2">{col.name}</th>)}</tr></thead><tbody>{preview.data.rows.map((row, i) => <tr key={i}>{preview.data.columns?.map((col) => <td key={col.name} className="whitespace-nowrap border-b border-border p-2 numeric">{String(row[col.name] ?? "")}</td>)}</tr>)}</tbody></table></div></>}
      {preview.data.text && <pre className="max-h-48 overflow-auto whitespace-pre-wrap text-xs">{preview.data.text}</pre>}
      {!preview.data.rows && !preview.data.text && <p className="text-xs text-muted-foreground">원본 다운로드로 문서를 확인할 수 있습니다.</p>}
      {!preview.file.bindings.length && <><p className="text-xs leading-5 text-muted-foreground">{preview.file.kind === "table" ? "검사가 완료된 파일로 분석 장부를 한 번 생성합니다. 이후 선택 시 이 장부를 재사용합니다." : "문서 검색을 준비합니다. 준비 완료 후 AI 채팅에 선택할 수 있습니다."} {preview.file.project_name ? `${preview.file.project_name}에 연결합니다.` : "현재 가게에 연결합니다."}</p><Button disabled={busy || !selectedProjectId} onClick={() => void prepare(preview.file)}>검사한 파일을 분석에 연결</Button></>}
    </div>}
    {removeTarget && <div role="alert" className="space-y-3 rounded-xl border border-border p-4 text-sm"><p><strong className="break-all">{removeTarget.filename}</strong>을 보관함에서 제외할까요? 연결된 장부와 원본 기록은 유지되며, 이후 채팅에서는 이 파일을 새로 선택할 수 없습니다.</p><div className="flex gap-2"><Button variant="outline" disabled={busy} onClick={() => setRemoveTarget(null)}>취소</Button><Button variant="destructive" disabled={busy} onClick={() => void remove(removeTarget)}>제외 확인</Button></div></div>}
    <div className="sticky bottom-0 space-y-3 rounded-xl border border-border bg-card p-4">
      <div className="flex flex-wrap items-center gap-2"><span className="text-sm font-medium">분석에 선택 · {selected.length}/10</span>{selected.map((file) => <button key={referenceKey(file)} title="선택 해제" disabled={busy || disabled} onClick={() => toggle(file)} className="inline-flex max-w-full items-center gap-1 rounded-md bg-secondary px-2 py-1 text-xs"><span className="truncate">{file.filename} · {referenceScope(file)}</span><X size={12} className="shrink-0" /></button>)}</div>
      <label className="flex items-start gap-2 text-xs leading-5 text-muted-foreground"><input type="checkbox" className="mt-1" checked={confirmed} onChange={(e) => setConfirmed(e.target.checked)} disabled={!selected.length || disabled} /><span>파일별 <strong className="text-foreground">분석 범위와 가게</strong>를 확인했습니다. 원본만 선택하면 업로드 당시 행을, 누적 장부를 선택하면 추가 거래도 포함합니다. 다른 가게와 문서는 선택한 범위만 사용합니다.</span></label>
      {disabled && <p className="text-xs text-muted-foreground">채팅의 기기 첨부 파일을 제거하거나 진행 중인 분석을 마친 뒤 선택하세요.</p>}
      <p className="text-xs text-muted-foreground">파일을 채팅에 추가한 뒤 질문을 작성해 전송하세요.</p>
      <Button disabled={!selected.length || !confirmed || busy || disabled} onClick={() => onSelect(selected)} className="w-full sm:w-auto">선택한 파일을 채팅에 추가</Button>
    </div>
  </section>;
}
