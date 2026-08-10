"use client";

import { useState } from "react";
import { ChevronDown, ChevronRight, Search, BarChart3, AlertTriangle, Database, GitBranch, CheckCircle2, Wrench } from "lucide-react";
import { cn } from "@/lib/utils";
import type { AgentStep } from "../lib/api";

const TOOL_ICONS: Record<string, typeof Search> = {
  profile_data: Database,
  query_data: Search,
  detect_anomaly: AlertTriangle,
  calculate_correlation: GitBranch,
  generate_chart: BarChart3,
};

const TOOL_LABELS: Record<string, string> = {
  profile_data: "데이터 구조 파악",
  query_data: "데이터 조회",
  detect_anomaly: "이상치 탐지",
  calculate_correlation: "상관관계 분석",
  generate_chart: "차트 생성",
};

function StepDetail({ step }: { step: AgentStep }) {
  const [expanded, setExpanded] = useState(false);

  if (step.type === "answer") return null;

  const Icon = (step.tool_name && TOOL_ICONS[step.tool_name]) || Wrench;
  const label = (step.tool_name && TOOL_LABELS[step.tool_name]) || step.tool_name || "Tool";

  return (
    <div className="group">
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center gap-2 py-1.5 px-2 rounded-md hover:bg-secondary/50 transition-all duration-200 text-left"
      >
        <Icon className="h-3.5 w-3.5 text-accent flex-shrink-0" />
        <span className="text-xs font-medium text-foreground flex-1">{label}</span>
        <CheckCircle2 className="h-3.5 w-3.5 text-success flex-shrink-0" />
        {expanded ? (
          <ChevronDown className="h-3 w-3 text-muted-foreground" />
        ) : (
          <ChevronRight className="h-3 w-3 text-muted-foreground" />
        )}
      </button>

      {expanded && (
        <div className="ml-6 mt-1 mb-2 space-y-1.5">
          {step.tool_input && Object.keys(step.tool_input).length > 0 && (
            <div>
              <p className="text-[10px] font-semibold text-muted-foreground uppercase mb-0.5">입력</p>
              <pre className="text-[11px] text-muted-foreground bg-secondary rounded-md p-2 overflow-x-auto whitespace-pre-wrap font-mono">
                {JSON.stringify(step.tool_input, null, 2)}
              </pre>
            </div>
          )}
          {step.tool_output && Object.keys(step.tool_output).length > 0 && (
            <div>
              <p className="text-[10px] font-semibold text-muted-foreground uppercase mb-0.5">결과</p>
              <pre className="text-[11px] text-muted-foreground bg-secondary rounded-md p-2 overflow-x-auto whitespace-pre-wrap max-h-40 font-mono">
                {JSON.stringify(step.tool_output, null, 2).slice(0, 1000)}
                {JSON.stringify(step.tool_output).length > 1000 ? "\n..." : ""}
              </pre>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export default function ReasoningSteps({ steps }: { steps: AgentStep[] }) {
  const [collapsed, setCollapsed] = useState(true);

  const toolSteps = steps.filter((s) => s.type === "tool_call");
  if (toolSteps.length === 0) return null;

  return (
    <div className="rounded-xl border border-border bg-card overflow-hidden">
      <button
        onClick={() => setCollapsed(!collapsed)}
        className="w-full flex items-center gap-2 px-3 py-2 hover:bg-secondary/50 transition-colors"
      >
        <div className="flex items-center gap-1.5 flex-1">
          <div className="h-5 w-5 rounded-full bg-secondary flex items-center justify-center">
            <Wrench className="h-3 w-3 text-accent" />
          </div>
          <span className="text-xs font-semibold text-foreground">
            추론 과정 ({toolSteps.length}단계)
          </span>
        </div>
        {collapsed ? (
          <ChevronRight className="h-4 w-4 text-muted-foreground" />
        ) : (
          <ChevronDown className="h-4 w-4 text-muted-foreground" />
        )}
      </button>

      {!collapsed && (
        <div className="border-t border-border px-2 py-1">
          {toolSteps.map((step, idx) => (
            <StepDetail key={idx} step={step} />
          ))}
        </div>
      )}
    </div>
  );
}
