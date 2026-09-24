// Folds the session's event stream into blocks the transcript renders.
//
// Streaming makes this hot: a long answer is thousands of ContentPart deltas.
// So the fold mutates in place and the view re-renders on a version counter,
// rather than copying the whole transcript per delta.

import type { ApprovalRequest, DisplayBlock, MemoryItem, TokenUsage, ToolReturnValue, WireEvent } from "./types.ts";

export type ApprovalStatus = "pending" | "approve" | "approve_for_session" | "reject";

export interface ApprovalState {
  request: ApprovalRequest;
  status: ApprovalStatus;
  auto: boolean;
}

export type Block =
  | { kind: "user"; key: string; turn: string | null; text: string; attachments: { name: string; mime: string }[]; memory: MemoryItem[] }
  | { kind: "text"; key: string; turn: string | null; text: string }
  | { kind: "think"; key: string; turn: string | null; text: string }
  | {
      kind: "tool";
      key: string;
      turn: string | null;
      id: string;
      name: string;
      args: string;
      result?: ToolReturnValue;
      approval?: ApprovalState;
      children?: TranscriptState;
    }
  | { kind: "approval"; key: string; turn: string | null; approval: ApprovalState }
  | { kind: "notice"; key: string; turn: string | null; tone: "info" | "warn" | "error"; text: string }
  | {
      kind: "turn_end";
      key: string;
      turn: string | null;
      status: string;
      duration?: number;
      error?: string;
      files: string[];
      usage: UsageTotals;
    };

export type ToolBlock = Extract<Block, { kind: "tool" }>;

export interface UsageTotals {
  input: number;
  output: number;
  cacheRead: number;
  cost: number;
}

export interface TodoItem {
  title: string;
  status: string;
}

export interface TranscriptState {
  blocks: Block[];
  running: boolean;
  contextUsage: number | null;
  usage: UsageTotals;
  turnUsage: UsageTotals;
  todos: TodoItem[];
  compacting: boolean;
  pending: Map<string, ApprovalState>;
  lastSeq: number;
  version: number;
}

export function emptyUsage(): UsageTotals {
  return { input: 0, output: 0, cacheRead: 0, cost: 0 };
}

export function createTranscript(): TranscriptState {
  return {
    blocks: [],
    running: false,
    contextUsage: null,
    usage: emptyUsage(),
    turnUsage: emptyUsage(),
    todos: [],
    compacting: false,
    pending: new Map(),
    lastSeq: 0,
    version: 0,
  };
}

let keyCounter = 0;
function nextKey(prefix: string): string {
  keyCounter += 1;
  return `${prefix}-${keyCounter}`;
}

function last(state: TranscriptState): Block | undefined {
  return state.blocks[state.blocks.length - 1];
}

function findTool(state: TranscriptState, id: string): ToolBlock | undefined {
  for (let i = state.blocks.length - 1; i >= 0; i -= 1) {
    const block = state.blocks[i];
    if (block.kind === "tool" && block.id === id) return block;
  }
  return undefined;
}

function lastTool(state: TranscriptState): ToolBlock | undefined {
  for (let i = state.blocks.length - 1; i >= 0; i -= 1) {
    const block = state.blocks[i];
    if (block.kind === "tool") return block;
  }
  return undefined;
}

function addUsage(total: UsageTotals, usage: TokenUsage | null | undefined): void {
  if (!usage) return;
  total.input += (usage.input_other ?? 0) + (usage.input_cache_read ?? 0) + (usage.input_cache_creation ?? 0);
  total.output += usage.output ?? 0;
  total.cacheRead += usage.input_cache_read ?? 0;
  total.cost += usage.cost_usd ?? 0;
}

function todosFrom(display: DisplayBlock[] | undefined): TodoItem[] | null {
  const block = display?.find((d) => d.type === "todo");
  return block?.items ? block.items.map((i) => ({ title: i.title, status: i.status })) : null;
}

