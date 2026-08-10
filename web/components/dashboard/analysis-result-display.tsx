"use client";

import { Loader2, Brain, CheckCircle2, ChevronDown, ChevronUp } from "lucide-react";
import { useState, useMemo } from "react";
import { cn } from "@/lib/utils";
import {
  Table,
  TableHeader,
  TableBody,
  TableRow,
  TableHead,
  TableCell,
} from "@/components/ui/table";
import type { Message, StreamingStep } from "@/app/lib/api";
import ReasoningSteps from "@/app/components/reasoning-steps";
import { RechartsChart } from "./recharts-chart";

const TOOL_LABELS: Record<string, string> = {
  profile_data: "데이터 구조 파악",
  query_data: "데이터 조회",
  detect_anomaly: "이상치 탐지",
  calculate_correlation: "상관관계 분석",
  generate_chart: "차트 생성",
};

type AnalysisResultDisplayProps = {
  result: Message | null;
  loading: boolean;
  streamingSteps: StreamingStep[];
  emptyMessage?: string;
  onSuggestionClick?: (suggestion: string) => void;
};

export function AnalysisResultDisplay({
  result,
  loading,
  streamingSteps,
  emptyMessage = "분석 결과가 여기에 표시됩니다.",
  onSuggestionClick,
}: AnalysisResultDisplayProps) {
  const [stepsExpanded, setStepsExpanded] = useState(false);
  const hasSteps = streamingSteps.length > 0;

  // Loading state
  if (loading) {
    return (
      <div className="space-y-4">
        <div className="bg-card border border-border rounded-xl px-5 py-4">
          <div className="flex items-center gap-3">
            <Loader2 className="h-5 w-5 animate-spin text-accent flex-shrink-0" />
            <span className="text-sm text-muted-foreground">
              {hasSteps
                ? `AI가 분석 중입니다... (${streamingSteps.length}단계 완료)`
                : "AI 연결 중..."}
            </span>
            {hasSteps && (
              <button
                type="button"
                onClick={() => setStepsExpanded((v) => !v)}
                className="flex items-center gap-1 text-xs text-accent hover:text-accent/80 transition-colors ml-auto"
              >
                <Brain className="h-3.5 w-3.5" />
                {stepsExpanded ? "접기" : "과정 보기"}
                {stepsExpanded ? (
                  <ChevronUp className="h-3 w-3" />
                ) : (
                  <ChevronDown className="h-3 w-3" />
                )}
              </button>
            )}
          </div>

          {hasSteps && stepsExpanded && (
            <div className="mt-3 pt-3 border-t border-border space-y-1.5">
              {streamingSteps.map((step, i) => {
                const label = TOOL_LABELS[step.tool_name] || step.tool_name;
                return (
                  <div key={i} className="flex items-center gap-2 text-xs">
                    <CheckCircle2 className="h-3.5 w-3.5 text-success flex-shrink-0" />
                    <span className="font-medium text-foreground">{label}</span>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </div>
    );
  }

  // Empty state
  if (!result) {
    return (
      <div className="flex items-center justify-center py-16 text-sm text-muted-foreground">
        {emptyMessage}
      </div>
    );
  }

  // Result display
  return (
    <div className="space-y-4 animate-in fade-in slide-in-from-bottom-4 duration-500">
      {/* Charts */}
      {result.charts && result.charts.length > 0 && (
        <div className="space-y-4">
          {result.charts.map((chart, idx) => (
            <RechartsChart
              key={idx}
              chartType={chart.chart_type as "line" | "bar" | "pie"}
              title={chart.title}
              xKey={chart.x_key}
              yKey={chart.y_key}
              data={chart.data}
            />
          ))}
        </div>
      )}

      {/* Data table */}
      {result.table_data && result.table_data.length > 0 && (
        <AnalysisTable data={result.table_data} />
      )}

      {/* Answer text */}
      {result.content && (
        <div className="bg-card border border-border rounded-xl px-5 py-4">
          <p className="text-sm text-foreground whitespace-pre-wrap leading-relaxed">
            {result.content.split("---SUGGESTIONS---")[0]?.trimEnd() || ""}
          </p>
        </div>
      )}

      {/* Suggestion buttons */}
      {result.suggestions && result.suggestions.length > 0 && onSuggestionClick && (
        <div className="flex flex-wrap gap-2 animate-in fade-in slide-in-from-bottom-2 duration-300">
          {result.suggestions.map((s, idx) => (
            <button
              key={idx}
              onClick={() => onSuggestionClick(s)}
              className="rounded-full px-3.5 py-1.5 text-xs font-medium bg-secondary text-secondary-foreground border border-border hover:border-accent hover:text-accent transition-all duration-200 hover:shadow-sm active:scale-[0.97]"
            >
              {s}
            </button>
          ))}
        </div>
      )}

      {/* Reasoning steps */}
      {result.steps && result.steps.length > 0 && (
        <ReasoningSteps steps={result.steps} />
      )}
    </div>
  );
}

function AnalysisTable({ data }: { data: Record<string, unknown>[] }) {
  const keys = Object.keys(data[0]);

  const numericCols = useMemo(() => {
    const set = new Set<string>();
    for (const key of keys) {
      const sample = data.slice(0, 5);
      const allNum = sample.every((r) => {
        const v = r[key];
        if (v === null || v === undefined || v === "") return true;
        return !isNaN(Number(v));
      });
      const hasVal = sample.some(
        (r) => r[key] !== null && r[key] !== undefined && r[key] !== ""
      );
      if (allNum && hasVal) set.add(key);
    }
    return set;
  }, [data, keys]);

  return (
    <div className="rounded-xl border border-border bg-card overflow-hidden">
      <Table>
        <TableHeader>
          <TableRow className="border-border hover:bg-transparent">
            {keys.map((key) => (
              <TableHead
                key={key}
                className={cn(
                  "whitespace-nowrap",
                  numericCols.has(key) && "text-right"
                )}
              >
                {key}
              </TableHead>
            ))}
          </TableRow>
        </TableHeader>
        <TableBody>
          {data.slice(0, 15).map((row, idx) => (
            <TableRow
              key={idx}
              className="border-border animate-in fade-in slide-in-from-left-1"
              style={{
                animationDelay: `${idx * 30}ms`,
                animationFillMode: "both",
              }}
            >
              {keys.map((key) => {
                const isNum = numericCols.has(key);
                const val = row[key];
                const display = String(val ?? "");
                return (
                  <TableCell
                    key={key}
                    className={cn(
                      "text-sm whitespace-nowrap",
                      isNum
                        ? "text-right font-semibold tabular-nums text-foreground"
                        : "text-foreground/90"
                    )}
                  >
                    {isNum && display && !isNaN(Number(display))
                      ? Number(display).toLocaleString()
                      : display}
                  </TableCell>
                );
              })}
            </TableRow>
          ))}
        </TableBody>
      </Table>
      {data.length > 15 && (
        <div className="px-4 py-3 text-sm text-muted-foreground border-t border-border bg-secondary/30">
          {data.length}행 중 15행 표시
        </div>
      )}
    </div>
  );
}
