"use client";

import { uploadSourceForm } from "@/app/lib/direct-upload";

import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { useDashboard } from "@/app/contexts/dashboard-context";
import { parseError } from "@/app/lib/api";
import { exactMetricValue } from "./metric-analysis-dialog";
import type { Source, ImportBatch } from "./ledger-import-panel";

type Inspection = { columns: string[]; row_count: number; suggested_mapping: Record<string, string | null>; candidates: Record<string, string[]>; sample: {row:number;values:(string|null)[]}[]; first_sheet_only: boolean };
type Check = { row_count:number; amount:string; note:string; sample:{row:number;event_id:string|null;event_kind:string;amount:string;occurred_at:string}[] };
const roles = [
  ["amount_column", "결제·취소 금액", true], ["occurred_at_column", "결제·취소 발생일", true],
  ["currency_column", "통화", false], ["event_id_column", "개별 결제·취소 ID", false],
  ["original_event_id_column", "원거래 ID", false], ["payment_method_column", "결제수단", false],
  ["channel_column", "판매채널", false], ["fee_column", "PG 수수료", false],
] as const;
const field = "block w-full rounded-md border border-input bg-background p-2 text-sm";

export function FileMappingWizard({ onPrepared, onBusyChange }: {onPrepared:(source:Source,batch:ImportBatch)=>void;onBusyChange:(busy:boolean)=>void}) {
  const {selectedProjectId,apiFetch}=useDashboard();
  const [file,setFile]=useState<File|null>(null);
  const [inspection,setInspection]=useState<Inspection|null>(null);
  const [mapping,setMapping]=useState<Record<string,string|null>>({});
  const [kind,setKind]=useState("");
  const [name,setName]=useState("");
  const [provider,setProvider]=useState("");
  const [account,setAccount]=useState("");
  const [confirmed,setConfirmed]=useState(false);
  const [checked,setChecked]=useState<{key:string;data:Check}|null>(null);
  const [created,setCreated]=useState<Source|null>(null);
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState("");
  const alive=useRef(true), requestKey=useRef("");
  useEffect(()=>{alive.current=true;return()=>{alive.current=false;};},[]);
  const definition={...mapping,event_kind:kind,currency:"KRW",timezone:"Asia/Seoul"};
  const key=JSON.stringify(definition), report=checked?.key===key?checked.data:null;
  const base=`/api/projects/${selectedProjectId}`;
  async function json(path:string,init:RequestInit){const r=await apiFetch(path,init);if(!r.ok)throw new Error(await parseError(r));return r.json();}
  async function run(action:()=>Promise<void>){setBusy(true);onBusyChange(true);setError("");try{await action();}catch(e){if(alive.current)setError(e instanceof Error?e.message:"다시 시도해주세요.");}finally{if(alive.current){setBusy(false);onBusyChange(false);}}}
  async function inspect(){if(!file)return;await run(async()=>{
    setInspection(null);setChecked(null);setConfirmed(false);setKind("");
    const data=await uploadSourceForm(apiFetch,file,selectedProjectId!);
    const result:Inspection=await json(base+"/import-mapping/inspect",{method:"POST",body:data});
    if(alive.current){setInspection(result);setMapping(result.suggested_mapping);}
  });}
  async function validate(){if(!file)return;await run(async()=>{
    setChecked(null);const data=await uploadSourceForm(apiFetch,file,selectedProjectId!);data.set("mapping",JSON.stringify(definition));
    const result=await json(base+"/import-mapping/validate",{method:"POST",body:data});
    if(alive.current)setChecked({key,data:result});
  });}
  async function prepare(){if(!file||!report||!confirmed)return;await run(async()=>{
    const source:Source=created||await json(base+"/ledger-sources",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({name:name.trim(),provider:provider.trim(),account:account.trim(),feed:"결제·취소 이벤트",mapping:definition})});
    if(!alive.current)return;setCreated(source);
    if(!requestKey.current)requestKey.current=crypto.randomUUID();
    const data=await uploadSourceForm(apiFetch,file,selectedProjectId!);data.set("source_id",source.id);data.set("request_key",requestKey.current);
    const batch=await json(base+"/imports",{method:"POST",body:data});
    if(alive.current){onBusyChange(false);onPrepared(source,batch);}
  });}
  return <section aria-label="파일 연결 안내" className="space-y-4 rounded-lg border bg-secondary/20 p-4">
    <div><h4 className="font-medium">파일을 보고 컬럼을 연결하세요</h4><p className="mt-1 text-sm text-muted-foreground">원본은 보관함에 저장되며, 컬럼 확인과 연결 검사만으로 장부에 반영되지 않습니다. 다음 단계에서 중복·오류를 검토한 뒤 장부에 반영합니다.</p></div>
    <fieldset disabled={busy||!!created} className="space-y-4">
      <div className="flex flex-wrap items-end gap-3"><label className="flex-1 text-sm">연결할 결제 파일<input aria-label="연결할 결제 파일" type="file" accept=".csv,.xlsx,.xls" className={field} onChange={e=>{const f=e.target.files?.[0]||null;setFile(f);setInspection(null);setChecked(null);setConfirmed(false);setKind("");requestKey.current="";if(f)setName(f.name.replace(/\.(csv|xlsx?)$/i,"").slice(0,120));}}/></label><Button type="button" disabled={!file} onClick={inspect}>파일 컬럼 확인</Button></div>
      <p className="text-xs text-muted-foreground">CSV·XLSX·XLS, 최대 20MB·10만 행. Excel은 첫 시트만 읽습니다. 금액은 쉼표 없는 숫자, 날짜는 2026-09-08 같은 형식을 사용하세요.</p>
      {inspection&&<>
        <p role="status" className="text-sm">전체 {inspection.row_count.toLocaleString()}행 · 아래는 앞 {inspection.sample.length}행 표본입니다.{inspection.first_sheet_only?" Excel 첫 번째 시트를 확인했습니다.":""}</p>
        <div className="max-h-64 overflow-auto rounded border"><table className="w-full text-left text-sm" aria-label="원본 파일 표본"><thead><tr><th className="p-2">원본 행</th>{inspection.columns.map(c=><th key={c} className="p-2 whitespace-nowrap">{c}</th>)}</tr></thead><tbody>{inspection.sample.map(r=><tr key={r.row} className="border-t"><td className="p-2">{r.row}</td>{r.values.map((v,i)=><td key={i} className="p-2 whitespace-nowrap">{v??"미제공"}</td>)}</tr>)}</tbody></table></div>
        <p className="text-sm">이름이 일치하는 컬럼을 후보로 연결했습니다. 후보가 여러 개면 비워 둡니다. 실제 의미를 확인하고 선택해주세요.</p>
        <div className="grid gap-3 sm:grid-cols-2">{roles.map(([role,label,required])=><label key={role} className="text-sm">{label}{required?" *":" (선택)"}<select aria-label={label} className={field} value={mapping[role]||""} onChange={e=>{setMapping(m=>({...m,[role]:e.target.value||null}));setConfirmed(false);}}><option value="">{required?"컬럼 선택":"연결하지 않음"}</option>{inspection.columns.map(c=><option key={c}>{c}</option>)}</select>{inspection.candidates[role]?.length>1&&<span className="text-xs text-muted-foreground">후보: {inspection.candidates[role].join(", ")}</span>}</label>)}</div>
        <label className="block text-sm">금액 해석 *<select aria-label="파일 금액 해석" className={field} value={kind} onChange={e=>{setKind(e.target.value);setConfirmed(false);}}><option value="">자료의 의미 선택</option><option value="signed">결제·취소 혼합 · 취소는 음수, 원본 부호 유지</option><option value="payment">결제만 · 양수 금액</option><option value="refund">취소만 · 음수로 반영</option></select></label>
        <p className="text-xs text-muted-foreground">개별 취소 ID가 없다면 ID 연결을 비워두고 원거래 ID만 연결하세요. 통화는 KRW, 시간대 없는 일시는 한국 시간입니다. 수수료는 별도로 보존하며 결제금액에서 자동 차감하지 않습니다.</p>
        <label className="flex items-start gap-2 text-sm"><input type="checkbox" checked={confirmed} onChange={e=>setConfirmed(e.target.checked)}/>거래별 원화 결제·취소 자료이며, 정산 입금액이나 집계표가 아님을 확인했습니다.</label>
        <Button type="button" disabled={!mapping.amount_column||!mapping.occurred_at_column||!kind||!confirmed} onClick={validate}>연결한 파일 전체 검사</Button>
      </>}
      {report&&<>
        <div role="status" className="space-y-1 rounded-md border p-3 text-sm"><p className="font-medium">형식 검사 완료 · {report.row_count.toLocaleString()}행 · {exactMetricValue(report.amount,"KRW")}</p><p>{report.note}</p></div>
        <div className="grid gap-3 sm:grid-cols-3">{[["출처 이름",name,setName],["파일 제공처",provider,setProvider],["가맹점·관리 계정",account,setAccount]].map(([label,value,change])=><label key={String(label)} className="text-sm">{String(label)}<input aria-label={String(label)} className={field} value={String(value)} maxLength={120} onChange={e=>(change as (v:string)=>void)(e.target.value)}/></label>)}</div>
        <p className="text-xs text-muted-foreground">같은 제공처·계정의 다음 파일도 이 출처에 연결합니다. 같은 거래를 새 출처로 반복 등록하지 마세요.</p>
      </>}
    </fieldset>
    {created&&<p role="status" className="text-sm">출처가 저장되었습니다. 업로드가 중단되었다면 아래 버튼으로 같은 파일의 검토를 이어가세요.</p>}
    {error&&<p role="alert" className="text-sm text-destructive">{error}</p>}
    {report&&<Button disabled={busy||!confirmed||!name.trim()||!provider.trim()||!account.trim()} onClick={prepare}>{busy?"준비 중…":created?"이 파일 검토 이어가기":"출처 저장하고 중복 검토"}</Button>}
  </section>;
}
