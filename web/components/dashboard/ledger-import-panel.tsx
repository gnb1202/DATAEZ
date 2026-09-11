"use client";

import { uploadSourceForm } from "@/app/lib/direct-upload";

import { useCallback, useEffect, useRef, useState } from "react";
import { Loader2, Upload } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useDashboard } from "@/app/contexts/dashboard-context";
import { formatDate, parseError } from "@/app/lib/api";
import type { TableMeta } from "@/app/lib/api";
import { EventReviewPanel } from "./event-review-panel";
import { FileMappingWizard } from "./file-mapping-wizard";
import { AttributeRestorePanel } from "./attribute-restore-panel";

export type Source = {
  id: string; name: string; provider: string; account: string; feed: string;
  table_id: string; row_count: number; data_revision: number;
  event_index_version?: number;
  rule_version: number; storage_mode: string;
  input_mode?: "file" | "cash";
  mapping: { amount_column: string; occurred_at_column: string; event_kind: string;
    payment_method_column?: string; channel_column?: string; fee_column?: string };
};
export type ImportBatch = {
  id: string; source_id?: string; filename: string; status: string; created_at: string; committed_at?: string;
  preview_token?: string | null; replayed?: boolean; rows_added?: number;
  review_version?: number;
  requires_reupload?: boolean;
  summary?: { row_count: number; amount: string; can_commit?: boolean; counts?: Record<string, number>; sample: { row: number; event_id: string | null; amount: string; occurred_at: string }[] };
  result?: { rows_inserted: number; amount: string; total_row_count: number; duplicates_skipped?: number; candidates_excluded?: number };
  error?: { detail: string };
  same_file_sources?: { source_id: string; source_name: string }[];
};
type Batch = ImportBatch;
type Baseline = { row_count: number; counts: Record<string, number>; can_adopt: boolean; adoption_token?: string; issues?: { row_number: number; classification: string; matched_row: number }[] };
const statusNames: Record<string, string> = { staging: "업로드 중단", uploaded: "미리보기 전", ready: "반영 대기", committed: "반영 완료", failed: "검증 오류", expired: "보관 만료" };
const fieldClass = "w-full rounded-lg border border-border bg-background px-3 py-2 text-sm disabled:opacity-50";

