"use client";

import { useCallback, useRef, useState } from "react";
import { API_URL } from "../lib/api";
import type { Message, StreamingStep } from "../lib/api";

type UseStreamingOptions = {
  getToken: () => string;
};

export function useStreaming({ getToken }: UseStreamingOptions) {
  const [loading, setLoading] = useState(false);
  const [streamingSteps, setStreamingSteps] = useState<StreamingStep[]>([]);
  const [mutationsPerformed, setMutationsPerformed] = useState(false);
  const [schemaChanged, setSchemaChanged] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  const parseSSE = useCallback(
    async (
      res: Response,
      onStep?: (step: StreamingStep) => void
    ): Promise<Message | null> => {
      const reader = res.body?.getReader();
      if (!reader) return null;

      const decoder = new TextDecoder();
      let buffer = "";
      let result: Message | null = null;

      try {
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;

          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split("\n\n");
          buffer = lines.pop() || "";

          for (const block of lines) {
            const dataLine = block
              .split("\n")
              .find((l) => l.startsWith("data: "));
            if (!dataLine) continue;

            try {
              const parsed = JSON.parse(dataLine.slice(6));

              if (parsed.type === "step") {
                const step: StreamingStep = {
                  tool_name: parsed.data.tool_name,
                  tool_input: parsed.data.tool_input || {},
                  tool_output: parsed.data.tool_output || undefined,
                };
                setStreamingSteps((prev) => [...prev, step]);
                onStep?.(step);
              } else if (parsed.type === "done") {
                if (parsed.data.mutations_performed) {
                  setMutationsPerformed(true);
                }
                if (parsed.data.schema_changed) {
                  setSchemaChanged(true);
                }
                result = {
                  message_id: parsed.data.message_id || "",
                  role: "assistant",
                  content: parsed.data.content || "",
                  steps: parsed.data.steps || null,
                  charts: parsed.data.charts || null,
                  table_data: parsed.data.table_data || null,
                  suggestions: parsed.data.suggestions || null,
                };
              }
            } catch {
              // skip malformed JSON
            }
          }
        }
      } finally {
        reader.releaseLock();
      }

      return result;
    },
    []
  );

  const sendMessage = useCallback(
    async (
      conversationId: string,
      message: string,
      file?: File | null
    ): Promise<Message | null> => {
      setLoading(true);
      setStreamingSteps([]);
      setMutationsPerformed(false);
      setSchemaChanged(false);
      setError(null);
      abortRef.current = new AbortController();
      const STREAM_TIMEOUT_MS = 120_000; // 2 minutes
      const timeoutId = setTimeout(() => abortRef.current?.abort(), STREAM_TIMEOUT_MS);

      try {
        const formData = new FormData();
        formData.append("message", message);
        if (file) {
          formData.append("files", file);
        }

        const res = await fetch(
          `${API_URL}/api/conversations/${conversationId}/messages/stream`,
          {
            method: "POST",
            headers: {
              Authorization: `Bearer ${getToken()}`,
            },
            body: formData,
            signal: abortRef.current.signal,
          }
        );

        if (!res.ok) {
          const detail = await res.text().catch(() => "");
          const msg =
            res.status === 429
              ? "요청이 너무 많습니다. 잠시 후 다시 시도해주세요."
              : res.status === 401
                ? "인증이 만료되었습니다. 다시 로그인해주세요."
                : `서버 오류가 발생했습니다 (${res.status})`;
          setError(msg);
          return null;
        }
        return await parseSSE(res);
      } catch (err) {
        if (err instanceof DOMException && err.name === "AbortError") {
          return null;
        }
        setError("네트워크 오류가 발생했습니다. 연결을 확인해주세요.");
        return null;
      } finally {
        clearTimeout(timeoutId);
        setLoading(false);
        abortRef.current = null;
      }
    },
    [getToken, parseSSE]
  );

  const abort = useCallback(() => {
    abortRef.current?.abort();
  }, []);

  return {
    loading,
    streamingSteps,
    mutationsPerformed,
    schemaChanged,
    error,
    sendMessage,
    abort,
  };
}
