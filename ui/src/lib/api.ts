import type { Flow, FlowReview, Health, LearnedSkill, LearningCandidate, Me, MemoryItem, ModelInfo, ProcessInfo, Session, Settings, TrustEntry, WireEvent } from "./types.ts";

let bootstrapped: Promise<void> | null = null;

/** The local app's same-site cookie. A hosted server answers 403: sign in instead. */
export function bootstrap(): Promise<void> {
  bootstrapped ??= fetch("/api/auth/bootstrap", { method: "POST", credentials: "same-origin" }).then((r) => {
    if (!r.ok && r.status !== 403) throw new Error(`Could not reach the root server (${r.status}).`);
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
const post = <T>(path: string, body: unknown = {}) => request<T>(path, { method: "POST", body: JSON.stringify(body) });

export const api = {
  health: () => request<Health>("/api/health"),
  me: () => request<Me>("/api/me"),
  login: (token: string) => post<{ ok: boolean }>("/api/auth/login", { token }),
  logout: () => post<{ ok: boolean }>("/api/auth/logout"),
  settings: () => request<Settings>("/api/settings"),
  saveSettings: (changes: Partial<Settings> & Record<string, unknown>) => request<Settings>("/api/settings", { method: "PUT", body: JSON.stringify(changes) }),
  models: (refresh = false) => request<{ models: ModelInfo[]; error: string }>(`/api/models${refresh ? "?refresh=true" : ""}`),
  sessions: () => request<{ sessions: Session[] }>("/api/sessions"),
  createSession: (workspace: string) => post<Session>("/api/sessions", { workspace }),
  updateSession: (id: string, changes: { title?: string; permission_mode?: string }) =>
    request<Session>(`/api/sessions/${id}`, { method: "PATCH", body: JSON.stringify(changes) }),
  deleteSession: (id: string) => request<{ ok: boolean }>(`/api/sessions/${id}`, { method: "DELETE" }),
  events: (id: string, before: number) => request<{ events: WireEvent[]; has_more: boolean; first_seq: number | null }>(`/api/sessions/${id}/events?${q({ before: String(before) })}`),
  director: (id: string) => request<{ decisions: any[] }>(`/api/sessions/${id}/director`),
  revokeGrant: (id: string, key: string) => post<Session>(`/api/sessions/${id}/grants/revoke`, { key }),
  processes: (id: string) => request<{ processes: ProcessInfo[] }>(`/api/sessions/${id}/processes`),
  processLog: (id: string, pid: string) => request<{ lines: string[]; total_lines: number; status: string }>(`/api/sessions/${id}/processes/${pid}/log`),
  killProcess: (id: string, pid: string) => post<ProcessInfo>(`/api/sessions/${id}/processes/${pid}/kill`),
  files: (workspace: string) => request<{ files: string[]; truncated: boolean; git: boolean }>(`/api/workspace/files?${q({ path: workspace })}`),
  file: (workspace: string, file: string) =>
    request<{ path: string; binary: boolean; truncated: boolean; content: string }>(`/api/workspace/file?${q({ path: workspace, file })}`),
  changes: (workspace: string) =>
    request<{ git: boolean; branch: string; files: { path: string; status: string }[]; diff: string }>(`/api/workspace/changes?${q({ path: workspace })}`),
  dirs: (path?: string) =>
    request<{ path: string; parent: string | null; git: boolean; entries: { name: string; path: string; git: boolean }[] }>(`/api/fs/dirs${path ? `?${q({ path })}` : ""}`),
  createWorkspace: (name: string, gitUrl = "") => post<{ path: string }>("/api/workspaces", { name, git_url: gitUrl }),
  memory: (workspace: string, query?: string) =>
    request<{ items: MemoryItem[]; status: Health["memory"]; error?: string }>(`/api/memory?${q(query ? { path: workspace, q: query } : { path: workspace })}`),
  forget: (id: string, workspace: string) => request<{ ok: boolean }>(`/api/memory/${encodeURIComponent(id)}?${q({ path: workspace })}`, { method: "DELETE" }),
  trust: () => request<{ entries: TrustEntry[]; promote_after: number }>("/api/trust"),
  revokeTrust: (key: string) => post<{ ok: boolean }>("/api/trust/revoke", { key }),
  classify: (command: string) => post<{ tier: string; key: string; effects: string[]; reasons: string[] }>("/api/classify", { command }),
  learning: () => request<{ mode: Settings["learning_mode"]; candidates: LearningCandidate[]; skills: LearnedSkill[] }>("/api/learning"),
  promote: (id: string) => post<LearningCandidate>(`/api/learning/${id}/promote`),
  reject: (id: string) => post<LearningCandidate>(`/api/learning/${id}/reject`),
  skill: (name: string) => request<{ name: string; text: string }>(`/api/skills/${encodeURIComponent(name)}`),
  rollbackSkill: (name: string) => post<{ ok: boolean }>(`/api/skills/${encodeURIComponent(name)}/rollback`),
  forgetSkill: (name: string) => request<{ ok: boolean }>(`/api/skills/${encodeURIComponent(name)}`, { method: "DELETE" }),
  flows: () => request<{ flows: Flow[] }>("/api/flows"),
  flow: (id: string) => request<Flow>(`/api/flows/${id}`),
  flowReview: (id: string) => request<FlowReview>(`/api/flows/${id}/review`),
  flowAction: (id: string, action: "start" | "stop" | "cancel") => post<Flow>(`/api/flows/${id}/${action}`),
  flowSelect: (id: string, candidate: string) => post<Flow>(`/api/flows/${id}/select`, { candidate_id: candidate }),
  flowApply: (id: string, sha: string) => post<Flow>(`/api/flows/${id}/apply`, { review_sha256: sha }),
  flowRollback: (id: string, commit: string) => post<Flow>(`/api/flows/${id}/rollback`, { applied_commit: commit }),
};
