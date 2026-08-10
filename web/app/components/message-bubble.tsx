"use client";

import { memo } from "react";
import { User, Bot, Plus, Pencil, Trash2, Pin, TableProperties, Database, Columns3, FileUp } from "lucide-react";
import { cn } from "@/lib/utils";
import {
  Table,
  TableHeader,
  TableBody,
  TableRow,
  TableHead,
  TableCell,
} from "@/components/ui/table";
import type { Message, AgentStep, ChartData } from "../lib/api";
import ReasoningSteps from "./reasoning-steps";
import { RechartsChart } from "@/components/dashboard/recharts-chart";

type MessageBubbleProps = {
  message: Message;
  showSuggestions?: boolean;
  onSuggestionClick?: (suggestion: string) => void;
  onPinChart?: (chart: ChartData) => void;
};

function MessageBubble({
  message,
  showSuggestions,
  onSuggestionClick,
  onPinChart,
}: MessageBubbleProps) {
  const isUser = message.role === "user";

  // Strip any leftover suggestions marker from content display
  const displayContent = message.content?.split("---SUGGESTIONS---")[0]?.trimEnd() || "";

  const suggestions = message.suggestions;
  const hasSuggestions = showSuggestions && suggestions && suggestions.length > 0;

  return (
    <div className={cn(
      "flex gap-3 animate-in fade-in slide-in-from-bottom-3 duration-500",
      isUser && "flex-row-reverse",
    )}>
      {/* Avatar */}
      <div
        className={cn(
          "flex-shrink-0 h-8 w-8 rounded-full flex items-center justify-center",
          isUser ? "bg-accent" : "bg-secondary"
        )}
      >
        {isUser ? (
          <User className="h-4 w-4 text-accent-foreground" />
        ) : (
          <Bot className="h-4 w-4 text-foreground" />
        )}
      </div>

      {/* Content */}
      <div className={cn("flex-1 min-w-0", isUser && "flex flex-col items-end")}>
        {isUser ? (
          <div className="bg-accent text-accent-foreground rounded-2xl rounded-tr-md px-4 py-2.5 max-w-[80%]">
            <p className="text-sm whitespace-pre-wrap">{message.content}</p>
          </div>
        ) : (
          <div className="max-w-full space-y-3">
            {/* Mutation badges */}
            <MutationBadges steps={message.steps} />

            {/* Charts */}
            {message.charts && message.charts.length > 0 && (
              <div className="space-y-3">
                {message.charts.map((chart, idx) => (
                  <div key={idx} className="relative group/chart">
                    <RechartsChart
                      chartType={chart.chart_type as "line" | "bar" | "pie"}
                      title={chart.title}
                      xKey={chart.x_key}
                      yKey={chart.y_key}
                      data={chart.data}
                      height={260}
                    />
                    {onPinChart && (
                      <button
                        onClick={() => onPinChart(chart)}
                        aria-label="대시보드에 고정"
                        className="absolute top-2 right-2 opacity-0 group-hover/chart:opacity-100 transition-opacity bg-background/80 backdrop-blur-sm border border-border rounded-lg px-2.5 py-1.5 text-xs font-medium text-muted-foreground hover:text-accent hover:border-accent flex items-center gap-1.5"
                      >
                        <Pin className="h-3 w-3" />
                        고정
                      </button>
                    )}
                  </div>
                ))}
              </div>
            )}

            {/* Data table */}
            {message.table_data && message.table_data.length > 0 && (
              <div className="rounded-xl border border-border bg-card overflow-hidden">
                <Table>
                  <TableHeader>
                    <TableRow className="border-border hover:bg-transparent">
                      {Object.keys(message.table_data[0]).map((key) => (
                        <TableHead
                          key={key}
                          className="text-xs font-semibold text-muted-foreground uppercase tracking-wider"
                        >
                          {key}
                        </TableHead>
                      ))}
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {message.table_data.slice(0, 15).map((row, idx) => (
                      <TableRow key={idx} className="border-border">
                        {Object.values(row).map((val, vIdx) => (
                          <TableCell
                            key={vIdx}
                            className="text-sm text-foreground font-mono"
                          >
                            {String(val ?? "")}
                          </TableCell>
                        ))}
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
                {message.table_data.length > 15 && (
                  <div className="px-3 py-2 text-xs text-muted-foreground border-t border-border">
                    {message.table_data.length}행 중 15행 표시
                  </div>
                )}
              </div>
            )}

            {/* Answer text */}
            {displayContent && (
              <div className="bg-card border border-border rounded-2xl rounded-tl-md px-4 py-3">
                <p className="text-sm text-foreground whitespace-pre-wrap leading-relaxed">
                  {displayContent}
                </p>
                {/* Referenced tables */}
                <ReferencedTables steps={message.steps} />
              </div>
            )}

            {/* Suggestion buttons */}
            {hasSuggestions && (
              <div className="flex flex-wrap gap-2 animate-in fade-in slide-in-from-bottom-2 duration-300">
                {suggestions.map((s, idx) => (
                  <button
                    key={idx}
                    onClick={() => onSuggestionClick?.(s)}
                    className="rounded-full px-3.5 py-1.5 text-xs font-medium bg-secondary text-secondary-foreground border border-border hover:border-accent/50 hover:text-accent transition-all duration-200 hover:shadow-sm active:scale-[0.97]"
                  >
                    {s}
                  </button>
                ))}
              </div>
            )}

            {/* Reasoning steps */}
            {message.steps && message.steps.length > 0 && (
              <ReasoningSteps steps={message.steps} />
            )}
          </div>
        )}
      </div>
    </div>
  );
}

function ReferencedTables({ steps }: { steps?: AgentStep[] | null }) {
  if (!steps) return null;

  const tableNames = new Set<string>();
  for (const step of steps) {
    if (step.type === "tool_call" && step.tool_input) {
      const name = step.tool_input.table_name as string | undefined;
      if (name) tableNames.add(name);
    }
  }

  if (tableNames.size === 0) return null;

  return (
    <div className="mt-3 pt-2.5 border-t border-border/50 flex items-center gap-2 flex-wrap">
      <span className="text-[11px] text-muted-foreground font-medium">참조 장부</span>
      {Array.from(tableNames).map((name) => (
        <span
          key={name}
          className="inline-flex items-center gap-1 rounded-md bg-secondary text-secondary-foreground px-2 py-0.5 text-[11px] font-medium"
        >
          <TableProperties className="h-3 w-3" />
          {name}
        </span>
      ))}
    </div>
  );
}

function MutationBadges({ steps }: { steps?: AgentStep[] | null }) {
  if (!steps) return null;

  const BADGE_TOOLS = new Set([
    "insert_rows", "update_rows", "delete_rows",
    "create_table", "alter_table", "import_file",
  ]);

  const mutations = steps.filter(
    (s) =>
      s.type === "tool_call" &&
      s.tool_name &&
      BADGE_TOOLS.has(s.tool_name) &&
      s.tool_output &&
      !s.tool_output.error
  );

  if (mutations.length === 0) return null;

  return (
    <div className="flex flex-wrap gap-2">
      {mutations.map((step, idx) => {
        const count = String(step.tool_output?.affected_rows ?? step.tool_output?.inserted_count ?? step.tool_output?.row_count ?? "?");
        if (step.tool_name === "insert_rows") {
          return (
            <span
              key={idx}
              className="inline-flex items-center gap-1.5 rounded-full bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 border border-emerald-500/20 px-3 py-1 text-xs font-medium"
            >
              <Plus className="h-3 w-3" />
              {count}건 추가됨
            </span>
          );
        }
        if (step.tool_name === "update_rows") {
          return (
            <span
              key={idx}
              className="inline-flex items-center gap-1.5 rounded-full bg-blue-500/10 text-blue-600 dark:text-blue-400 border border-blue-500/20 px-3 py-1 text-xs font-medium"
            >
              <Pencil className="h-3 w-3" />
              {count}건 수정됨
            </span>
          );
        }
        if (step.tool_name === "delete_rows") {
          return (
            <span
              key={idx}
              className="inline-flex items-center gap-1.5 rounded-full bg-red-500/10 text-red-600 dark:text-red-400 border border-red-500/20 px-3 py-1 text-xs font-medium"
            >
              <Trash2 className="h-3 w-3" />
              {count}건 삭제됨
            </span>
          );
        }
        if (step.tool_name === "create_table") {
          const tableName = step.tool_output?.table_name || step.tool_input?.table_name || "";
          return (
            <span
              key={idx}
              className="inline-flex items-center gap-1.5 rounded-full bg-violet-500/10 text-violet-600 dark:text-violet-400 border border-violet-500/20 px-3 py-1 text-xs font-medium"
            >
              <Database className="h-3 w-3" />
              장부 생성됨{tableName ? `: ${tableName}` : ""}
            </span>
          );
        }
        if (step.tool_name === "alter_table") {
          const op = step.tool_input?.operation || "";
          return (
            <span
              key={idx}
              className="inline-flex items-center gap-1.5 rounded-full bg-amber-500/10 text-amber-600 dark:text-amber-400 border border-amber-500/20 px-3 py-1 text-xs font-medium"
            >
              <Columns3 className="h-3 w-3" />
              구조 변경됨{op ? ` (${op})` : ""}
            </span>
          );
        }
        if (step.tool_name === "import_file") {
          const importCount = String(step.tool_output?.row_count ?? step.tool_output?.rows_inserted ?? "?");
          return (
            <span
              key={idx}
              className="inline-flex items-center gap-1.5 rounded-full bg-cyan-500/10 text-cyan-600 dark:text-cyan-400 border border-cyan-500/20 px-3 py-1 text-xs font-medium"
            >
              <FileUp className="h-3 w-3" />
              {importCount}건 가져오기 완료
            </span>
          );
        }
        return null;
      })}
    </div>
  );
}

export default memo(MessageBubble);
