"use client";

import { useCallback, useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { useDashboard } from "@/app/contexts/dashboard-context";
import { parseError } from "@/app/lib/api";
import { exactMetricValue, MetricAnalysisDialog } from "./metric-analysis-dialog";
import { EChartsChart } from "./echarts-chart";
import type { Project } from "@/app/lib/api";
import type { LibraryFile } from "@/app/lib/file-library";
import type { Source } from "./ledger-import-panel";

const field="block w-full rounded-md border border-input bg-background p-2 text-sm";
type Props={completed:boolean;onCreateStore:()=>void;onOpenTables:()=>void;onCreated:()=>void;onStartChat:(prompt:string)=>void;onSampleReady:(project:Project,file:LibraryFile)=>void;onOpenLibrary:()=>void};

export function GettingStarted({completed,onCreateStore,onOpenTables,onCreated,onStartChat,onSampleReady,onOpenLibrary}:Props){
  const {selectedProjectId,apiFetch}=useDashboard();
  const [sources,setSources]=useState<Source[]|null>(null);
  const [sourceId,setSourceId]=useState("");
  const [open,setOpen]=useState(!completed);
  const [mode,setMode]=useState("daily");
  const [period,setPeriod]=useState("all");
  const [title,setTitle]=useState("첫 결제액 그래프 (원)");
  const [interval,setInterval]=useState(3600);
  const [preview,setPreview]=useState<{key:string;data:Record<string,unknown>}|null>(null);
  const [busy,setBusy]=useState(false),[error,setError]=useState("");
  const [retry,setRetry]=useState(0);
  useEffect(()=>{let active=true;if(!selectedProjectId)return;
    setSources(null);setError("");apiFetch(`/api/projects/${selectedProjectId}/ledger-sources`).then(async r=>{
      if(!r.ok)throw new Error(await parseError(r));const data=await r.json();if(active)setSources(data.sources);
    }).catch(e=>{if(active)setError(e.message);});return()=>{active=false;};
  },[selectedProjectId,apiFetch,retry]);
  const eligible=(sources||[]).filter(s=>s.row_count>0&&s.storage_mode==="canonical");
  const source=eligible.find(s=>s.id===sourceId)||(sourceId?undefined:eligible[0]);
  const definition={unit:"KRW",table_id:source?.table_id,operation:"sum",column:"amount",group_by:mode==="daily"?"occurred_at":null,date_grain:mode==="daily"?"day":null,chart_type:"bar",time_range:period,date_column:"occurred_at"};
  const key=JSON.stringify(definition),result=preview?.key===key?preview.data:null;
  const hasData=(sources||[]).some(s=>s.row_count>0);
  const run=useCallback(async(action:()=>Promise<void>)=>{setBusy(true);setError("");try{await action();}catch(e){setError(e instanceof Error?e.message:"요청을 완료하지 못했습니다.");}finally{setBusy(false);}},[]);
  async function calculate(){await run(async()=>{
    setPreview(null);const r=await apiFetch(`/api/projects/${selectedProjectId}/metrics/preview`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({definition})});
    if(!r.ok)throw new Error(await parseError(r));setPreview({key,data:{...await r.json(),unit:"KRW"}});
  });}
  async function save(){if(!result||!title.trim())return;await run(async()=>{
    const r=await apiFetch(`/api/projects/${selectedProjectId}/metrics`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({title,definition,refresh_interval_seconds:interval})});
    if(!r.ok)throw new Error(await parseError(r));onCreated();
  });}
  async function sample(){await run(async()=>{
    const response=await apiFetch("/api/library/files/sample-workspace",{method:"POST"});
    if(!response.ok)throw new Error(await parseError(response));
    const data=await response.json();onSampleReady(data.project,data.file);
  });}
  const steps=[{name:"가게 선택",done:!!selectedProjectId},{name:"파일 연결·반영",done:hasData},{name:"첫 지표 저장",done:completed}];
  return <details open={open} onToggle={e=>setOpen(e.currentTarget.open)} aria-label="첫 대시보드 안내" className="rounded-xl border bg-card p-5">
    <summary className="cursor-pointer font-semibold">{completed?"시작 안내 · 저장 지표가 준비되었습니다":"첫 대시보드를 만들어보세요"}</summary>
    <ol className="my-4 grid gap-2 sm:grid-cols-3" aria-label="시작 단계">{steps.map((s,i)=><li key={s.name} className="rounded-md border p-3 text-sm"><span className="mr-2 font-mono text-muted-foreground">{s.done?"✓":i+1}</span>{s.name}<span className="ml-2 text-xs text-muted-foreground">{s.done?"완료":"대기"}</span></li>)}</ol>
    <div className="mb-5 space-y-3 rounded-lg bg-secondary p-4"><p className="text-sm font-medium">파일이 없어도 먼저 경험해보세요</p><p className="text-xs leading-5 text-muted-foreground">별도의 샘플 가게에서 카드·현금·취소 거래 8행으로 시작합니다. 파일 원본 선택 → 자연어 질문 → 그래프 확인 → 저장 설정 순서로 진행합니다.</p><div className="flex flex-wrap gap-2"><Button disabled={busy} onClick={()=>void sample()}>{busy?"준비 중…":"샘플 데이터로 시작"}</Button>{!!selectedProjectId&&<Button variant="outline" disabled={busy} onClick={onOpenLibrary}>내 파일로 시작</Button>}</div><p className="text-[11px] text-muted-foreground">가상 데이터입니다. 다시 시작해도 같은 샘플 가게와 파일을 사용합니다.</p></div>
    {!selectedProjectId?<div className="space-y-3"><p className="text-sm">가게마다 장부와 대시보드를 따로 관리합니다. 첫 가게를 만들어 시작하세요.</p><Button onClick={onCreateStore}>첫 가게 만들기</Button></div>:<>
      {sources===null&&!error?<p role="status" className="text-sm">이 가게의 준비 상태를 확인하고 있습니다.</p>:<>
        {!completed&&<p className="mb-3 text-sm text-muted-foreground">파일을 연결하고 검토한 거래로 첫 지표를 만듭니다. 컬럼 이름을 외우거나 SQL을 작성할 필요가 없습니다.</p>}
        <div className="mb-4 flex flex-wrap gap-2"><Button variant="outline" onClick={onOpenTables}>{hasData?"장부·추가 파일 관리":"파일 연결·반영하러 가기"}</Button>{sources?.some(s=>s.row_count===0)&&<p className="self-center text-sm text-muted-foreground">빈 출처가 있습니다. 장부 관리의 업로드 이력에서 검토·반영을 이어가세요.</p>}</div>
        {!eligible.length&&<p className="text-sm text-muted-foreground">첫 지표 안내는 반영된 결제·취소 장부나 현금 장부를 사용합니다. 일반 통계 파일은 기존 지표 만들기 또는 AI 분석에서 출처와 계산 기준을 지정하세요.</p>}
        {!!eligible.length&&<fieldset disabled={busy} className="space-y-3">
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <label className="text-sm">첫 지표의 출처<select aria-label="첫 지표의 출처" className={field} value={source?.id||""} onChange={e=>setSourceId(e.target.value)}>{eligible.map(s=><option key={s.id} value={s.id}>{s.name} · {s.row_count}행</option>)}</select></label>
            <label className="text-sm">첫 지표 모양<select aria-label="첫 지표 모양" className={field} value={mode} onChange={e=>setMode(e.target.value)}><option value="daily">일별 결제·취소 금액 그래프</option><option value="total">장부의 전체 합계</option></select></label>
            <label className="text-sm">첫 지표 기간<select aria-label="첫 지표 기간" className={field} value={period} onChange={e=>setPeriod(e.target.value)}><option value="all">파일 전체 기간</option><option value="this_month">이번 달</option><option value="last_month">지난달</option><option value="last_30_days">최근 30일</option></select></label>
            <label className="text-sm">첫 지표 갱신<select aria-label="첫 지표 갱신" className={field} value={interval} onChange={e=>setInterval(Number(e.target.value))}><option value={3600}>매시간</option><option value={86400}>24시간마다</option><option value={0}>수동</option></select></label>
          </div>
          <label className="block text-sm">첫 지표 이름<input aria-label="첫 지표 이름" className={field} value={title} onChange={e=>setTitle(e.target.value)} maxLength={120}/></label>
          <p className="text-sm text-muted-foreground">선택한 장부만 원화로 합산합니다. 결제·취소 발생일 기준이며 수수료 차감 전입니다. 다른 결제수단이나 가게의 파일은 자동으로 포함되지 않습니다.</p>
          <div className="flex flex-wrap gap-2"><Button disabled={!source} onClick={calculate}>첫 지표 미리보기</Button><Button variant="outline" disabled={!source} onClick={()=>onStartChat(`${JSON.stringify(source?.name)} 장부의 전체 기간 결제·취소 금액을 발생일 기준 일별 막대그래프로 미리보기만 해줘. 원본 부호와 취소를 유지하고 수수료는 차감하지 마. 출처를 확인하고 저장은 아직 하지 마.`)}>이 출처로 자연어 질문 작성</Button></div>
        </fieldset>}
      </>}
    </>}
    {error&&<div className="mt-3 space-y-2"><p role="alert" className="text-sm text-destructive">{error}</p>{sources===null&&<Button variant="outline" onClick={()=>setRetry(v=>v+1)}>준비 상태 다시 확인</Button>}</div>}
    {result&&<div className="mt-4 space-y-3 border-t pt-4">
      {Array.isArray(result.data)?<EChartsChart chartType="bar" title={title} xKey="dimension" yKey="value" data={result.data as Record<string,unknown>[]} unit="KRW" height={220}/>:<p className="font-sans numeric text-lg">{exactMetricValue(result.value,"KRW")}</p>}
      <MetricAnalysisDialog title={title} data={result}/>
      <p className="text-xs text-muted-foreground">새 거래는 파일 반영 또는 직접 입력 후 다음 계산에 포함됩니다. 저장 후 위젯을 이동·크기 조절할 수 있습니다.</p>
      <Button disabled={busy||!title.trim()} onClick={save}>첫 지표 저장</Button>
    </div>}
  </details>;
}
