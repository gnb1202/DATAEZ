"use client";

import { useEffect, useState } from "react";
import { useDashboard } from "@/app/contexts/dashboard-context";
import { GettingStarted } from "../getting-started";
import type { SampleReady } from "../sample-workspace-actions";

export function GettingStartedSection(props: {
  onCreateStore: () => void;
  onOpenTables: () => void;
  onCreated: () => void;
  onStartChat: (prompt: string) => void;
  onSampleReady: SampleReady;
  onOpenLibrary: () => void;
}) {
  const { selectedProjectId, apiFetch } = useDashboard();
  const [completed, setCompleted] = useState(false);
  useEffect(() => {
    let active = true;
    if (!selectedProjectId) return;
    void apiFetch(`/api/dashboard/widgets?project_id=${selectedProjectId}`).then(async res => {
      if (!res.ok) return;
      const data = await res.json();
      if (active) setCompleted((data.widgets || []).some((widget: { widget_data: Record<string, unknown> }) => !!widget.widget_data.metric_definition));
    }).catch(() => {});
    return () => { active = false; };
  }, [selectedProjectId, apiFetch]);

  return <div className="mx-auto max-w-5xl space-y-6">
    <div><h2 className="text-xl font-bold">가게와 데이터 준비하기</h2><p className="mt-2 text-sm text-muted-foreground">내 파일을 연결하거나 샘플 데이터로 첫 분석을 시작하세요.</p></div>
    <GettingStarted completed={completed} {...props} />
  </div>;
}
