"use client";

import { useSyncExternalStore } from "react";
import { X, MessageSquare } from "lucide-react";
import ChatPanel from "@/app/components/chat-panel";
import type { useWorkspaceAnalysis } from "@/app/hooks/use-workspace-analysis";
import { Sheet, SheetContent, SheetDescription, SheetTitle } from "@/components/ui/sheet";

const query = "(max-width: 1100px)";
const subscribe = (callback: () => void) => {
  const media = window.matchMedia(query);
  media.addEventListener("change", callback);
  return () => media.removeEventListener("change", callback);
};

export function ChatDock({ analysis, open, onOpenChange, onOpenResult, storeName, disabled, onOpenLibrary }: {
  analysis: ReturnType<typeof useWorkspaceAnalysis>; open: boolean; onOpenChange: (value: boolean) => void;
  onOpenLibrary: (search?: string) => void; onOpenResult: (id: string) => void; storeName: string; disabled: boolean;
}) {
  const narrow = useSyncExternalStore(subscribe, () => window.matchMedia(query).matches, () => false);
  const panel = <ChatPanel composer={analysis.composer} onComposerChange={analysis.setComposer} messages={analysis.messages}
    onOpenLibrary={onOpenLibrary} onSend={analysis.send} loading={analysis.loading} disabled={disabled || analysis.messageLoading}
    streamingSteps={analysis.stream.streamingSteps} streamingAnswer={analysis.stream.streamingAnswer}
    streamError={analysis.error} onStop={analysis.stop}
    onReviewConversation={analysis.recoveryAvailable ? () => void analysis.reviewCurrentConversation() : undefined} recoveryNotice={analysis.recoveryNotice}
    onOpenResult={(id) => { onOpenResult(id); if (narrow) onOpenChange(false); }} />;
  if (narrow) return <Sheet open={open} onOpenChange={onOpenChange}>
    <SheetContent id="workspace-chat" className="w-full gap-0 bg-[var(--chat)] sm:max-w-[440px]" onCloseAutoFocus={(event) => { event.preventDefault(); document.getElementById("workspace-chat-toggle")?.focus(); }}>
      <div className="border-b border-border p-5 pr-12"><SheetTitle>AI 채팅</SheetTitle><SheetDescription className="mt-1 truncate text-xs">현재 작업 가게 · {storeName}</SheetDescription></div>
      {analysis.messageLoading && <p role="status" className="px-4 pt-3 text-xs text-muted-foreground">대화를 불러오는 중…</p>}
      <div className="min-h-0 flex-1">{panel}</div>
    </SheetContent>
  </Sheet>;
  return <aside id="workspace-chat" aria-label="AI 채팅" hidden={!open} className={open ? "flex w-[380px] min-w-0 shrink-0 flex-col border-l border-border bg-[var(--chat)] 2xl:w-[408px]" : "hidden"}>
    <div className="flex h-[76px] shrink-0 items-center justify-between border-b border-border px-5">
      <div className="min-w-0"><h2 className="flex items-center gap-2 text-sm font-bold"><MessageSquare size={16} />AI 채팅</h2><p className="mt-1 truncate text-[11px] text-muted-foreground">현재 작업 가게 · {storeName}</p></div>
      <button aria-label="채팅 패널 닫기" onClick={() => { onOpenChange(false); document.getElementById("workspace-chat-toggle")?.focus(); }} className="rounded p-1 text-muted-foreground hover:text-foreground"><X size={18} /></button>
    </div>
    {analysis.messageLoading && <p role="status" className="px-4 pt-3 text-xs text-muted-foreground">대화를 불러오는 중…</p>}
    <div className="min-h-0 flex-1">{panel}</div>
  </aside>;
}