export function LedgerImportPanel({ onTablesChange, tables, onOpenDashboard }: { onTablesChange: () => void; tables: TableMeta[]; onOpenDashboard?: () => void }) {
  const { selectedProjectId: projectId, apiFetch } = useDashboard();
  const [sources, setSources] = useState<Source[]>([]);
  const [sourceId, setSourceId] = useState("");
  const [creating, setCreating] = useState(false);
  const [mappingOpen, setMappingOpen] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  const [batch, setBatch] = useState<Batch | null>(null);
  const [history, setHistory] = useState<Batch[]>([]);
  const [page, setPage] = useState(0);
  const [total, setTotal] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [historyError, setHistoryError] = useState("");
  const [historyVersion, setHistoryVersion] = useState(0);
  const [adoption, setAdoption] = useState<Baseline | null>(null);
  const [baseline, setBaseline] = useState<Baseline | null>(null);
  const [acceptIdless, setAcceptIdless] = useState(false);
  const [existingTable, setExistingTable] = useState("");
  const requestKey = useRef("");
  const fileInput = useRef<HTMLInputElement>(null);
  const alive = useRef(true);
  const base = `/api/projects/${projectId}`;
  const source = sources.find((item) => item.id === sourceId);

  const json = useCallback(async (path: string, init?: RequestInit) => {
    const res = await apiFetch(path, init);
    if (!res.ok) throw new Error(await parseError(res));
    return res.json();
  }, [apiFetch]);

  useEffect(() => {
    alive.current = true;
    let cancelled = false;
    json(`${base}/ledger-sources`).then(async (data) => {
      if (cancelled) return;
      data.sources = data.sources.filter((item: Source) => item.input_mode !== "cash");
      setSources(data.sources);
      const params = new URLSearchParams(window.location.search);
      const linkedSource = params.get("project") === projectId ? params.get("source") : null;
      const selected = data.sources.find((item: Source) => item.id === linkedSource)?.id || data.sources[0]?.id || "";
      setSourceId(selected);
      const linkedBatch = params.get("batch");
      if (linkedSource && linkedBatch && selected === linkedSource) {
        const linked = await json(`${base}/imports/${encodeURIComponent(linkedBatch)}`);
        if (!cancelled && linked.source_id === selected) setBatch(linked);
      }
    }).catch((e: Error) => { if (!cancelled) setError(e.message); });
    return () => { cancelled = true; alive.current = false; };
  }, [base, json]);

  useEffect(() => {
    let cancelled = false;
    setHistory([]);
    setTotal(0);
    setHistoryError("");
    if (sourceId) json(`${base}/imports?source_id=${sourceId}&limit=20&offset=${page * 20}`).then((data) => {
      if (!cancelled) { setHistory(data.batches); setTotal(data.total); }
    }).catch((e: Error) => { if (!cancelled) setHistoryError(e.message); });
    return () => { cancelled = true; };
  }, [sourceId, base, json, page, historyVersion]);

  const run = async (action: () => Promise<void>) => {
    setBusy(true);
    setError("");
    try { await action(); }
    catch (e) { if (alive.current) setError(e instanceof Error ? e.message : "요청에 실패했습니다. 다시 시도해주세요."); }
    finally { if (alive.current) { setBusy(false); setHistoryVersion((v) => v + 1); } }
  };

  const refreshTables = async () => {
    const data = await json(`${base}/ledger-sources`);
    if (alive.current) { setSources(data.sources.filter((item: Source) => item.input_mode !== "cash")); onTablesChange(); }
  };

  const createSource = (form: HTMLFormElement) => run(async () => {
    const data = new FormData(form);
    const value = (name: string) => String(data.get(name) || "").trim();
    const mapping = { amount_column: value("amount_column"), occurred_at_column: value("occurred_at_column"),
      event_kind: value("event_kind"), event_id_column: value("event_id_column") || undefined,
      original_event_id_column: value("original_event_id_column") || undefined,
      payment_method_column: value("payment_method_column") || undefined,
      channel_column: value("channel_column") || undefined, fee_column: value("fee_column") || undefined };
    const payload = { name: value("name"), provider: value("provider"), account: value("account"), feed: value("feed"), mapping,
      existing_table_id: existingTable || undefined, accept_idless: data.get("accept_idless") === "on", adoption_token: adoption?.adoption_token };
    if (existingTable && !adoption?.can_adopt) {
      const report = await json(`${base}/ledger-sources/preview-adoption`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
      if (alive.current) setAdoption(report);
      return;
    }
    let created;
    try {
      created = await json(`${base}/ledger-sources`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
    } catch (e) { setAdoption(null); throw e; }
    if (!alive.current) return;
    setSources((items) => [...items.filter((item) => item.id !== created.id), created]);
    setSourceId(created.id); setCreating(false); setBatch(null); setFile(null); setPage(0); setAdoption(null); setBaseline(null); setExistingTable("");
    if (fileInput.current) fileInput.current.value = "";
    onTablesChange();
  });

  const preview = async (id: string) => {
    const ready = await json(`${base}/imports/${id}/preview`, { method: "POST" });
    if (alive.current) setBatch(ready);
  };

  const upload = () => run(async () => {
    if (!file || !sourceId) return;
    if (!requestKey.current) requestKey.current = crypto.randomUUID();
    const data = await uploadSourceForm(apiFetch, file, projectId!); data.set("source_id", sourceId); data.set("request_key", requestKey.current);
    const uploaded = await json(`${base}/imports`, { method: "POST", body: data });
    if (!alive.current) return;
    setBatch(uploaded); setPage(0);
    if (uploaded.status !== "committed") await preview(uploaded.id);
  });

  const commit = () => run(async () => {
    if (!batch?.preview_token) return;
    try {
      const result = await json(`${base}/imports/${batch.id}/commit`, { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ preview_token: batch.preview_token }) });
      if (alive.current) setBatch(result);
    } catch (e) {
      // A lost response can still mean the commit succeeded. Keep the batch
      // id and let re-preview retrieve that saved result before another commit.
      if (alive.current) setBatch({ ...batch, status: "uploaded", preview_token: null });
      throw e;
    }
    await refreshTables();
  });

  return (
    <section aria-label="출처별 파일 반영" className="space-y-4 rounded-xl border border-border bg-card p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div><h3 className="font-semibold">출처별 파일 반영</h3>
          <p className="mt-1 text-sm text-muted-foreground">같은 가게·출처에 같은 파일을 다시 올려도 한 번만 반영합니다.</p></div>
        <div className="flex flex-wrap gap-2"><Button disabled={busy} onClick={() => { setMappingOpen(v => !v); setCreating(false); }}>{mappingOpen ? "파일 연결 닫기" : "파일로 출처 연결"}</Button><Button variant="outline" disabled={busy} onClick={() => { setCreating((v) => !v); setMappingOpen(false); }}>{creating ? "출처 등록 닫기" : "새 출처 등록"}</Button></div>
      </div>
      {mappingOpen && <FileMappingWizard onBusyChange={setBusy} onPrepared={(created, uploaded) => {
        setSources(items => [...items.filter(item => item.id !== created.id), created]);
        setSourceId(created.id); setBatch(uploaded); setPage(0); setMappingOpen(false); setFile(null); requestKey.current = "";
        setHistoryVersion(v => v + 1); onTablesChange();
      }} />}
      {creating && <form aria-label="새 출처 등록" className="space-y-4 rounded-lg bg-secondary/30 p-4" onChange={() => setAdoption(null)} onSubmit={(e) => { e.preventDefault(); void createSource(e.currentTarget); }}>
        <p className="text-sm text-muted-foreground">원화 결제·취소 이벤트 파일을 연결합니다. 기존 장부 전환은 전체 행 검사 후 진행하며 원래 행과 저장 지표를 유지합니다. 등록한 연결 규칙은 고정되며, 미연결 추가 정보는 이후 원본 검사를 거쳐 복원할 수 있습니다.</p>
        <label className="block space-y-1 text-sm">대상 장부<select className={fieldClass} disabled={busy} value={existingTable} onChange={(e) => setExistingTable(e.target.value)}>
          <option value="">새 장부 만들기</option>{tables.filter((t) => !t.ledger_source_id).map((t) => <option key={t.id} value={t.id}>{t.name} · 기존 {t.row_count}행 전환</option>)}</select></label>
        <fieldset disabled={busy} className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {[["name", "출처 이름", "강남점 카드 매출"], ["provider", "제공자", "카드사 또는 현금 수기"], ["account", "가맹점·계정", "가맹점 번호 또는 관리 계정"], ["feed", "자료 종류", "결제 이벤트"]].map(([name, label, placeholder]) =>
            <label key={name} className="space-y-1 text-sm">{label}<input className={fieldClass} name={name} required maxLength={120} placeholder={placeholder} /></label>)}
        </fieldset>
        <p className="text-sm">{existingTable ? "기존 장부의 컬럼 이름을 연결해주세요. 이후 파일은 현재 장부의 전체 컬럼 형식을 사용합니다." : "파일 첫 행의 컬럼 이름을 그대로 입력해주세요."} 금액은 원 단위 숫자, 일시는 ISO 형식(예: 2026-09-08)으로 준비합니다.</p>
        {existingTable && <p className="text-xs text-muted-foreground">장부 컬럼: {tables.find((t) => t.id === existingTable)?.columns_schema.map((c) => c.name).join(", ")}</p>}
        <fieldset disabled={busy} className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {[["amount_column", "금액 컬럼", true], ["occurred_at_column", "발생일시 컬럼", true], ["event_id_column", "이벤트 ID 컬럼 (선택)", false], ["original_event_id_column", "원거래 ID 컬럼 (선택)", false]].map(([name, label, required]) =>
            <label key={String(name)} className="space-y-1 text-sm">{label}<input className={fieldClass} name={String(name)} required={Boolean(required)} maxLength={200} /></label>)}
        </fieldset>
        <label className="block max-w-sm space-y-1 text-sm">금액 해석<select name="event_kind" disabled={busy} className={fieldClass}>
          <option value="payment">결제 — 양수 금액</option><option value="refund">취소 — 음수로 반영</option><option value="signed">결제·취소 혼합 — 원본 부호 유지</option>
        </select></label>
        <fieldset disabled={busy} className="grid gap-3 sm:grid-cols-3">
          <legend className="mb-2 text-sm font-medium">분석에 사용할 추가 정보 (선택)</legend>
          {[["payment_method_column", "결제수단 컬럼", "결제수단"], ["channel_column", "판매채널 컬럼", "판매채널"], ["fee_column", "PG 수수료 컬럼", "PG수수료"]].map(([name, label, placeholder]) =>
            <label key={name} className="space-y-1 text-sm">{label}<input className={fieldClass} name={name} maxLength={200} placeholder={placeholder} /></label>)}
        </fieldset>
        <p className="text-xs text-muted-foreground">연결한 컬럼의 빈칸은 미제공으로 남습니다. 수수료는 원 단위 숫자이며 원본 부호를 유지합니다. 결제금액에서 자동 차감하지 않습니다.</p>
        <p className="text-xs text-muted-foreground">통화: KRW · 시간대 없는 일시: 한국 시간 · Excel은 첫 번째 시트만 읽습니다.</p>
        <p className="text-xs text-muted-foreground">취소의 이벤트 ID는 각각의 취소를 식별해야 합니다. 독립된 취소 ID가 없다면 이벤트 ID 연결을 비우고 원거래 ID만 연결해주세요.</p>
        {existingTable && <label className="flex items-center gap-2 text-sm"><input type="checkbox" name="accept_idless" disabled={busy} />기존 장부의 ID 없는 유사 거래는 각각 별개 거래로 유지합니다</label>}
        {adoption && <div className="space-y-1 text-sm"><p>기존 {adoption.row_count}행 · 중복 {adoption.counts.duplicate} · 충돌 {adoption.counts.conflict} · 유사 후보 {adoption.counts.candidate}</p>
          <p>{adoption.can_adopt ? "검사를 통과했습니다. 전환하면 직접 수정 대신 출처 업로드를 사용합니다." : "중복·충돌을 기존 장부에서 해결하거나 ID 없는 후보의 유지 여부를 확인한 뒤 다시 검사해주세요."}</p>
          {adoption.issues?.slice(0, 5).map((item) => <p key={item.row_number}>장부 {item.row_number}행 ↔ {item.matched_row}행: {item.classification}</p>)}
        </div>}
        <Button disabled={busy} type="submit">{existingTable ? adoption?.can_adopt ? "검사한 장부를 출처로 전환" : "기존 장부 전체 검사" : "출처와 장부 만들기"}</Button>
      </form>}
      {sources.length > 0 ? <>
        <div className="grid items-end gap-3 md:grid-cols-[1fr_1fr_auto]">
          <label className="space-y-1 text-sm">반영할 출처<select aria-label="반영할 출처" className={fieldClass} value={sourceId} disabled={busy} onChange={(e) => {
            setSourceId(e.target.value); setFile(null); setBatch(null); setError(""); setPage(0); setBaseline(null); setAcceptIdless(false); requestKey.current = "";
            if (fileInput.current) fileInput.current.value = "";
          }}>{sources.map((item) => <option key={item.id} value={item.id}>{item.name} · {item.account}</option>)}</select></label>
          <label className="space-y-1 text-sm">결제 파일<input ref={fileInput} className={fieldClass} type="file" accept=".csv,.xlsx,.xls" disabled={busy} onChange={(e) => {
            setFile(e.target.files?.[0] || null); setBatch(null); setError(""); requestKey.current = "";
          }} /></label>
          <Button disabled={busy || !file || !sourceId} onClick={upload}>{busy ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Upload className="mr-2 h-4 w-4" />}업로드·미리보기</Button>
        </div>
        {source && <p className="text-xs text-muted-foreground">{source.provider} / {source.account} / {source.feed} · 금액: {source.mapping.amount_column} · 일시: {source.mapping.occurred_at_column}</p>}
        {source && <p className="text-xs text-muted-foreground">결제수단: {source.mapping.payment_method_column || "미연결"} · 판매채널: {source.mapping.channel_column || "미연결"} · PG 수수료: {source.mapping.fee_column || "미연결"}</p>}
      </> : !creating && <p className="text-sm text-muted-foreground">제공자·계정별 출처를 먼저 등록한 뒤 파일을 연결해주세요.</p>}
      {source?.event_index_version === 0 && <div className="space-y-2 rounded border border-border p-3 text-sm"><p>이 출처는 이전에 등록한 장부입니다. 새 파일을 반영하기 전에 기존 거래 전체를 검사해주세요.</p>
        <label className="flex items-center gap-2"><input type="checkbox" disabled={busy} checked={acceptIdless} onChange={(e) => setAcceptIdless(e.target.checked)} />기존 ID 없는 유사 거래를 각각 별개로 유지</label>
        <Button variant="outline" disabled={busy} onClick={() => run(async () => {
          const result = await json(`${base}/ledger-sources/${sourceId}/baseline`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ accept_idless: acceptIdless }) });
          if (alive.current) setBaseline(result); await refreshTables();
        })}>기준점 검사·전환</Button>
        {baseline && <p>중복 {baseline.counts.duplicate} · 충돌 {baseline.counts.conflict} · 후보 {baseline.counts.candidate}. {baseline.can_adopt ? "전환 완료" : "미해결 거래가 있어 전환하지 않았습니다."}</p>}
      </div>}
      <p className="text-sm text-muted-foreground">같은 출처의 같은 이벤트 ID·내용은 중복 제외하고, 내용이 다르면 반영을 막습니다. ID 없는 유사 거래는 포함·제외를 직접 결정해주세요. 미반영 파일은 24시간 보관합니다.</p>
      {source && <AttributeRestorePanel key={source.id} source={source} base={base} busy={busy} apiFetch={apiFetch} run={run} onApplied={async () => {
        setBatch(null); setFile(null); requestKey.current = "";
        if (fileInput.current) fileInput.current.value = "";
        await refreshTables();
      }} />}
      {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
      {batch && <div aria-label="업로드 검토" className="space-y-3 rounded-lg border border-border p-4">
        <div className="flex flex-wrap items-center justify-between gap-2"><h4 className="font-medium">{batch.filename}</h4><span className="text-sm text-muted-foreground">{statusNames[batch.status] || batch.status}</span></div>
        {!!batch.same_file_sources?.length && <p className="text-sm text-amber-700 dark:text-amber-300">같은 파일이 다른 출처에도 반영되어 있습니다: {batch.same_file_sources.map((item) => item.source_name).join(", ")}. 선택한 계정과 자료 종류를 확인해주세요.</p>}
        {batch.status === "committed" && batch.result ? <div role="status" className="space-y-1 text-sm">
          <p className="font-semibold">{batch.replayed ? "이미 반영한 파일입니다. 이번 추가는 0건입니다." : "장부 반영 완료"}</p>
          <p>이 파일의 반영 결과: {batch.result.rows_inserted}행 · {batch.result.amount}원</p>
          {batch.review_version === 1 && <p>중복 제외 {batch.result.duplicates_skipped ?? 0}행 · 사용자 제외 {batch.result.candidates_excluded ?? 0}행</p>}
          <p className="text-muted-foreground">저장 지표는 대시보드에서 새로고침하거나 설정한 주기에 재계산됩니다.</p>
          {onOpenDashboard && <Button variant="outline" onClick={onOpenDashboard}>대시보드에서 첫 지표 만들기</Button>}
        </div> : <>
          {batch.summary && <>
            <p className="font-medium">반영 예정 {batch.summary.counts?.included ?? batch.summary.row_count}행 · {batch.summary.amount}원</p>
            {batch.summary.counts && <p className="text-sm">총 {batch.summary.row_count}행 · 신규 {batch.summary.counts.new} · 중복 {batch.summary.counts.duplicate} · 후보 {batch.summary.counts.candidate} · 충돌 {batch.summary.counts.conflict} · 미결정 {batch.summary.counts.unresolved}</p>}
            {batch.review_version !== 1 && <><div className="overflow-x-auto"><table className="w-full text-left text-sm"><thead className="text-muted-foreground"><tr><th className="py-2">원본 행</th><th>이벤트 ID</th><th>금액 (원)</th><th>발생일시</th></tr></thead>
              <tbody>{batch.summary.sample.map((row) => <tr key={row.row} className="border-t border-border"><td className="py-2">{row.row}</td><td>{row.event_id || "없음"}</td><td className="tabular-nums">{row.amount}</td><td>{row.occurred_at}</td></tr>)}</tbody></table></div>
            <p className="text-xs text-muted-foreground">앞 5행 미리보기 · 금액과 건수는 파일 전체 기준입니다.</p></>}
          </>}
          {batch.error && <p className="text-sm text-destructive">{batch.error.detail}</p>}
          {batch.requires_reupload && <p className="text-sm text-muted-foreground">출처에 속성이 추가되어 이전 검사는 사용할 수 없습니다. 파일을 다시 선택해 업로드해주세요.</p>}
          <div className="flex gap-2"><Button variant="outline" disabled={busy || batch.requires_reupload || ["staging", "expired"].includes(batch.status)} onClick={() => run(() => preview(batch.id))}>{batch.status === "uploaded" ? "중복 검사·미리보기" : "미리보기 다시 확인"}</Button>
            <Button disabled={busy || batch.status !== "ready" || !batch.preview_token || batch.summary?.can_commit === false} onClick={commit}>장부에 반영</Button></div>
          {["staging", "expired"].includes(batch.status) && <p className="text-sm text-muted-foreground">같은 파일을 다시 선택해 업로드해주세요.</p>}
        </>}
        {batch.review_version === 1 && <EventReviewPanel key={batch.id} base={base} batch={batch} apiFetch={apiFetch} busy={busy} run={run} onBatch={setBatch} />}
      </div>}
      {sourceId && <div className="space-y-2">
        <h4 className="text-sm font-semibold">업로드 이력 <span className="text-muted-foreground">{total}개 파일</span></h4>
        {historyError && <p role="alert" className="text-sm text-destructive">{historyError}</p>}
        {history.map((item) => <button key={item.id} disabled={busy} onClick={() => run(async () => {
          const result = await json(`${base}/imports/${item.id}`); if (alive.current) setBatch(result);
        })} className="flex w-full flex-wrap items-center justify-between gap-2 rounded-lg border border-border px-3 py-2 text-left text-sm hover:bg-secondary/40 disabled:opacity-50">
          <span>{item.filename}<span className="ml-2 text-xs text-muted-foreground">{formatDate(item.created_at)}</span></span>
          <span>{statusNames[item.status]}{item.result ? ` · ${item.result.rows_inserted}행` : ""}</span>
        </button>)}
        {total === 0 && !historyError && <p className="text-sm text-muted-foreground">아직 업로드한 파일이 없습니다.</p>}
        {total > 20 && <div className="flex items-center gap-3"><Button variant="outline" size="sm" disabled={busy || page === 0} onClick={() => setPage((v) => v - 1)}>이전 이력</Button><span className="text-sm">{page + 1} / {Math.ceil(total / 20)}</span><Button variant="outline" size="sm" disabled={busy || (page + 1) * 20 >= total} onClick={() => setPage((v) => v + 1)}>다음 이력</Button></div>}
      </div>}
    </section>
  );
}
