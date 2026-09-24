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

export interface ApprovalRequest {
  id: string;
  tool_call_id: string;
  sender: string;
  action: string;
  description: string;
  display: DisplayBlock[];
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
  running: boolean;
  runtime_state: string;
  runtime: {
    model?: string;
    director?: string;
    memory?: string;
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
  search_model: string;
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
  runtime: { binary: string; error: string };
  memory: { requested_mode: string; active_mode: string; installed: boolean; version: string; ready: boolean; error: string };
  api_key_set: boolean;
  scripted: boolean;
}

export type ServerMessage =
  | { type: "hello"; session: Session; history: WireEvent[]; pending_approvals: ApprovalRequest[] }
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