/** Apply one event. Returns false for a replayed event already applied. */
export function applyEvent(state: TranscriptState, event: WireEvent, nested = false): boolean {
  if (!nested) {
    if (event.seq && event.seq <= state.lastSeq) return false;
    if (event.seq) state.lastSeq = event.seq;
  }
  const p = event.payload ?? {};
  const turn = event.turn ?? null;
  switch (event.type) {
    case "UserPrompt": {
      state.running = true;
      state.turnUsage = emptyUsage();
      state.blocks.push({
        kind: "user",
        key: nextKey("user"),
        turn,
        text: String(p.text ?? ""),
        attachments: Array.isArray(p.attachments) ? p.attachments : [],
        memory: Array.isArray(p.memory) ? p.memory : [],
      });
      break;
    }
    case "TurnBegin": {
      // A turn that begins again inside the same prompt has abandoned the
      // words of its first attempt; the tools it ran still happened.
      if (nested) break;
      let index = state.blocks.length - 1;
      while (index >= 0 && state.blocks[index].kind !== "user") index -= 1;
      if (index >= 0) {
        const kept = state.blocks.slice(index + 1).filter((b) => b.kind !== "text" && b.kind !== "think");
        state.blocks.splice(index + 1, state.blocks.length - index - 1, ...kept);
      }
      break;
    }
    case "ContentPart": {
      const partType = p.type;
      if (partType !== "text" && partType !== "think") break;
      const chunk = String(partType === "text" ? p.text ?? "" : p.think ?? "");
      const tail = last(state);
      if (tail && (tail.kind === "text" || tail.kind === "think") && tail.kind === partType) {
        tail.text += chunk;
      } else if (chunk) {
        state.blocks.push({ kind: partType, key: nextKey(partType), turn, text: chunk });
      }
      break;
    }
    case "ToolCall": {
      const fn = p.function ?? {};
      state.blocks.push({
        kind: "tool",
        key: nextKey("tool"),
        turn,
        id: String(p.id ?? ""),
        name: String(fn.name ?? p.name ?? "tool"),
        args: String(fn.arguments ?? ""),
      });
      break;
    }
    case "ToolCallPart": {
      const tool = lastTool(state);
      if (tool) tool.args += String(p.arguments_part ?? "");
      break;
    }
    case "ToolResult": {
      const tool = findTool(state, String(p.tool_call_id ?? ""));
      const value = p.return_value as ToolReturnValue | undefined;
      if (tool && value) {
        tool.result = value;
        if (tool.name === "SetTodoList") {
          const todos = todosFrom(value.display);
          if (todos) state.todos = todos;
        }
      }
      break;
    }
    case "ApprovalRequest": {
      const approval: ApprovalState = { request: p as ApprovalRequest, status: "pending", auto: false };
      state.pending.set(approval.request.id, approval);
      const tool = findTool(state, approval.request.tool_call_id);
      if (tool) tool.approval = approval;
      else state.blocks.push({ kind: "approval", key: nextKey("approval"), turn, approval });
      break;
    }
    case "ApprovalResolved": {
      const id = String(p.request_id ?? "");
      const status = (p.response ?? "reject") as ApprovalStatus;
      const existing = state.pending.get(id);
      if (existing) {
        existing.status = status;
        existing.auto = Boolean(p.auto);
        state.pending.delete(id);
      } else {
        const tool = findTool(state, String(p.tool_call_id ?? ""));
        const approval: ApprovalState = {
          request: {
            id,
            tool_call_id: String(p.tool_call_id ?? ""),
            sender: String(p.sender ?? ""),
            action: String(p.action ?? ""),
            description: String(p.description ?? ""),
            display: [],
          },
          status,
          auto: Boolean(p.auto),
        };
        if (tool) tool.approval = approval;
      }
      break;
    }
    case "StatusUpdate": {
      if (typeof p.context_usage === "number") state.contextUsage = p.context_usage;
      if (p.token_usage) {
        addUsage(state.usage, p.token_usage);
        addUsage(state.turnUsage, p.token_usage);
      }
      break;
    }
    case "CompactionBegin":
      state.compacting = true;
      state.blocks.push({ kind: "notice", key: nextKey("notice"), turn, tone: "info", text: "Compacting context…" });
      break;
    case "CompactionEnd": {
      state.compacting = false;
      for (let i = state.blocks.length - 1; i >= 0; i -= 1) {
        const block = state.blocks[i];
        if (block.kind === "notice" && block.text === "Compacting context…") {
          block.text = "Context compacted. Dhee restored durable memory into the summary.";
          break;
        }
      }
      break;
    }
    case "SubagentEvent": {
      const tool = findTool(state, String(p.task_tool_call_id ?? ""));
      const inner = p.event;
      if (tool && inner && typeof inner === "object") {
        tool.children ??= createTranscript();
        applyEvent(tool.children, { seq: 0, ts: event.ts, turn, type: String(inner.type ?? ""), payload: inner.payload ?? {} }, true);
      }
      break;
    }
    case "ModeChanged":
      state.blocks.push({ kind: "notice", key: nextKey("notice"), turn, tone: "info", text: `Permission mode: ${modeLabel(String(p.mode))}` });
      break;
    case "MemoryCheckpoint":
      break;
    case "RuntimeStatus": {
      if (p.state === "exited" || p.state === "failed") {
        state.blocks.push({
          kind: "notice",
          key: nextKey("notice"),
          turn,
          tone: "error",
          text: `Agent runtime ${p.state}${p.code != null ? ` (code ${p.code})` : ""}${p.detail ? `: ${String(p.detail).split("\n").slice(-3).join(" ")}` : ""}`,
        });
      }
      break;
    }
    case "StepInterrupted":
      break;
    case "TurnFinished": {
      state.running = false;
      for (const approval of state.pending.values()) approval.status = "reject";
      state.pending.clear();
      state.blocks.push({
        kind: "turn_end",
        key: nextKey("end"),
        turn,
        status: String(p.status ?? "finished"),
        duration: typeof p.duration === "number" ? p.duration : undefined,
        error: p.error ? String(p.error) : undefined,
        files: Array.isArray(p.files_touched) ? p.files_touched : [],
        usage: { ...state.turnUsage },
      });
      break;
    }
    default:
      break;
  }
  state.version += 1;
  return true;
}

