"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { referencePayload, type LibraryReference } from "../lib/file-library";
import { API_URL, parseError } from "../lib/api";
import type { Message, StreamingStep } from "../lib/api";

// Every request owns its controller and idle timer. Aborted requests cannot
// publish state (including their finally block) into a newer conversation.
export function useStreaming({ getToken }: { getToken: () => string }) {
  const [loading, setLoading] = useState(false);
  const [streamingSteps, setStreamingSteps] = useState<StreamingStep[]>([]);
  const [streamingAnswer, setStreamingAnswer] = useState("");
  const [mutationsPerformed, setMutationsPerformed] = useState(false);
  const [schemaChanged, setSchemaChanged] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const current = useRef<AbortController | null>(null);

  const abort = useCallback(() => {
    current.current?.abort();
    current.current = null;
    setLoading(false);
    setStreamingSteps([]);
    setStreamingAnswer("");
    setError(null);
    setMutationsPerformed(false);
    setSchemaChanged(false);
  }, []);
  useEffect(() => () => { current.current?.abort(); current.current = null; }, []);

  const sendMessage = useCallback(async (conversationId: string, message: string, file?: File | null, libraryFiles: LibraryReference[] = []): Promise<Message | null> => {
    current.current?.abort();
    const controller = new AbortController();
    current.current = controller;
    const active = () => current.current === controller && !controller.signal.aborted;
    setLoading(true);
    setStreamingSteps([]);
    setStreamingAnswer("");
    setError(null);
    setMutationsPerformed(false);
    setSchemaChanged(false);
    let timedOut = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const heartbeat = () => {
      clearTimeout(timer);
      timer = setTimeout(() => { timedOut = true; controller.abort(); }, 60_000);
    };
    heartbeat();
    try {
      const body = new FormData();
      body.append("message", message);
      if (file) body.append("files", file);
      if (libraryFiles.length) { body.append("library_selections", JSON.stringify(referencePayload(libraryFiles))); body.append("library_scope_confirmed", "true"); }
      const res = await fetch(`${API_URL}/api/conversations/${conversationId}/messages/stream`, {
        method: "POST", headers: { Authorization: `Bearer ${getToken()}` }, body, signal: controller.signal,
      });
      if (!active()) return null;
      if (!res.ok) throw new Error(res.status === 401 ? "인증이 만료되었습니다. 다시 로그인해주세요." : res.status === 429 ? "요청이 너무 많습니다. 잠시 후 다시 시도해주세요." : await parseError(res));
      const reader = res.body?.getReader();
      if (!reader) throw new Error("응답을 읽을 수 없습니다. 다시 시도해주세요.");
      const decoder = new TextDecoder();
      let buffer = "";
      let answer = "";
      try {
        while (active()) {
          const { done, value } = await reader.read();
          if (!active()) return null;
          if (done) break;
          buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, "\n");
          const blocks = buffer.split("\n\n");
          buffer = blocks.pop() || "";
          for (const block of blocks) {
            const line = block.split("\n").find((part) => part.startsWith("data:"));
            if (!line) continue;
            let frame;
            try { frame = JSON.parse(line.slice(5).trim()); } catch { continue; }
            heartbeat();
            if (frame.type === "token") { answer += frame.data?.content || ""; setStreamingAnswer(answer); }
            if (frame.type === "step") setStreamingSteps((prev) => [...prev, { tool_name: frame.data.tool_name, tool_input: frame.data.tool_input || {}, tool_output: frame.data.tool_output }]);
            if (frame.type === "error") throw new Error(frame.data?.message || "응답 생성 중 오류가 발생했습니다.");
            if (frame.type === "done") {
              setMutationsPerformed(!!frame.data.mutations_performed);
              setSchemaChanged(!!frame.data.schema_changed);
              return { message_id: frame.data.message_id || crypto.randomUUID(), role: "assistant", content: frame.data.content || "", steps: frame.data.steps, charts: frame.data.charts, table_data: frame.data.table_data, suggestions: frame.data.suggestions };
            }
          }
        }
        if (active()) throw new Error("응답이 완료되기 전에 연결이 끊겼습니다. 분석 이력을 확인한 뒤 다시 시도해주세요.");
        return null;
      } finally { await reader.cancel().catch(() => {}); reader.releaseLock(); }
    } catch (err) {
      if (current.current === controller) {
        if (timedOut) setError("응답이 지연되어 중단했습니다. 분석 이력을 확인해주세요.");
        else if (!controller.signal.aborted) setError(err instanceof Error ? err.message : "네트워크 연결을 확인해주세요.");
      }
      return null;
    } finally {
      clearTimeout(timer);
      if (current.current === controller) { current.current = null; setLoading(false); }
    }
  }, [getToken]);

  return { loading, streamingSteps, streamingAnswer, mutationsPerformed, schemaChanged, error, sendMessage, abort };
}
