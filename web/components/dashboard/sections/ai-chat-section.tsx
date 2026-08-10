"use client";

import { useCallback, useEffect, useState, useRef } from "react";
import {
  MessageSquarePlus,
  MessageSquare,
  Loader2,
  Bot,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import ChatPanel from "@/app/components/chat-panel";
import { useDashboard } from "@/app/contexts/dashboard-context";
import type {
  Conversation,
  Message,
  StreamingStep,
  ChartData,
} from "@/app/lib/api";

interface AiChatSectionProps {
  sendMessage: (
    conversationId: string,
    message: string,
    file?: File | null
  ) => Promise<Message | null>;
  streamLoading: boolean;
  streamingSteps: StreamingStep[];
  streamingAnswer?: string;
  streamError?: string | null;
  onStopStream?: () => void;
  onMutationPerformed?: () => void;
  onPinChart?: (chart: ChartData) => void;
}

export function AiChatSection({
  sendMessage,
  streamLoading,
  streamingSteps,
  streamingAnswer,
  streamError,
  onStopStream,
  onMutationPerformed,
  onPinChart,
}: AiChatSectionProps) {
  const { selectedProjectId, apiFetch } = useDashboard();
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [activeConvId, setActiveConvId] = useState<string>("");
  const [messages, setMessages] = useState<Message[]>([]);
  const [convLoading, setConvLoading] = useState(false);
  const [msgsLoading, setMsgsLoading] = useState(false);
  const prevProjectRef = useRef(selectedProjectId);
  const hasLoadedRef = useRef(false);

  const fetchConversations = useCallback(async () => {
    if (!selectedProjectId) return;
    setConvLoading(true);
    try {
      const res = await apiFetch(
        `/api/conversations?project_id=${selectedProjectId}`
      );
      if (res.ok) {
        const data = await res.json();
        const convs: Conversation[] = data.conversations || [];
        setConversations(convs);
        hasLoadedRef.current = true;

        if (!activeConvId) {
          if (convs.length > 0) {
            setActiveConvId(convs[0].conversation_id);
          }
        }
      }
    } catch {
      // ignore
    } finally {
      setConvLoading(false);
    }
  }, [selectedProjectId, apiFetch, activeConvId]);

  const handleNewConversation = useCallback(async () => {
    if (!selectedProjectId) return;
    try {
      const res = await apiFetch("/api/conversations", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          project_id: selectedProjectId,
          title: "새 대화",
        }),
      });
      if (res.ok) {
        const data = await res.json();
        setConversations((prev) => [data, ...prev]);
        setActiveConvId(data.conversation_id);
        setMessages([]);
      }
    } catch {
      // ignore
    }
  }, [selectedProjectId, apiFetch]);

  useEffect(() => {
    if (selectedProjectId !== prevProjectRef.current) {
      prevProjectRef.current = selectedProjectId;
      hasLoadedRef.current = false;
      setActiveConvId("");
      setMessages([]);
    }
    fetchConversations();
  }, [selectedProjectId, fetchConversations]);

  useEffect(() => {
    if (!selectedProjectId || convLoading || activeConvId || !hasLoadedRef.current) return;
    if (conversations.length === 0) {
      handleNewConversation();
    }
  }, [selectedProjectId, convLoading, activeConvId, conversations, handleNewConversation]);

  useEffect(() => {
    if (!activeConvId) {
      setMessages([]);
      return;
    }
    let cancelled = false;
    (async () => {
      setMsgsLoading(true);
      try {
        const res = await apiFetch(
          `/api/conversations/${activeConvId}/messages`
        );
        if (res.ok && !cancelled) {
          const data = await res.json();
          setMessages(data.messages || []);
        }
      } catch {
        // ignore
      } finally {
        if (!cancelled) setMsgsLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [activeConvId, apiFetch]);

  const handleSend = useCallback(
    async (text: string, file?: File | null) => {
      if (!activeConvId || !text.trim()) return;

      const userMsg: Message = {
        message_id: `temp-${Date.now()}`,
        role: "user",
        content: text,
      };
      setMessages((prev) => [...prev, userMsg]);

      const result = await sendMessage(activeConvId, text, file);
      if (result) {
        setMessages((prev) => {
          const withoutTemp = prev.filter((m) => m.message_id !== userMsg.message_id);
          return [
            ...withoutTemp,
            { ...userMsg, message_id: result.message_id ? `user-${result.message_id}` : userMsg.message_id },
            result,
          ];
        });
        await fetchConversations();
        onMutationPerformed?.();
      }
    },
    [activeConvId, sendMessage, fetchConversations, onMutationPerformed]
  );

  if (!selectedProjectId) {
    return (
      <div className="flex flex-col items-center justify-center py-24 text-center animate-in fade-in slide-in-from-bottom-4 duration-500">
        <div className="h-20 w-20 rounded-2xl bg-secondary flex items-center justify-center mb-6">
          <Bot className="h-10 w-10 text-muted-foreground" />
        </div>
        <h3 className="text-lg font-semibold text-foreground mb-2">
          프로젝트를 먼저 선택해주세요
        </h3>
        <p className="text-sm text-muted-foreground max-w-md">
          사이드바에서 프로젝트를 선택하면 AI와 대화할 수 있습니다.
        </p>
      </div>
    );
  }

  return (
    <div className="flex h-[calc(100vh-130px)] rounded-xl border border-border bg-card overflow-hidden">
      {/* Left: Conversation list */}
      <div className="w-64 border-r border-border flex flex-col shrink-0">
        <div className="p-3 border-b border-border">
          <Button
            onClick={handleNewConversation}
            size="sm"
            variant="outline"
            className="w-full gap-2 hover:border-accent/50 transition-colors"
          >
            <MessageSquarePlus className="h-4 w-4" />
            새 대화
          </Button>
        </div>

        <div className="flex-1 overflow-y-auto">
          {convLoading ? (
            <div className="flex justify-center py-8">
              <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
            </div>
          ) : conversations.length === 0 ? (
            <div className="px-3 py-8 text-center text-xs text-muted-foreground animate-in fade-in duration-300">
              대화가 없습니다.
              <br />
              새 대화를 시작해보세요.
            </div>
          ) : (
            conversations.map((conv, index) => (
              <button
                key={conv.conversation_id}
                onClick={() => setActiveConvId(conv.conversation_id)}
                className={cn(
                  "w-full text-left px-3 py-2.5 text-sm transition-all duration-200 border-b border-border/50 flex items-start gap-2 group animate-in fade-in slide-in-from-left-2",
                  activeConvId === conv.conversation_id
                    ? "bg-secondary text-foreground"
                    : "text-muted-foreground hover:bg-secondary/50 hover:text-foreground"
                )}
                style={{
                  animationDelay: `${index * 50}ms`,
                  animationFillMode: "both",
                }}
              >
                <MessageSquare
                  className={cn(
                    "h-4 w-4 shrink-0 mt-0.5 transition-colors duration-200",
                    activeConvId === conv.conversation_id
                      ? "text-accent"
                      : "group-hover:text-accent"
                  )}
                />
                <span className="truncate">{conv.title}</span>
              </button>
            ))
          )}
        </div>
      </div>

      {/* Right: Chat panel */}
      <div className="flex-1 flex flex-col min-w-0">
        {!activeConvId ? (
          <div className="flex-1 flex flex-col items-center justify-center text-center px-6 animate-in fade-in duration-500">
            <div className="h-16 w-16 rounded-2xl bg-secondary flex items-center justify-center mb-4">
              <MessageSquare className="h-8 w-8 text-muted-foreground" />
            </div>
            <h3 className="text-base font-semibold text-foreground mb-2">
              대화를 선택하거나 새 대화를 시작하세요
            </h3>
            <p className="text-sm text-muted-foreground max-w-md">
              AI에게 데이터를 추가/수정/삭제하거나 분석을 요청해보세요.
              <br />
              프로젝트 내 모든 장부를 AI가 자동으로 탐색합니다.
            </p>
          </div>
        ) : msgsLoading ? (
          <div className="flex-1 flex items-center justify-center">
            <Loader2 className="h-6 w-6 animate-spin text-accent" />
          </div>
        ) : (
          <ChatPanel
            messages={messages}
            onSend={handleSend}
            loading={streamLoading}
            disabled={false}
            streamingSteps={streamingSteps}
            streamingAnswer={streamingAnswer}
            streamError={streamError}
            onStop={onStopStream}
            onPinChart={onPinChart}
          />
        )}
      </div>
    </div>
  );
}
