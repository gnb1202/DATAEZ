"use client";

import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { formatDate, parseError } from "@/app/lib/api";
import type { Source } from "./ledger-import-panel";

const attributes = [
  { name: "payment_method", key: "payment_method_column", label: "결제수단", placeholder: "결제수단" },
  { name: "channel", key: "channel_column", label: "판매채널", placeholder: "판매채널" },
  { name: "fee", key: "fee_column", label: "PG 수수료", placeholder: "PG수수료" },
] as const;
type Restoration = {
  id: string; status: "ready" | "blocked" | "applied"; old_rule_version: number; new_rule_version: number;
  created_at: string; applied_at?: string; expires_at: string; replayed?: boolean; index_status?: string;
  report: { can_apply: boolean; row_count: number; file_count: number; pending_uploads: number; origin: string;
    attributes: Record<string, { column: string; provided: number; missing: number }>;
    issues: { code: string; message: string; row?: number; filename?: string; column?: string }[]; issue_count: number;
    sample: { target_row_id: number; event_id?: string; filename?: string; row_number: number; values: Record<string, string | null> }[] };
  result?: { rows_verified: number; invalidated_uploads: number };
};
type Change = { target_row_id: number; origin_batch_id: string | null; origin_row_number: number; origin_filename: string | null;
  before_normalized: Record<string, string | null>; after_normalized: Record<string, string | null> };
const fieldClass = "w-full rounded-lg border border-border bg-background px-3 py-2 text-sm";
const valueLabel = (name: string, value?: string | null) => value == null ? "미제공" : name === "fee" ? `${value}원` : value;