export function loadHistory(events: WireEvent[], pending: ApprovalRequest[] = []): TranscriptState {
  const state = createTranscript();
  for (const event of events) applyEvent(state, event);
  // Approvals still waiting when the page loaded are live again.
  for (const request of pending) {
    const tool = findTool(state, request.tool_call_id);
    const approval: ApprovalState = tool?.approval?.request.id === request.id ? tool.approval : { request, status: "pending", auto: false };
    approval.status = "pending";
    state.pending.set(request.id, approval);
    if (tool) tool.approval = approval;
    else if (!state.blocks.some((b) => b.kind === "approval" && b.approval.request.id === request.id)) {
      state.blocks.push({ kind: "approval", key: nextKey("approval"), turn: null, approval });
    }
  }
  return state;
}

export function modeLabel(mode: string): string {
  switch (mode) {
    case "accept_edits":
      return "Accept edits";
    case "plan":
      return "Plan";
    case "yolo":
      return "Auto-approve all";
    default:
      return "Ask before acting";
  }
}

export function parseArgs(raw: string): Record<string, any> | null {
  if (!raw) return {};
  try {
    const value = JSON.parse(raw);
    return value && typeof value === "object" && !Array.isArray(value) ? value : null;
  } catch {
    return null;
  }
}

export function outputText(value: ToolReturnValue | undefined): string {
  if (!value) return "";
  if (typeof value.output === "string") return value.output;
  if (Array.isArray(value.output)) return value.output.map((part) => part.text ?? "").join("");
  return "";
}
