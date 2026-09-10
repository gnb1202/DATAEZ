"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useStreaming } from "./use-streaming";
import type { Conversation, Message } from "../lib/api";
import { parseError } from "../lib/api";
import { messageReferences, referencePayload, referenceStep, type LibraryReference } from "../lib/file-library";

export type Composer = { text: string; file: File | null; libraryFiles?: LibraryReference[] };

// Owned by the store workspace, never by a route or the chat panel.
export function useWorkspaceAnalysis(projectId: string, token: string, apiFetch: (path: string, init?: RequestInit) => Promise<Response>) {
  const stream = useStreaming({ getToken: () => token });
  const abortStream = stream.abort;
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [conversationId, setConversationId] = useState("");
  const [messages, setMessages] = useState<Message[]>([]);
  const [resultId, setResultId] = useState("");
  const [composer, setComposer] = useState<Composer>({ text: "", file: null });
  const [historyLoading, setHistoryLoading] = useState(false);
  const [messageLoading, setMessageLoading] = useState(false);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [recoveryAvailable, setRecoveryAvailable] = useState(false);
  const [recoveryNotice, setRecoveryNotice] = useState("");
  const pendingDraft = useRef<Composer | null>(null);
  const streamStarted = useRef(false);
  const epoch = useRef(0);
  const historyRequest = useRef(0);
  const sendLock = useRef(false);
  const alive = useRef(true);
  useEffect(() => {
    alive.current = true;
    const invalidate = () => { alive.current = false; epoch.current++; historyRequest.current++; };
    return invalidate;
  }, []);

  const refreshHistory = useCallback(async () => {
    if (!projectId) return;
    const request = ++historyRequest.current;
    setHistoryLoading(true);
    try {
      const res = await apiFetch(`/api/conversations?project_id=${encodeURIComponent(projectId)}`);
      if (!res.ok) throw new Error(await parseError(res));
      const data = await res.json();
      if (alive.current && request === historyRequest.current) setConversations(data.conversations || []);
    } catch (err) {
      if (alive.current && request === historyRequest.current) setError(err instanceof Error ? err.message : "분석 이력을 불러오지 못했습니다.");
    } finally {
      if (alive.current && request === historyRequest.current) setHistoryLoading(false);
    }
  }, [projectId, apiFetch]);
  useEffect(() => { void refreshHistory(); }, [refreshHistory]);

  const reset = useCallback((text = "") => {
    epoch.current++;
    sendLock.current = false;
    abortStream();
    setSending(false);
    setMessageLoading(false);
    setConversationId("");
    setMessages([]);
    setResultId("");
    setComposer({ text, file: null });
    setError(null);
    setRecoveryAvailable(false);
    setRecoveryNotice("");
    pendingDraft.current = null;
    streamStarted.current = false;
  }, [abortStream]);

  const openConversation = async (id: string) => {
    reset();
    const request = epoch.current;
    setConversationId(id);
    setMessageLoading(true);
    try {
      const res = await apiFetch(`/api/conversations/${encodeURIComponent(id)}/messages`);
      if (!res.ok) throw new Error(await parseError(res));
      const data = await res.json();
      if (!alive.current || request !== epoch.current) return;
      const list: Message[] = data.messages || [];
      setMessages(list);
      const refs = messageReferences(list.filter((item) => item.role === "user").at(-1)?.steps);
      setComposer({ text: "", file: null, libraryFiles: refs.map((ref) => ({ ...ref, include_other_store: ref.project_id !== projectId })) });
      setResultId(list.filter((item) => item.role === "assistant").at(-1)?.message_id || "");
    } catch (err) {
      if (alive.current && request === epoch.current) {
        setConversationId("");
        setError(err instanceof Error ? err.message : "대화를 불러오지 못했습니다.");
      }
    } finally { if (alive.current && request === epoch.current) setMessageLoading(false); }
  };

  const send = async (text: string, file?: File | null): Promise<void> => {
    if (!projectId || sendLock.current || messageLoading) return;
    sendLock.current = true;
    setSending(true);
    setError(null);
    setRecoveryAvailable(false);
    setRecoveryNotice("");
    pendingDraft.current = { text, file: file || null, libraryFiles: composer.libraryFiles };
    streamStarted.current = false;
    const request = epoch.current;
    const active = () => alive.current && request === epoch.current;
    let libraryFiles = composer.libraryFiles || [];
    let id = conversationId;
    try {
      if (libraryFiles.length) {
        if (file) throw new Error("기기 첨부와 보관함 파일 중 하나의 경로를 선택해주세요.");
        const check = await apiFetch("/api/library/files/resolve", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ project_id: projectId, selections: referencePayload(libraryFiles), confirmed: true }) });
        if (!check.ok) throw new Error(await parseError(check));
        libraryFiles = (await check.json()).files.map((ref: LibraryReference) => ({...ref, include_other_store: ref.project_id !== projectId}));
        if (!active()) return;
      }
      if (!id) {
        const res = await apiFetch("/api/conversations", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ project_id: projectId }) });
        if (!res.ok) throw new Error(await parseError(res));
        const data = await res.json();
        if (!active()) return;
        id = data.conversation_id;
        setConversationId(id);
      }
      if (!active()) return;
      setMessages((prev) => [...prev, { message_id: crypto.randomUUID(), role: "user", content: text, steps: libraryFiles.length ? [referenceStep(libraryFiles)] : undefined }]);
      pendingDraft.current = { text, file: file || null, libraryFiles };
      streamStarted.current = true;
      setComposer({ text: "", file: null, libraryFiles });
      const result = await stream.sendMessage(id, text, file, libraryFiles);
      if (!active()) return;
      if (result) {
        setMessages((prev) => [...prev, result]);
        setResultId(result.message_id);
      } else {
        setComposer({ text, file: file || null, libraryFiles });
        setRecoveryAvailable(true);
      }
      // Restore the draft, never resend it: the server may already have written
      // transactions or widgets. Let the user read persisted messages first.
      void refreshHistory();
    } catch (err) {
      if (active()) setError(err instanceof Error ? err.message : "분석을 시작하지 못했습니다.");
    } finally {
      if (active()) { sendLock.current = false; setSending(false); pendingDraft.current = null; streamStarted.current = false; }
    }
  };

  const stop = () => {
    epoch.current++;
    sendLock.current = false;
    abortStream();
    setSending(false);
    setError("응답 수신을 중지했습니다. 처리된 내용은 분석 이력에서 확인할 수 있습니다.");
    if (pendingDraft.current) setComposer(pendingDraft.current);
    setRecoveryAvailable(streamStarted.current);
    pendingDraft.current = null;
    streamStarted.current = false;
    void refreshHistory();
  };

  const reviewCurrentConversation = async () => {
    if (!conversationId || sendLock.current || messageLoading) return;
    const request = epoch.current;
    setMessageLoading(true); setRecoveryNotice("");
    try {
      const response = await apiFetch(`/api/conversations/${encodeURIComponent(conversationId)}/messages`);
      if (!response.ok) throw new Error(await parseError(response));
      const data = await response.json();
      if (!alive.current || request !== epoch.current) return;
      const list: Message[] = data.messages || [];
      setMessages(list);
      setResultId(list.filter(item => item.role === "assistant").at(-1)?.message_id || "");
      abortStream(); setError(null);
      setRecoveryNotice(list.at(-1)?.role === "assistant"
        ? "저장된 답변을 불러왔습니다. 이번 질문의 처리 내용인지 확인하세요. 질문 초안과 첨부는 유지했습니다."
        : "아직 완료된 답변을 확인하지 못했습니다. 잠시 후 기록을 다시 확인하세요. 질문 초안과 첨부는 유지했습니다.");
    } catch (err) {
      if (alive.current && request === epoch.current) setError(err instanceof Error ? err.message : "처리 기록을 불러오지 못했습니다.");
    } finally { if (alive.current && request === epoch.current) setMessageLoading(false); }
  };

  return { conversations, conversationId, messages, result: messages.find((item) => item.message_id === resultId), setResultId,
    composer, setComposer, historyLoading, messageLoading, loading: sending || stream.loading,
    error: error || stream.error, stream, reset, openConversation, send, stop, refreshHistory,
    recoveryAvailable, recoveryNotice, reviewCurrentConversation };
}