export function AttributeRestorePanel({ source, base, busy, apiFetch, run, onApplied }: {
  source: Source; base: string; busy: boolean; apiFetch: (path: string, init?: RequestInit) => Promise<Response>;
  run: (action: () => Promise<void>) => Promise<void>; onApplied: () => Promise<void>;
}) {
  const [open, setOpen] = useState(false);
  const [checked, setChecked] = useState<Restoration | null>(null);
  const [history, setHistory] = useState<Restoration[]>([]);
  const [historyVersion, setHistoryVersion] = useState(0);
  const [historyError, setHistoryError] = useState("");
  const [selected, setSelected] = useState<Restoration | null>(null);
  const [changes, setChanges] = useState<Change[]>([]);
  const [page, setPage] = useState(0);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const alive = useRef(true);
  const path = `${base}/ledger-sources/${source.id}/attribute-restorations`;
  const available = attributes.filter(a => !source.mapping[a.key]);
  useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);
  useEffect(() => {
    let cancelled = false;
    setHistoryError("");
    apiFetch(path).then(async res => {
      if (!res.ok) throw new Error(await parseError(res));
      const data = await res.json();
      if (!cancelled) setHistory(data.restorations);
    }).catch(e => { if (!cancelled) setHistoryError(e.message); });
    return () => { cancelled = true; };
  }, [apiFetch, path, source.rule_version, historyVersion]);
  useEffect(() => {
    let cancelled = false;
    setChanges([]); setTotal(0); setLoading(false);
    if (selected) {
      setLoading(true); setHistoryError("");
      apiFetch(`${path}/${selected.id}/changes?limit=20&offset=${page * 20}`).then(async res => {
        if (!res.ok) throw new Error(await parseError(res));
        const data = await res.json();
        if (!cancelled) { setChanges(data.changes); setTotal(data.total); }
      }).catch(e => { if (!cancelled) setHistoryError(e.message); }).finally(() => { if (!cancelled) setLoading(false); });
    }
    return () => { cancelled = true; };
  }, [apiFetch, path, selected, page]);

  const preview = (form: HTMLFormElement) => {
    const data = new FormData(form);
    const payload = Object.fromEntries(available.map(a => [a.key, String(data.get(a.key) || "").trim()]).filter(([, value]) => value));
    return run(async () => {
      const res = await apiFetch(path + "/preview", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
      if (!res.ok) throw new Error(await parseError(res));
      const result = await res.json();
      if (alive.current) { setChecked(result); setHistoryVersion(v => v + 1); }
    });
  };
  const apply = () => run(async () => {
    if (!checked) return;
    const res = await apiFetch(`${path}/${checked.id}/apply`, { method: "POST" });
    if (!res.ok) {
      // Keep the inspection ID after a network failure: the same apply call
      // replays a committed result. A definitive stale response requires preview.
      if (res.status === 409 && alive.current) setChecked(null);
      throw new Error(await parseError(res));
    }
    const result = await res.json();
    if (alive.current) { setChecked(result); setHistoryVersion(v => v + 1); }
    await onApplied();
  });

  return <section aria-label="과거 속성 복원" className="space-y-3 rounded-lg border border-border p-4">
    <div className="flex flex-wrap items-center justify-between gap-2"><div><h4 className="text-sm font-semibold">과거 결제 정보 복원</h4>
      <p className="mt-1 text-xs text-muted-foreground">기존 거래를 유지하며 미연결 결제수단·채널·수수료를 추가합니다.</p></div>
      <Button variant="outline" size="sm" disabled={busy} onClick={() => setOpen(v => !v)}>{open ? "복원 검사 닫기" : "과거 속성 복원"}</Button></div>
    {open && <>
      {available.length > 0 && <form aria-label="과거 속성 복원 검사" className="space-y-3" onChange={() => setChecked(null)} onSubmit={e => { e.preventDefault(); void preview(e.currentTarget); }}>
        <p className="text-sm">{source.storage_mode === "original" ? "보존된 원본 장부 컬럼을 검사합니다." : "각 거래가 처음 반영된 보관 파일과 원본 행을 검사합니다."} 추가할 정보의 원본 컬럼 이름을 입력해주세요.</p>
        <fieldset disabled={busy} className="grid gap-3 sm:grid-cols-3">{available.map(a => <label key={a.key} className="space-y-1 text-sm">{a.label} 원본 컬럼<input name={a.key} className={fieldClass} maxLength={200} placeholder={a.placeholder} /></label>)}</fieldset>
        <p className="text-xs text-muted-foreground">한 항목 이상 선택해주세요. 연결 후 올리는 파일에도 해당 컬럼이 필요합니다. 빈칸은 미제공으로 남고, 수수료는 원본 부호를 유지합니다. 기존 금액·거래 ID·지표는 유지합니다.</p>
        <Button disabled={busy || source.event_index_version !== 1} type="submit">원본 검사·복원 미리보기</Button>
        {source.event_index_version !== 1 && <p className="text-xs text-muted-foreground">출처의 기존 거래 기준점 검사를 먼저 완료해주세요.</p>}
      </form>}
      {available.length === 0 && <p className="text-sm text-muted-foreground">세 속성이 모두 연결되어 있습니다.</p>}
      {checked && <div aria-label="속성 복원 검토" className="space-y-3 rounded-lg bg-secondary/20 p-3">
        <p className="text-sm font-medium">전체 {checked.report.row_count}거래 검사 · 원본 {checked.report.file_count}파일 · 대기 업로드 {checked.report.pending_uploads}개</p>
        {Object.entries(checked.report.attributes).map(([name, stat]) => <p key={name} className="text-sm">{attributes.find(a => a.name === name)?.label}: 제공 {stat.provided}건 · 미제공 {stat.missing}건</p>)}
        {checked.report.issue_count > 0 && <div className="text-sm text-destructive"><p>복원 불가 사유 {checked.report.issue_count}개 · 전체 미반영</p>{checked.report.issues.map((issue, i) => <p key={i}>{issue.filename} {issue.row ? `${issue.row}행` : ""} {issue.column}: {issue.message}</p>)}</div>}
        {checked.report.sample.length > 0 && <div className="overflow-x-auto"><table className="w-full text-left text-xs"><thead><tr><th className="py-2">장부 행</th><th>원본 위치</th><th>복원할 정보</th></tr></thead><tbody>
          {checked.report.sample.map(row => <tr key={row.target_row_id} className="border-t border-border"><td className="py-2">{row.target_row_id}</td><td>{row.filename} · {row.row_number}행</td><td>{Object.entries(row.values).map(([name, value]) => `${attributes.find(a => a.name === name)?.label}: ${valueLabel(name, value)}`).join(" · ")}</td></tr>)}
        </tbody></table><p className="text-muted-foreground">앞 10건 예시 · 제공/미제공 건수는 검증된 원본 행 기준</p></div>}
        {checked.status === "ready" && <><p className="text-xs text-muted-foreground">검사 유효 시각: {formatDate(checked.expires_at)}. 적용하면 대기 중인 업로드는 파일을 새로 올려 검사해야 합니다.</p><Button disabled={busy || !checked.report.can_apply} onClick={apply}>검사한 속성 복원 적용</Button></>}
        {checked.status === "applied" && <div role="status" className="space-y-1 text-sm"><p className="font-semibold">속성 복원 완료</p><p>{checked.result?.rows_verified}거래 확인 · 연결 규칙 {checked.old_rule_version} → {checked.new_rule_version}</p>
          <p>{checked.replayed ? "이미 완료한 결과입니다. 재반영하지 않았습니다." : "같은 장부에 속성과 변경 이력을 저장했습니다."} 저장 지표는 재계산하거나 설정한 주기에 갱신됩니다.</p>
          {checked.index_status === "queued" && <p>검색 내용을 자동으로 갱신합니다. 검색 갱신 상태에서 진행 상황을 확인할 수 있습니다.</p>}
          {checked.index_status === "not_updated" && <p>장부 복원은 완료했습니다. 검색 갱신 상태에서 처리 상황을 확인해 주세요.</p>}
        </div>}
      </div>}
      <div className="space-y-2"><h5 className="text-sm font-medium">복원 검사·적용 이력 (최근 20개)</h5>
        <p className="text-xs text-muted-foreground">원본 반영 기록은 당시 내용으로 유지됩니다. 복원된 값은 변경 행 보기에서 확인할 수 있습니다.</p>
        {history.map(item => <div key={item.id} className="flex flex-wrap items-center justify-between gap-2 text-xs"><span>{formatDate(item.applied_at || item.created_at)} · {item.status === "applied" ? "복원 완료" : item.status === "blocked" ? "복원 불가" : "검사 기록"} · 규칙 {item.old_rule_version} → {item.new_rule_version}</span>
          {item.status === "applied" && <Button size="sm" variant="ghost" disabled={busy} onClick={() => { setSelected(item); setPage(0); }}>변경 행 보기</Button>}</div>)}
        {history.length === 0 && <p className="text-xs text-muted-foreground">아직 복원 검사 이력이 없습니다.</p>}
        {historyError && <p role="alert" className="text-sm text-destructive">{historyError}</p>}
        {selected && <div aria-label="속성 복원 변경 이력" className="space-y-2 overflow-x-auto"><p className="text-xs">규칙 {selected.old_rule_version} → {selected.new_rule_version} · {loading ? "불러오는 중…" : `총 ${total}행`}</p>
          {changes.map(change => <div key={change.target_row_id} className="border-t border-border py-2 text-xs"><p>장부 {change.target_row_id}행 · {selected.report.origin === "original" ? "보존된 원본 컬럼" : `${change.origin_filename || "최초 반영 파일"} · ${change.origin_row_number}행`}</p>
            {Object.keys(selected.report.attributes).map(name => <p key={name}>{attributes.find(a => a.name === name)?.label}: {valueLabel(name, change.before_normalized[name])} → {valueLabel(name, change.after_normalized[name])}</p>)}
            {change.origin_batch_id && <a className="inline-block pt-1 underline underline-offset-2" href={`/dashboard?${new URLSearchParams({ project: base.split("/").pop() || "", section: "tables", source: source.id, batch: change.origin_batch_id })}`}>원본 반영 기록 보기</a>}
          </div>)}
          {total > 20 && <div className="flex items-center gap-3"><Button size="sm" variant="outline" disabled={busy || loading || page === 0} onClick={() => setPage(v => v - 1)}>이전 변경 행</Button><span className="text-xs">{page + 1} / {Math.ceil(total / 20)}</span><Button size="sm" variant="outline" disabled={busy || loading || (page + 1) * 20 >= total} onClick={() => setPage(v => v + 1)}>다음 변경 행</Button></div>}
        </div>}
      </div>
    </>}
  </section>;
}
