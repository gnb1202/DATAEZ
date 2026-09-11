import { parseError } from "./api";
import type { LibraryFile } from "./file-library";

type ApiFetch = (path: string, init?: RequestInit) => Promise<Response>;
const requests = new WeakMap<File, Map<string, string>>();
type SourceCache = WeakMap<File, Map<string, Promise<LibraryFile & { replayed: boolean }>>>;

// Keep the same original across inspect → validate → commit, scoped to the
// authenticated fetch callback and store without retaining any credentials.
export async function uploadSourceForm(apiFetch: ApiFetch, file: File, projectId: string,
  field = "file", signal?: AbortSignal): Promise<FormData> {
  const response = await apiFetch("/api/uploads/capabilities", { signal });
  if (!response.ok) throw new Error(await parseError(response));
  const capability = await response.json();
  const body = new FormData();
  if (!capability.direct_upload) { body.set(field, file); return body; }
  // apiFetch identity belongs to the authenticated workspace; the WeakMap is
  // attached below instead of retaining credentials in module state.
  let cache = sourceCaches.get(apiFetch);
  if (!cache) { cache = new WeakMap(); sourceCaches.set(apiFetch, cache); }
  let scopes = cache.get(file);
  if (!scopes) { scopes = new Map(); cache.set(file, scopes); }
  let pending = scopes.get(projectId);
  if (!pending) {
    pending = uploadLibraryFile(apiFetch, file, projectId);
    scopes.set(projectId, pending);
    pending.catch(() => scopes!.delete(projectId));
  }
  const source = await pending;
  signal?.throwIfAborted();
  body.set(field === "files" ? "stored_file_ids" : "stored_file_id",
    field === "files" ? JSON.stringify([source.file_id]) : source.file_id);
  return body;
}
const sourceCaches = new WeakMap<ApiFetch, SourceCache>();

export async function uploadLibraryFile(apiFetch: ApiFetch, file: File, projectId?: string,
  onStage?: (message: string) => void): Promise<LibraryFile & { replayed: boolean }> {
  const read = async (path: string, init?: RequestInit) => {
    const response = await apiFetch(path, init);
    if (!response.ok) throw new Error(await parseError(response));
    return response;
  };
  const capabilities = await (await read("/api/uploads/capabilities")).json();
  if (!file.size || file.size > capabilities.max_size_bytes) {
    throw new Error(`비어 있지 않은 ${Math.floor(capabilities.max_size_bytes / 1024 / 1024)}MB 이하 파일을 선택해주세요.`);
  }
  if (!capabilities.direct_upload) {
    const body = new FormData(); body.append("file", file);
    if (projectId) body.append("project_id", projectId);
    return (await read("/api/library/files", { method: "POST", body })).json();
  }
  onStage?.("파일을 확인하고 있습니다…");
  const digest = await crypto.subtle.digest("SHA-256", await file.arrayBuffer());
  const hash = Array.from(new Uint8Array(digest), value => value.toString(16).padStart(2, "0")).join("");
  const scope = projectId || "";
  const ids = requests.get(file) || new Map<string, string>();
  if (!ids.has(scope)) ids.set(scope, crypto.randomUUID());
  requests.set(file, ids);
  const reservation = await (await read("/api/uploads", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ request_id: ids.get(scope), project_id: projectId || null,
      filename: file.name, size_bytes: file.size, content_hash: hash }),
  })).json();
  if (reservation.upload_url) {
    onStage?.("원본을 전송하고 있습니다…");
    // The scoped signed URL is the only credential sent to Storage. Never use
    // apiFetch here: it attaches DATA:EZ's account JWT to outgoing requests.
    try {
      const uploaded = await fetch(reservation.upload_url, { method: "PUT", body: file,
        headers: { "Content-Type": "application/octet-stream", "Cache-Control": "no-store" },
        credentials: "omit", referrerPolicy: "no-referrer", signal: AbortSignal.timeout(120_000) });
      if (!uploaded.ok) throw new Error("파일 전송을 완료하지 못했습니다.");
    } catch {
      // A lost response can still mean a successful immutable upload. The
      // authenticated completion endpoint checks actual bytes before accepting it.
      onStage?.("전송 결과를 확인하고 있습니다…");
    }
  }
  onStage?.("전송된 파일을 검증하고 있습니다…");
  return (await read(`/api/uploads/${reservation.session_id}/complete`, { method: "POST" })).json();
}

export async function downloadLibraryFile(apiFetch: ApiFetch, fileId: string): Promise<Blob> {
  const signed = await apiFetch(`/api/library/files/${fileId}/download-url`, { method: "POST" });
  if (!signed.ok) throw new Error(await parseError(signed));
  const { url } = await signed.json();
  const response = url ? await fetch(url, { credentials: "omit", referrerPolicy: "no-referrer", signal: AbortSignal.timeout(120_000) })
    : await apiFetch(`/api/library/files/${fileId}/download`);
  if (!response.ok) throw new Error("원본을 다운로드하지 못했습니다. 다시 시도해주세요.");
  return response.blob();
}
