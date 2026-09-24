import assert from "node:assert/strict";
import { test } from "node:test";

import { groupBlocks, type Activity } from "./activity.ts";
import { applyEvent, createTranscript } from "./transcript.ts";
import type { WireEvent } from "./types.ts";

let seq = 0;
const ev = (type: string, payload: any = {}): WireEvent => ({ seq: ++seq, ts: 0, turn: "t", type, payload });
const ok = { is_error: false, output: "", message: "", display: [] };

function call(state: ReturnType<typeof createTranscript>, id: string, name: string, args: any, result: any = ok) {
  applyEvent(state, ev("ToolCall", { id, function: { name, arguments: JSON.stringify(args) } }));
  if (result) applyEvent(state, ev("ToolResult", { tool_call_id: id, return_value: result }));
}

test("inspection steps fold into one sentence and edits into another", () => {
  const s = createTranscript();
  applyEvent(s, ev("UserPrompt", { text: "go" }));
  call(s, "1", "ReadFile", { path: "app/stats.py" });
  call(s, "2", "ReadFile", { path: "app/test_stats.py" });
  call(s, "3", "Grep", { pattern: "mean(" });
  call(s, "4", "StrReplaceFile", { path: "/ws/app/stats.py", edit: { old: "a", new: "b" } });
  call(s, "5", "WriteFile", { path: "/ws/app/test_stats.py", content: "x" });
  call(s, "6", "Shell", { command: "pytest -q" });
  applyEvent(s, ev("ContentPart", { type: "text", text: "Done" }));
  const items = groupBlocks(s.blocks, { running: false, workspace: "/ws" });
  const acts = items.filter((i): i is Activity => i.kind === "activity");
  assert.deepEqual(acts.map((a) => a.label), ["Read 2 files, searched code", "Edited 2 files", "Run pytest -q"]);
  assert.equal(acts[0].icon, "read");
  assert.equal(items[items.length - 1].kind, "text");
});

test("text between tool calls splits the lines; single edits name the file", () => {
  const s = createTranscript();
  call(s, "1", "StrReplaceFile", { path: "/ws/src/a.ts", edit: { old: "a", new: "b" } });
  applyEvent(s, ev("ContentPart", { type: "text", text: "Now the test." }));
  call(s, "2", "StrReplaceFile", { path: "/ws/src/a.ts", edit: [{ old: "a", new: "b" }, { old: "c", new: "d" }] });
  const acts = groupBlocks(s.blocks, { running: false, workspace: "/ws" }).filter((i): i is Activity => i.kind === "activity");
  assert.deepEqual(acts.map((a) => a.label), ["Edited a.ts", "Edited a.ts"]);
});

test("approvals, failures and running steps stand on their own lines", () => {
  const s = createTranscript();
  call(s, "1", "ReadFile", { path: "a.py" });
  call(s, "2", "Shell", { command: "rm -rf build" }, null);
  applyEvent(s, ev("ApprovalRequest", { id: "r", tool_call_id: "2", sender: "Shell", action: "run command", description: "", display: [] }));
  call(s, "3", "Shell", { command: "false" }, { ...ok, is_error: true, message: "exit 1" });
  call(s, "4", "Grep", { pattern: "x" }, null);
  const acts = groupBlocks(s.blocks, { running: true }).filter((i): i is Activity => i.kind === "activity");
  assert.deepEqual(acts.map((a) => [a.tone, a.label]), [
    ["done", "Read a.py"],
    ["permission", "Needs approval: Run rm -rf build"],
    ["error", "Failed: Run false"],
    ["working", "Search x…"],
  ]);
});

test("a finished turn with an unanswered call reads as interrupted, not running", () => {
  const s = createTranscript();
  call(s, "1", "Shell", { command: "sleep 100" }, null);
  const [act] = groupBlocks(s.blocks, { running: false }).filter((i): i is Activity => i.kind === "activity");
  assert.equal(act.tone, "muted");
});
