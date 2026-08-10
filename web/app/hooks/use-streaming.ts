"use client";

import { useCallback, useRef, useState } from "react";
import { API_URL } from "../lib/api";
import type { Message, StreamingStep } from "../lib/api";

type UseStreamingOptions = {
  getToken: () => string;
};

// Time without *any* frame from the server — tokens, steps, or heartbeats —
// before the client gives up. The server heartbeats every 15s, so this only
// fires on a genuinely stalled connection rather than on a slow tool call.
const STREAM_IDLE_TIMEOUT_MS = 60_000;

export function useStreaming({ getToken }: UseStreamingOptions) {
  const [loading, setLoading] = useState(false);
  const [streamingSteps, setStreamingSteps] = useState<StreamingStep[]>([]);
  const [streamingAnswer, setStreamingAnswer] = useState("");
  const [mutationsPerformed, setMutationsPerformed] = useState(false);
  const [schemaChanged, setSchemaChanged] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  // Reset by every frame the server sends, including heartbeats, so a slow
  // tool call cannot be mistaken for a dead connection.
  const idleTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const parseSSE = useCallback(
    async (
      res: Response,
      onIdleTimeout: () => void,
      onStep?: (step: StreamingStep) => void
    ): Promise<Message | null> => {
      const reader = res.body?.getReader();
      if (!reader) return null;

      const decoder = new TextDecoder();
      let buffer = "";
      let result: Message | null = null;
      let answerSoFar = "";

      const resetIdleTimer = () => {
        if (idleTimerRef.current) clearTimeout(idleTimerRef.current);
        idleTimerRef.current = setTimeout(onIdleTimeout, STREAM_IDLE_TIMEOUT_MS);
      };
      resetIdleTimer();

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

            let parsed: any;
            try {
              parsed = JSON.parse(dataLine.slice(6));
            } catch {
              continue; // skip malformed JSON
            }

            resetIdleTimer();

            if (parsed.type === "heartbeat") {
              continue;
            }

            if (parsed.type === "token") {
              // Incremental answer text — rendered as it arrives.
              answerSoFar += parsed.data.content || "";
              setStreamingAnswer(answerSoFar);
            } else if (parsed.type === "step") {
              const step: StreamingStep = {
                tool_name: parsed.data.tool_name,
                tool_input: parsed.data.tool_input || {},
                tool_output: parsed.data.tool_output || undefined,
              };
              setStreamingSteps((prev) => [...prev, step]);
              onStep?.(step);
            } else if (parsed.type === "error") {
              // A mid-stream failure. Without this the stream simply ended
              // and the user saw the spinner stop with no explanation.
              setError(
                parsed.data?.message ||
                  "응답 생성 중 오류가 발생했습니다. 다시 시도해주세요."
              );
              return null;
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
          }
        }
      } finally {
        if (idleTimerRef.current) clearTimeout(idleTimerRef.current);
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
      setStreamingAnswer("");
      setMutationsPerformed(false);
      setSchemaChanged(false);
      setError(null);
      abortRef.current = new AbortController();
      let timedOut = false;
      const onIdleTimeout = () => {
        timedOut = true;
        abortRef.current?.abort();
      };

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
        return await parseSSE(res, onIdleTimeout);
      } catch (err) {
        if (err instanceof DOMException && err.name === "AbortError") {
          // A user-initiated stop is not an error; a silent stall is.
          if (timedOut) {
            setError("응답이 지연되어 중단했습니다. 다시 시도해주세요.");
          }
          return null;
        }
        setError("네트워크 오류가 발생했습니다. 연결을 확인해주세요.");
        return null;
      } finally {
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
    streamingAnswer,
    mutationsPerformed,
    schemaChanged,
    error,
    sendMessage,
    abort,
  };
}
