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
  /** Set when the request reaches outside the session's workspace. */
  outside?: string;
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
  provider_sort: string;
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

// ── Multi-human & Multi-agent Squads ──

export type IssueStatus = "backlog" | "in_progress" | "blocked" | "in_review" | "done";
export type IssuePriority = "low" | "medium" | "high" | "urgent";
export type AssigneeType = "human" | "agent" | "unassigned";
export type WorkspaceScope = "personal" | "shared";

export interface TeamCollaborator {
  user_id: string; // e.g. "chitranjan", "nitin", "ashish"
  user_name: string; // e.g. "Chitranjan", "Nitin", "Ashish"
  agent_id: string; // e.g. "antigravity", "claude_code", "codex", "root"
  agent_name: string; // e.g. "Antigravity", "Claude Code", "Codex", "Root"
  status: "active" | "working" | "idle" | "holding_lease" | "waiting_on_human";
  current_activity: string;
  last_active?: number;
}

export interface IntercomMessage {
  id: string;
  sender_id: string;
  sender_name: string;
  sender_type: "human" | "agent";
  agent_name: string;
  recipient: string; // "@all-agents", "@Antigravity", "@Claude-Code", "@Codex", etc.
  content: string;
  action_type:
    | "message"
    | "instruction"
    | "lease_notice"
    | "broadcast"
    | "handoff"
    | "agent_query"
    | "agent_response"
    | "lease_claimed"
    | "agreement_synced"
    | string;
  files_mentioned?: string[];
  created_at: number;
}

export interface SquadMember {
  id: string;
  type: "human" | "agent";
  name: string;
  role: string;
  user_id?: string;
  user_name?: string;
  agent_id?: string;
  agent_name?: string;
}

export interface Squad {
  id: string;
  name: string;
  description: string;
  members: TeamCollaborator[];
  created_at: number;
  updated_at: number;
}

export interface IssueComment {
  id: string;
  author_type: "human" | "agent";
  author_id: string;
  content: string;
  created_at: number;
}

export interface ExecutionStep {
  id: string;
  run_id?: string;
  timestamp: number;
  agent_name: string;
  user_name: string;
  phase: "Search" | "Inspect" | "Edit" | "Test" | "Verify" | "Gate" | string;
  tool?: string;
  target_file?: string;
  activity: string;
  output_snippet?: string;
  status: "completed" | "running" | "failed";
}

export interface ExecutionRun {
  id: string;
  issue_id: string;
  agent_name: string;
  user_name: string;
  status: "running" | "completed" | "failed" | "paused";
  phase: string;
  step_count: number;
  current_step: number;
  current_activity: string;
  active_file?: string;
  last_tool?: string;
  started_at: number;
  updated_at: number;
  completed_at?: number | null;
}

export interface Issue {
  id: string;
  title: string;
  description: string;
  status: IssueStatus;
  priority: IssuePriority;
  squad_id: string;
  assignee_type?: AssigneeType;
  assignee_id?: string;
  workspace_scope: WorkspaceScope;
  workspace_path: string;
  branch?: string;
  flow_id?: string | null;
  diff?: string | null;
  verification_command?: string;
  verification_output?: string | null;
  verification_passed?: boolean | null;
  blocker_reason?: string | null;
  collaborators?: TeamCollaborator[];
  messages?: IntercomMessage[];
  active_leases?: Record<string, string>;
  active_run?: ExecutionRun | null;
  runs?: ExecutionRun[];
  execution_timeline?: ExecutionStep[];
  comments?: IssueComment[];
  lane_id?: string | null;
  created_by: string;
  created_at: number;
  updated_at: number;
}


export interface BusState {
  ready: boolean;
  lanes: { id: string; session_id: string; from_agent: string; to_agent: string; status: string; context: any }[];
  signals: { id: number; topic: string; data: any; agent_id: string | null; timestamp: string }[];
  agents: { agent_id: string; metadata: any; first_seen: string; last_seen: string }[];
  leases: Record<string, { agent_id: string; acquired_at: number }>;
}
