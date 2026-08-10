"use client";

import { FormEvent, useEffect, useRef, useState } from "react";
import { Send, Loader2, Sparkles, CheckCircle2, ChevronDown, ChevronUp, Brain, Paperclip, X } from "lucide-react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import type { Message, StreamingStep } from "../lib/api";
import MessageBubble from "./message-bubble";

const QUICK_PROMPTS = [
  "어떤 장부들이 있어?",
  "전체 데이터 보여줘",
  "월별 매출 추이 보여줘",
  "카테고리별 매출 비율 차트",
  "매출 장부 만들어줘",
];

const TOOL_LABELS: Record<string, string> = {
  list_tables: "장부 목록 확인",
  describe_table: "장부 구조 파악",
  query_data: "데이터 조회",
  insert_rows: "데이터 추가",
  update_rows: "데이터 수정",
  delete_rows: "데이터 삭제",
  generate_chart: "차트 생성",
  recommend_charts: "차트 추천",
  create_table: "장부 생성",
  alter_table: "구조 변경",
  cross_query: "교차 분석",
  import_file: "파일 가져오기",
};

function summarizeToolInput(toolName: string, input: Record<string, unknown>): string {
  const parts: string[] = [];
  // Show which table is being accessed
  if (input.table_name) parts.push(`📋 ${input.table_name}`);
  if (toolName === "query_data") {
    if (input.group_by) parts.push(`group: ${input.group_by}`);
    if (input.operation && input.operation !== "none") parts.push(`${input.operation}`);
    if (input.order_by) parts.push(`sort: ${input.order_by}`);
    if (input.limit) parts.push(`top ${input.limit}`);
  } else if (toolName === "generate_chart") {
    if (input.chart_type) parts.push(`${input.chart_type}`);
    if (input.title) parts.push(`${String(input.title).slice(0, 30)}`);
  } else if (toolName === "insert_rows") {
    const rows = input.rows as unknown[];
    if (rows) parts.push(`${rows.length}건`);
  } else if (toolName === "update_rows") {
    if (input.set_values) parts.push(`${Object.keys(input.set_values as object).join(", ")}`);
  } else if (toolName === "delete_rows") {
    const where = input.where as unknown[];
    if (where) parts.push(`${where.length}개 조건`);
  } else if (toolName === "create_table") {
    if (input.table_name) parts.push(`${input.table_name}`);
    const cols = input.columns as unknown[];
    if (cols) parts.push(`${cols.length}개 컬럼`);
  } else if (toolName === "alter_table") {
    if (input.operation) parts.push(`${input.operation}`);
    if (input.column_name) parts.push(`${input.column_name}`);
  } else if (toolName === "cross_query") {
    const tables = input.tables as string[];
    if (tables) parts.push(tables.join(" + "));
  } else if (toolName === "import_file") {
    if (input.action) parts.push(`${input.action}`);
  }
  return parts.length > 0 ? parts.join(", ") : "";
}

type ChatPanelProps = {
  messages: Message[];
  onSend: (message: string, file?: File | null) => Promise<void>;
  loading: boolean;
  disabled: boolean;
  streamingSteps?: StreamingStep[];
  streamError?: string | null;
  onPinChart?: (chart: import("../lib/api").ChartData) => void;
};

const ALLOWED_FILE_TYPES = ".csv,.xlsx,.xls";

