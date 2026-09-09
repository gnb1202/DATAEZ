"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { ChartData, Message } from "../lib/api";
import { parseError } from "../lib/api";

type Widget = { id: string; save_key?: string; layout?: { y: number; h: number }; widget_data?: Record<string, unknown> };
export type ChartSaveOptions = { title: string; definition?: Record<string, unknown>; refresh_interval_seconds: number };
export type ChartSaveState = { status: "checking" | "unsaved" | "saving" | "saved" | "error"; id?: string; error?: string; settings?: ChartSaveOptions };
const canonical = (value: unknown): string => JSON.stringify(value, (_key, item) => item && typeof item === "object" && !Array.isArray(item) ? Object.fromEntries(Object.entries(item).sort(([a], [b]) => a.localeCompare(b))) : item);

// Lives with the store workspace so navigation does not cancel or reset a save.
export function useChartSaving(projectId: string, message: Message | undefined, visible: boolean, apiFetch: (path: string, init?: RequestInit) => Promise<Response>, onSaved: () => void) {
  const [widgets, setWidgets] = useState<Widget[]>([]);
  const [catalog, setCatalog] = useState<"checking" | "ready" | "error">("checking");
  const [attempts, setAttempts] = useState<Record<string, ChartSaveState>>({});
  const submitted = useRef(new Map<string, { body: string; metric: boolean; settings?: ChartSaveOptions }>());
  const alive = useRef(true), revision = useRef(0), locks = useRef(new Set<string>());
  useEffect(() => { alive.current = true; const invalidate = () => { alive.current = false; revision.current++; }; return invalidate; }, []);
  const load = useCallback(async () => {
    const response = await apiFetch(`/api/dashboard/widgets?project_id=${encodeURIComponent(projectId)}`);
    if (!response.ok) throw new Error(await parseError(response));
    return (await response.json()).widgets as Widget[];
  }, [projectId, apiFetch]);
  const refresh = useCallback(async () => {
    const request = ++revision.current;
    setCatalog("checking");
    try {
      const list = await load();
      if (alive.current && request === revision.current) { setWidgets(list); setCatalog("ready"); }
    } catch { if (alive.current && request === revision.current) setCatalog("error"); }
  }, [load]);
  useEffect(() => { if (visible && message?.charts?.length) void refresh(); }, [visible, message?.message_id, message?.charts?.length, refresh]);

  const keyFor = (index: number) => `analysis:${message?.message_id}:${index}`;
  const existing = (index: number) => {
    const byKey = widgets.find((widget) => widget.save_key === keyFor(index));
    if (byKey) return byKey;
    const definition = message?.charts?.[index]?.metric_definition;
    if (!definition) return;
    const savedIds = message?.steps?.flatMap((step) => {
      const output = step.tool_output;
      return output?.saved && output.metric_id && canonical(output.definition) === canonical(definition) ? [String(output.metric_id)] : [];
    }) || [];
    return widgets.find((widget) => savedIds.includes(widget.id));
  };
  const state = (index: number): ChartSaveState => {
    if (attempts[keyFor(index)]?.status === "saving") return attempts[keyFor(index)];
    if (catalog === "checking") return { status: "checking", settings: submitted.current.get(keyFor(index))?.settings };
    if (catalog === "error") return { status: "error", settings: submitted.current.get(keyFor(index))?.settings, error: "저장 상태를 확인하지 못했습니다. 다시 확인해주세요." };
    const found = existing(index);
    return found ? { status: "saved", id: found.id } : attempts[keyFor(index)] || { status: "unsaved" };
  };
  const save = async (index: number, chart: ChartData, options?: ChartSaveOptions) => {
    if (catalog !== "ready") { void refresh(); return; }
    const key = keyFor(index);
    if (!message || existing(index) || locks.current.has(key)) return;
    locks.current.add(key);
    revision.current++;
    setAttempts((prev) => ({ ...prev, [key]: { status: "saving", settings: submitted.current.get(key)?.settings || options } }));
    const remember = (widget: Widget) => {
      if (!alive.current) return;
      revision.current++;
      setWidgets((prev) => [...prev.filter((item) => item.id !== widget.id), { ...widget, save_key: key }]);
      setCatalog("ready");
      setAttempts((prev) => ({ ...prev, [key]: { status: "unsaved" } }));
      submitted.current.delete(key);
      onSaved();
    };
    try {
      const nextY = widgets.reduce((bottom, widget) => Math.max(bottom, (widget.layout?.y || 0) + (widget.layout?.h || 0)), 0);
      const body = chart.metric_definition ? { title: options?.title || chart.title || "저장 지표", definition: options?.definition || chart.metric_definition, refresh_interval_seconds: options?.refresh_interval_seconds || 0, save_key: key } : {
        project_id: projectId, widget_type: "chart", title: options?.title || chart.title, save_key: key,
        widget_data: chart, layout: { x: 0, y: nextY, w: 6, h: 5 },
      };
      if (!submitted.current.has(key)) submitted.current.set(key, { body: JSON.stringify(body), metric: !!chart.metric_definition, settings: options });
      const attempt = submitted.current.get(key)!;
      const response = await apiFetch(attempt.metric ? `/api/projects/${projectId}/metrics` : "/api/dashboard/widgets", { method: "POST", headers: { "Content-Type": "application/json" }, body: attempt.body });
      if (!response.ok) throw new Error(await parseError(response));
      const widget = await response.json();
      if (!widget.id) throw new Error("저장 결과를 확인하지 못했습니다.");
      remember(widget);
    } catch (error) {
      // A response can be lost after commit. Reconcile before offering the same-key retry.
      const saved = await load().then((list) => list.find((widget) => widget.save_key === key)).catch(() => undefined);
      if (saved) remember(saved);
      else if (alive.current) setAttempts((prev) => ({ ...prev, [key]: { status: "error", settings: submitted.current.get(key)?.settings, error: error instanceof Error ? error.message : "저장하지 못했습니다. 다시 시도해주세요." } }));
    } finally { locks.current.delete(key); }
  };
  return { state, save };
}
