import type { Health, MemoryItem, ModelInfo, Session, Settings } from "./types.ts";

let bootstrapped: Promise<void> | null = null;

/** Get the same-site session cookie the API requires. */
export function bootstrap(): Promise<void> {
  bootstrapped ??= fetch("/api/auth/bootstrap", { method: "POST", credentials: "same-origin" }).then((r) => {
    if (!r.ok) throw new Error(`Could not reach the root server (${r.status}).`);
  });
  return bootstrapped;
}

export class ApiError extends Error {
  constructor(message: string, readonly status: number) {
    super(message);
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  await bootstrap();
  const response = await fetch(path, {
    credentials: "same-origin",
    ...init,
    headers: { "Content-Type": "application/json", ...(init.headers ?? {}) },
  });
  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = await response.json();
      detail = body.detail ?? detail;
    } catch {
      /* not JSON */
    }
    throw new ApiError(String(detail), response.status);
  }
  return response.json() as Promise<T>;
}

const q = (params: Record<string, string>) => new URLSearchParams(params).toString();

export const api = {
  health: () => request<Health>("/api/health"),
  settings: () => request<Settings>("/api/settings"),
  saveSettings: (changes: Partial<Settings> & { clear_api_key?: boolean }) =>
    request<Settings>("/api/settings", { method: "PUT", body: JSON.stringify(changes) }),
  models: (refresh = false) => request<{ models: ModelInfo[]; error: string }>(`/api/models${refresh ? "?refresh=true" : ""}`),
  sessions: () => request<{ sessions: Session[] }>("/api/sessions"),
  createSession: (workspace: string) =>
    request<Session>("/api/sessions", { method: "POST", body: JSON.stringify({ workspace }) }),
  updateSession: (id: string, changes: { title?: string; permission_mode?: string }) =>
    request<Session>(`/api/sessions/${id}`, { method: "PATCH", body: JSON.stringify(changes) }),
  deleteSession: (id: string) => request<{ ok: boolean }>(`/api/sessions/${id}`, { method: "DELETE" }),
  director: (id: string) => request<{ decisions: any[] }>(`/api/sessions/${id}/director`),
  files: (workspace: string) => request<{ files: string[]; truncated: boolean; git: boolean }>(`/api/workspace/files?${q({ path: workspace })}`),
  file: (workspace: string, file: string) =>
    request<{ path: string; binary: boolean; truncated: boolean; content: string }>(`/api/workspace/file?${q({ path: workspace, file })}`),
  changes: (workspace: string) =>
    request<{ git: boolean; branch: string; files: { path: string; status: string }[]; diff: string }>(`/api/workspace/changes?${q({ path: workspace })}`),
  dirs: (path?: string) =>
    request<{ path: string; parent: string | null; git: boolean; entries: { name: string; path: string; git: boolean }[] }>(
      `/api/fs/dirs${path ? `?${q({ path })}` : ""}`,
    ),
  memory: (workspace: string, query?: string) =>
    request<{ items: MemoryItem[]; status: Health["memory"]; error?: string }>(`/api/memory?${q(query ? { path: workspace, q: query } : { path: workspace })}`),
  forget: (id: string) => request<{ ok: boolean }>(`/api/memory/${encodeURIComponent(id)}`, { method: "DELETE" }),
};