export default function ChatPanel({ messages, onSend, loading, disabled, streamingSteps, streamError, onPinChart }: ChatPanelProps) {
  const [input, setInput] = useState("");
  const [attachedFile, setAttachedFile] = useState<File | null>(null);
  const [stepsExpanded, setStepsExpanded] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, loading, streamingSteps]);

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    if (!input.trim() || loading || disabled) return;
    const msg = input;
    const file = attachedFile;
    setInput("");
    setAttachedFile(null);
    await onSend(msg, file);
  };

  const handleQuickPrompt = async (prompt: string) => {
    if (loading || disabled) return;
    await onSend(prompt);
  };

  const handleFileSelect = () => {
    fileInputRef.current?.click();
  };

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) setAttachedFile(file);
    // Reset so the same file can be re-selected
    e.target.value = "";
  };

  const hasSteps = streamingSteps && streamingSteps.length > 0;

  return (
    <div className="flex flex-col h-full">
      {/* Messages area */}
      <div className="flex-1 overflow-y-auto px-4 lg:px-6 py-4 space-y-6">
        {messages.length === 0 && !loading ? (
          <div className="flex flex-col items-center justify-center h-full text-center py-12">
            <div className="h-16 w-16 rounded-2xl bg-secondary flex items-center justify-center mb-4">
              <Sparkles className="h-8 w-8 text-accent" />
            </div>
            <h3 className="text-lg font-semibold text-foreground mb-2">
              데이터에 대해 무엇이든 물어보세요
            </h3>
            <p className="text-sm text-muted-foreground mb-6 max-w-md">
              AI가 데이터를 단계별로 분석하여 인사이트와 시각화를 자동으로 생성합니다.
            </p>
            <div className="flex flex-wrap gap-2 justify-center max-w-lg">
              {QUICK_PROMPTS.map((prompt) => (
                <button
                  key={prompt}
                  onClick={() => handleQuickPrompt(prompt)}
                  disabled={disabled}
                  className="rounded-full px-3.5 py-1.5 text-xs font-medium bg-secondary text-secondary-foreground border border-border hover:border-accent/50 hover:text-accent transition-all duration-200 hover:shadow-sm active:scale-[0.97] disabled:opacity-50"
                >
                  {prompt}
                </button>
              ))}
            </div>
          </div>
        ) : (
          messages.map((msg, idx) => {
            const isLastAssistant =
              msg.role === "assistant" && idx === messages.length - 1;
            return (
              <MessageBubble
                key={msg.message_id}
                message={msg}
                showSuggestions={isLastAssistant && !loading}
                onPinChart={onPinChart}
                onSuggestionClick={handleQuickPrompt}
              />
            );
          })
        )}

        {/* Streaming loading indicator */}
        {loading && (
          <div className="flex gap-3 animate-in fade-in slide-in-from-bottom-3 duration-500">
            <div className="flex-shrink-0 h-8 w-8 rounded-full bg-secondary flex items-center justify-center">
              <Loader2 className="h-4 w-4 text-accent animate-spin" />
            </div>
            <div className="bg-card border border-border rounded-2xl rounded-tl-md px-4 py-3 max-w-[80%]">
              <div className="flex items-center gap-2">
                <Loader2 className="h-3.5 w-3.5 animate-spin text-accent flex-shrink-0" />
                <span className="text-xs text-muted-foreground">
                  {hasSteps
                    ? `분석 중... (${streamingSteps.length}단계 완료)`
                    : "연결 중..."}
                </span>
                {hasSteps && (
                  <button
                    type="button"
                    onClick={() => setStepsExpanded((v) => !v)}
                    className="flex items-center gap-0.5 text-xs text-accent hover:text-accent/80 transition-colors ml-1"
                  >
                    <Brain className="h-3 w-3" />
                    <span>{stepsExpanded ? "접기" : "생각보기"}</span>
                    {stepsExpanded ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}
                  </button>
                )}
              </div>

              {hasSteps && stepsExpanded && (
                <div className="mt-2 pt-2 border-t border-border space-y-1">
                  {streamingSteps.map((step, i) => {
                    const label = TOOL_LABELS[step.tool_name] || step.tool_name;
                    const detail = summarizeToolInput(step.tool_name, step.tool_input);
                    return (
                      <div key={i} className="flex items-center gap-2 text-xs">
                        <CheckCircle2 className="h-3.5 w-3.5 text-success flex-shrink-0" />
                        <span className="font-medium text-foreground">{label}</span>
                        {detail && (
                          <span className="text-muted-foreground truncate">{detail}</span>
                        )}
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          </div>
        )}

        {streamError && (
          <div className="mx-4 mb-2 rounded-lg border border-destructive/50 bg-destructive/10 p-3 text-sm text-destructive">
            {streamError}
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      {/* Input area */}
      <div className="border-t border-border bg-background px-4 lg:px-6 py-3">
        {/* Attached file indicator */}
        {attachedFile && (
          <div className="flex items-center gap-2 mb-2 px-1">
            <span className="inline-flex items-center gap-1.5 rounded-lg bg-secondary border border-border px-2.5 py-1 text-xs font-medium text-foreground">
              <Paperclip className="h-3 w-3 text-muted-foreground" />
              {attachedFile.name}
              <button
                type="button"
                onClick={() => setAttachedFile(null)}
                className="ml-0.5 text-muted-foreground hover:text-destructive transition-colors"
              >
                <X className="h-3 w-3" />
              </button>
            </span>
          </div>
        )}
        <form onSubmit={handleSubmit} className="flex items-end gap-2">
          <input
            ref={fileInputRef}
            type="file"
            accept={ALLOWED_FILE_TYPES}
            onChange={handleFileChange}
            className="hidden"
          />
          <Button
            type="button"
            variant="ghost"
            size="icon"
            onClick={handleFileSelect}
            disabled={disabled || loading}
            className="rounded-xl shrink-0 text-muted-foreground hover:text-accent"
            title="CSV/XLSX 파일 첨부"
          >
            <Paperclip className="h-5 w-5" />
          </Button>
          <textarea
            ref={textareaRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                handleSubmit(e);
              }
            }}
            placeholder={disabled ? "프로젝트를 선택하세요" : "데이터를 추가/수정/삭제하거나 분석을 요청하세요..."}
            rows={1}
            disabled={disabled || loading}
            className="flex-1 rounded-xl border border-input bg-secondary px-4 py-2.5 text-sm text-foreground placeholder:text-muted-foreground resize-none focus:outline-none focus:ring-2 focus:ring-ring/50 focus:border-accent disabled:opacity-50 transition-all duration-200 max-h-32"
          />
          <Button
            type="submit"
            disabled={loading || disabled || !input.trim()}
            size="icon"
            className="rounded-xl shrink-0 bg-accent text-accent-foreground hover:bg-accent/90"
          >
            {loading ? (
              <Loader2 className="h-5 w-5 animate-spin" />
            ) : (
              <Send className="h-5 w-5" />
            )}
          </Button>
        </form>
      </div>
    </div>
  );
}
