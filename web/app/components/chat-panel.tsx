"use client";

import { FormEvent, useEffect, useRef, useState } from "react";
import { Send, Loader2, Sparkles, CheckCircle2, ChevronDown, ChevronUp, Brain, Paperclip, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import type { Message, StreamingStep } from "../lib/api";
import type { Composer } from "../hooks/use-workspace-analysis";
import { referenceScope, referenceKey } from "../lib/file-library";
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
  search_library_files: "보관함 파일 찾기",
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
  composer?: Composer;
  onOpenLibrary?: (search?: string) => void;
  onComposerChange?: (value: Composer) => void;
  onOpenResult?: (messageId: string) => void;
  draft?: {id:string;text:string}|null;
  onDraftConsumed?: () => void;
  messages: Message[];
  onSend: (message: string, file?: File | null) => Promise<void>;
  loading: boolean;
  disabled: boolean;
  streamingSteps?: StreamingStep[];
  streamingAnswer?: string;
  streamError?: string | null;
  onStop?: () => void;
  onPinChart?: (chart: import("../lib/api").ChartData) => void;
};

const ALLOWED_FILE_TYPES = ".csv,.xlsx,.xls";

export default function ChatPanel({ composer, onComposerChange, onOpenLibrary, onOpenResult, draft, onDraftConsumed, messages, onSend, loading, disabled, streamingSteps, streamingAnswer, streamError, onStop, onPinChart }: ChatPanelProps) {
  const [localInput, setLocalInput] = useState("");
  const input = composer?.text ?? localInput;
  const setInput = (text: string) => {
    if (onComposerChange && composer) onComposerChange({ ...composer, text });
    else setLocalInput(text);
  };
  // Legacy callers inject a draft; the workspace uses a controlled composer.
  useEffect(() => { if (draft) {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- synchronize an explicit external draft
    setLocalInput(draft.text); onDraftConsumed?.();
  } }, [draft, onDraftConsumed]);
  const [localFile, setLocalFile] = useState<File | null>(null);
  const attachedFile = composer ? composer.file : localFile;
  const setAttachedFile = (file: File | null) => {
    if (onComposerChange && composer) onComposerChange({ ...composer, file });
    else setLocalFile(file);
  };
  const [stepsExpanded, setStepsExpanded] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    const region = scrollRef.current;
    region?.scrollTo({ top: region.scrollHeight, behavior: "instant" });
  }, [messages, loading, streamingSteps, streamingAnswer]);

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    if (!input.trim() || loading || disabled) return;
    const msg = input;
    const file = attachedFile;
    if (!composer) { setLocalInput(""); setLocalFile(null); }
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
    <div className="flex min-h-0 flex-col h-full">
      {/* Messages area */}
      <div ref={scrollRef} className="min-h-0 flex-1 overflow-y-auto overscroll-contain px-4 py-5 space-y-6">
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
                onOpenResult={onOpenResult}
                onOpenLibrary={onOpenLibrary}
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
                {onStop && (
                  <button
                    type="button"
                    onClick={onStop}
                    className="ml-auto text-xs text-muted-foreground hover:text-destructive transition-colors"
                  >
                    중지
                  </button>
                )}
              </div>

              {/* Answer text as it streams in */}
              {streamingAnswer && (
                <p className="mt-2 text-sm leading-relaxed text-foreground whitespace-pre-wrap">
                  {streamingAnswer}
                  <span className="ml-0.5 inline-block h-4 w-[2px] translate-y-0.5 bg-accent animate-pulse" />
                </p>
              )}

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
          <div role="status" className="mb-2 rounded-lg border border-destructive/50 bg-destructive/10 p-3 text-sm text-destructive">
            {streamError}
          </div>
        )}


      </div>

      {/* Input area */}
      <div className="shrink-0 border-t border-border bg-[var(--chat)] px-3 py-3">
        {onOpenLibrary && <div className="mb-2 flex items-center justify-between gap-2"><button type="button" disabled={disabled || loading || !!attachedFile} onClick={() => onOpenLibrary()} className="rounded px-1 py-1 text-xs text-accent hover:underline disabled:opacity-40">보관함에서 선택</button><span className="text-[10px] text-muted-foreground">{attachedFile ? "기기에서 첨부됨" : "계정에 저장된 파일 사용"}</span></div>}
        {!!composer?.libraryFiles?.length && <div className="mb-3 space-y-2" aria-label="선택한 보관 파일"><div className="flex max-h-28 flex-wrap gap-1 overflow-auto">{composer.libraryFiles.map((ref) => <span key={referenceKey(ref)} className="inline-flex max-w-full items-center gap-1 rounded-md border border-border bg-secondary px-2 py-1 text-xs"><span className="truncate" title={`${ref.project_name} · ${ref.table_name || "문서"}`}>{ref.filename} · {ref.project_name} · {referenceScope(ref)}</span><button type="button" aria-label={`${ref.filename} 선택 해제`} disabled={loading} onClick={() => onComposerChange?.({ ...composer, libraryFiles: composer.libraryFiles?.filter((item) => referenceKey(item) !== referenceKey(ref)) })}><X size={13} /></button></span>)}</div><p className="text-[10px] leading-4 text-muted-foreground">표시된 파일별 범위로 분석합니다. 선택은 다음 질문에도 유지됩니다.</p></div>}
        {/* Attached file indicator */}
        {attachedFile && (
          <div className="flex items-center gap-2 mb-2 px-1">
            <span className="inline-flex items-center gap-1.5 rounded-lg bg-secondary border border-border px-2.5 py-1 text-xs font-medium text-foreground">
              <Paperclip className="h-3 w-3 text-muted-foreground" />
              {attachedFile.name}
              <button
                type="button"
                aria-label="첨부 파일 제거"
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
            disabled={disabled || loading || !!composer?.libraryFiles?.length}
            className="rounded-xl shrink-0 text-muted-foreground hover:text-accent"
            title="CSV/XLSX 파일 첨부"
            aria-label="CSV/XLSX 파일 첨부"
          >
            <Paperclip className="h-5 w-5" />
          </Button>
          <textarea
            aria-label="분석 요청"
            ref={textareaRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing && e.keyCode !== 229) {
                e.preventDefault();
                handleSubmit(e);
              }
            }}
            placeholder={disabled ? "가게를 선택하세요" : "매출에 대해 물어보세요…"}
            rows={1}
            disabled={disabled || loading}
            className="min-w-0 flex-1 rounded-xl border border-input bg-[var(--surface-input)] px-3 py-2.5 text-sm text-foreground placeholder:text-muted-foreground resize-none focus:outline-none focus:ring-2 focus:ring-ring/50 focus:border-accent disabled:opacity-50 transition-all duration-200 max-h-32"
          />
          <Button
            type="submit"
            aria-label="분석 요청 보내기"
            disabled={loading || disabled || !input.trim()}
            size="icon"
            className="rounded-xl shrink-0 bg-primary text-primary-foreground hover:bg-[var(--action-hover)]"
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
