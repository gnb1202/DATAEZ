export const API_URL = process.env.NEXT_PUBLIC_API_URL?.trim().replace(/\/+$/, "") ||
  (process.env.NODE_ENV === "production" ? "" : "http://localhost:8000");
export const API_CONFIGURED = Boolean(API_URL);
export const API_UNAVAILABLE_MESSAGE = "체험 서비스를 준비하고 있어요. 준비가 끝나면 다시 이용해주세요.";

export function requireApiConfiguration(): void {
  if (!API_CONFIGURED) throw new Error(API_UNAVAILABLE_MESSAGE);
}

export async function parseError(res: Response): Promise<string> {
  try {
    const data = (await res.json()) as { detail?: unknown };
    if (typeof data.detail === "string") return data.detail;
    if (Array.isArray(data.detail)) return data.detail.map((item) => String(item.msg || "입력값을 확인해주세요.")).join(" · ");
    return `Request failed (${res.status})`;
  } catch {
    return `Request failed (${res.status})`;
  }
}

export function formatDate(value?: string | null): string {
  if (!value) return "-";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return value;
  return d.toLocaleString();
}

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

// Core domain types
export type Project = {
  id: string;
  name: string;
  description: string;
  table_count?: number;
  created_at?: string;
  updated_at?: string;
};

export type ColumnSchema = {
  name: string;
  type: string;
  nullable: boolean;
};

export type TableMeta = {
  id: string;
  project_id: string;
  name: string;
  description: string;
  columns_schema: ColumnSchema[];
  row_count: number;
  source_file_id?: string | null;
  ledger_source_id?: string | null;
  created_at?: string;
  updated_at?: string;
};

export type StreamingStep = {
  tool_name: string;
  tool_input: Record<string, unknown>;
  tool_output?: Record<string, unknown>;
};

export type AgentStep = {
  type: "thinking" | "tool_call" | "tool_result" | "answer" | "meta";
  content?: string;
  tool_name?: string;
  tool_input?: Record<string, unknown>;
  tool_output?: Record<string, unknown>;
};

export type ChartData = {
  unit?: string;
  metric_definition?: Record<string, unknown>;
  chart_type: string;
  title: string;
  x_key: string;
  y_key: string;
  data: Array<Record<string, unknown>>;
};

export type Message = {
  message_id: string;
  role: "user" | "assistant";
  content: string;
  steps?: AgentStep[] | null;
  charts?: ChartData[] | null;
  table_data?: Array<Record<string, unknown>> | null;
  suggestions?: string[] | null;
  created_at?: string;
};

export type Conversation = {
  conversation_id: string;
  file_id: string | null;
  table_id: string | null;
  project_id: string | null;
  title: string;
  created_at?: string;
  updated_at?: string;
};

export function createApiFetcher(getToken: () => string) {
  return async (
    path: string,
    init: RequestInit = {},
    authRequired = true,
    accessTokenOverride = ""
  ): Promise<Response> => {
    requireApiConfiguration();
    const headers = new Headers(init.headers || {});
    const accessToken = accessTokenOverride || getToken();
    if (authRequired && accessToken) {
      headers.set("Authorization", `Bearer ${accessToken}`);
    }
    return fetch(`${API_URL}${path}`, { ...init, headers });
  };
}
