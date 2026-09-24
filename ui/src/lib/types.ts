// The host's event envelope and the runtime payloads the UI renders.
// Runtime payload shapes are defined in runtime/kimi-agent/src/wire/types.rs
// and runtime/kosong/src/{message,tooling}.rs.

export type PermissionMode = "default" | "accept_edits" | "plan" | "yolo";

export interface WireEvent {
  seq: number;
  ts: number;
  turn: string | null;
  type: string;
  payload: any;
}

export interface DisplayBlock {
  type: string;
  text?: string;
  path?: string;
  old_text?: string;
  new_text?: string;
  items?: { title: string; status: string }[];
  language?: string;
  command?: string;
  [key: string]: unknown;
}

export interface ToolReturnValue {
  is_error: boolean;
  output: string | { type: string; text?: string }[];
  message: string;
  display: DisplayBlock[];
  extras?: Record<string, unknown> | null;
}

export interface TrustInfo {
  key: string;
  promotable: boolean;
  approvals: number;
  promote_after: number;
  tier?: "read" | "verify" | "needs_trust";
  effects?: string[];
  reasons?: string[];
}

export interface ApprovalRequest {
  id: string;
  tool_call_id: string;
  sender: string;
  action: string;
  description: string;
  display: DisplayBlock[];
  trust?: TrustInfo;
}

export interface TokenUsage {
  input_other: number;
  output: number;
  input_cache_read?: number;
  input_cache_creation?: number;
  cost_usd?: number | null;
}

export interface MemoryItem {
  id: string;
  memory: string;
  scope: "project" | "owner";
  score?: number;
  created_at?: string | null;
}

export interface SlashCommand {
  name: string;
  description: string;
  aliases: string[];
}

export interface Session {
  id: string;
  workspace: string;
  title: string;
  created_at: number;
  updated_at: number;
  permission_mode: PermissionMode;
  turns: number;
  last_status: string;
  grants: string[];
  kind: "session" | "candidate";
  parent: string;
  role: string;
  running: boolean;
  runtime_state: string;
  runtime: {
    model?: string;
    director?: string;
    memory?: string;
    sandbox?: string;
    slash_commands?: SlashCommand[];
    server?: { name?: string; version?: string };
  };
}

export interface Settings {
  openrouter_api_key: string;
  api_key_set: boolean;
  api_key_hint: string;
  api_key_source: "environment" | "settings" | "missing";
  base_url: string;
  model: string;
  max_context_size: number;
  reasoning_effort: string;
  max_steps_per_turn: number;
  director_mode: "on" | "shadow" | "off";
  memory_mode: "local" | "openrouter" | "off";
  memory_llm_model: string;
  memory_embedding_model: string;
  memory_embedding_dims: number;
  web_search: boolean;
  parallel_api_key: string;
  firecrawl_api_key: string;
  parallel_key_set: boolean;
  firecrawl_key_set: boolean;
  web_search_paid_fallback: boolean;
  search_model: string;
  learning_mode: "review" | "auto" | "off";
  learning_model: string;
  default_permission_mode: PermissionMode;
  recent_workspaces: string[];
}

export interface ModelInfo {
  id: string;
  name: string;
  context_length?: number | null;
  tools: boolean;
  reasoning: boolean;
  capabilities: string[];
  prompt_price?: string | null;
  completion_price?: string | null;
}

export interface Health {
  version: string;
  mode: "local" | "hosted";
  signed_in: boolean;
  runtime: { binary: string; error: string };
  memory: { requested_mode: string; active_mode: string; installed: boolean; version: string; ready: boolean; error: string };
  api_key_set: boolean;
  scripted: boolean;
}

export type ServerMessage =
  | { type: "hello"; session: Session; history: WireEvent[]; has_more: boolean; pending_approvals: ApprovalRequest[] }
  | { type: "event"; event: WireEvent }
  | { type: "session"; session: Session }
  | { type: "error"; message: string }
  | { type: "pong" };

export interface Attachment {
  name: string;
  mime: string;
  data: string; // base64
  preview?: string; // object URL for images
}

export interface Me {
  mode: "local" | "hosted";
  user: { id: string; name: string; admin: boolean };
  sandbox: string;
}

export interface TrustEntry {
  key: string;
  approvals: number;
  rejections: number;
  promoted: boolean;
  updated_at?: number;
}

export interface ProcessInfo {
  id: string;
  label: string;
  command: string;
  status: "running" | "exited" | "killed";
  exit_code: number | null;
  pid: number | null;
  runtime_seconds: number;
  output_tail?: string;
}

export interface LearningCandidate {
  id: string;
  kind: "skill" | "memory";
  status: "candidate" | "promoted" | "rejected";
  title: string;
  body: {
    name?: string;
    trigger?: string;
    lesson?: string;
    steps?: string[];
    verification?: string[];
    pitfalls?: string[];
    content?: string;
    scope?: string;
    kind?: string;
  };
  review_summary: string;
  updates_existing: boolean;
  session_id: string;
  workspace: string;
  created_at: number;
}

export interface LearnedSkill {
  name: string;
  description: string;
  updated_at: number;
  versions: number;
}

export interface FlowCandidate {
  id: string;
  status: string;
  session_id: string;
  attempts: number;
  verification: { command: string; exit_code: number | null; output_tail: string }[];
  diff: { sha256: string; changed_paths: string[]; stat: string; bytes: number } | null;
}

export interface Flow {
  id: string;
  status: "preparing" | "working" | "needs_review" | "ready_to_apply" | "applied" | "rolled_back" | "failed" | "cancelled";
  task: string;
  acceptance: string[];
  verification_commands: string[];
  repo: string;
  base_commit: string;
  owner_session: string;
  created_at: number;
  updated_at?: number;
  candidates: FlowCandidate[];
  selected: string | null;
  judgment: { winner: string; summary: string } | null;
  judge_error: string;
  apply: { applied_commit: string; diff_sha256: string } | null;
  rollback: { rollback_commit: string } | null;
  controls: { can_start: boolean; can_stop: boolean; can_select: boolean; can_review: boolean; can_apply: boolean; can_cancel: boolean; can_rollback: boolean };
  summary?: string;
  running?: boolean;
}

export interface FlowReview {
  flow_id: string;
  candidate_id: string;
  base_commit: string;
  diff: { sha256: string; changed_paths: string[]; stat: string; patch: string };
  judgment: Flow["judgment"];
}
