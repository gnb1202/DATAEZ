"use client";

import { useDashboard } from "@/app/contexts/dashboard-context";
import { Button } from "@/components/ui/button";
import { MetricCreateForm } from "../metric-create-form";
import { StoreMetricForm } from "../store-metric-form";

export function MetricBuilderSection({ onCreated, onPrepareData }: { onCreated: () => void; onPrepareData: () => void }) {
  const { selectedProjectId } = useDashboard();
  return <div className="mx-auto max-w-5xl space-y-6">
    <div>
      <h2 className="text-xl font-bold">직접 지표 만들기</h2>
      <p className="mt-2 text-sm leading-6 text-muted-foreground">장부와 계산 기준을 선택해 지표를 만드세요. 저장한 지표는 대시보드에서 확인하고 다시 계산할 수 있습니다.</p>
    </div>
    {selectedProjectId ? <div className="space-y-4"><MetricCreateForm onCreated={onCreated} /><StoreMetricForm onCreated={onCreated} /></div> : <div className="rounded-xl border border-dashed border-border px-5 py-12 text-center">
      <p className="mb-4 text-sm text-muted-foreground">지표를 저장할 가게와 장부를 먼저 준비하세요.</p>
      <Button onClick={onPrepareData}>가게와 데이터 준비하기</Button>
    </div>}
  </div>;
}
