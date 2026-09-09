import type { AgentStep } from "./api";

export type LibraryBinding = {
  kind: "ledger" | "document";
  project_id: string;
  project_name: string;
  table_id?: string;
  table_name?: string;
  row_count?: number;
  index_status?: string;
  job_id?: string;
};
export type LibraryFile = {
  file_id: string; filename: string; size_bytes: number; created_at: string;
  content_hash?: string; status: string; project_id?: string; project_name?: string;
  bindings: LibraryBinding[]; kind: "table" | "document";
};
export type LibraryReference = LibraryBinding & { file_id: string; filename: string; content_hash?: string; include_other_store?: boolean; scope?: "original_file" | "linked_ledger" | "document"; binding_table_id?: string };
export function referenceScope(file: LibraryReference) { return file.kind === "document" ? "선택 문서" : file.scope === "original_file" ? "파일 원본만" : "누적 장부 전체"; }
export function referenceKey(file: LibraryReference) { return `${file.file_id}:${file.binding_table_id || file.table_id || file.project_id}`; }
export function referencePayload(files: LibraryReference[]) {
  return files.map(({ file_id, table_id, binding_table_id, scope, include_other_store }) => ({ file_id, table_id: binding_table_id || table_id, scope, include_other_store: !!include_other_store }));
}
export function messageReferences(steps?: AgentStep[] | null): LibraryReference[] {
  const output = steps?.find((step) => step.tool_name === "library_references")?.tool_output;
  return Array.isArray(output?.files) ? output.files as LibraryReference[] : [];
}
export function referenceStep(files: LibraryReference[]): AgentStep {
  return { type: "meta", tool_name: "library_references", tool_output: { files } };
}
