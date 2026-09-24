// How each tool call is named in the transcript: a verb and its subject.

import { parseArgs } from "./transcript.ts";

export type ToolIcon =
  | "terminal"
  | "file"
  | "edit"
  | "new"
  | "search"
  | "folder"
  | "globe"
  | "todo"
  | "agent"
  | "memory"
  | "image"
  | "plug";

export interface ToolView {
  icon: ToolIcon;
  verb: string;
  subject: string;
}

function short(text: unknown, max = 90): string {
  const value = String(text ?? "").replace(/\s+/g, " ").trim();
  return value.length > max ? `${value.slice(0, max - 1)}…` : value;
}

export function relativePath(path: string, workspace?: string): string {
  if (workspace && path.startsWith(`${workspace}/`)) return path.slice(workspace.length + 1);
  return path;
}

export function describeTool(name: string, rawArgs: string, workspace?: string): ToolView {
  const args = parseArgs(rawArgs) ?? {};
  const path = args.path ? relativePath(String(args.path), workspace) : "";
  switch (name) {
    case "Shell":
      return { icon: "terminal", verb: "Run", subject: short(args.command, 120) };
    case "ReadFile":
      return { icon: "file", verb: "Read", subject: path };
    case "ReadMediaFile":
      return { icon: "image", verb: "View", subject: path };
    case "WriteFile":
      return { icon: "new", verb: args.mode === "append" ? "Append" : "Write", subject: path };
    case "StrReplaceFile": {
      const edits = Array.isArray(args.edit) ? args.edit.length : args.edit ? 1 : 0;
      return { icon: "edit", verb: "Edit", subject: edits > 1 ? `${path} · ${edits} edits` : path };
    }
    case "Glob":
      return { icon: "folder", verb: "Find", subject: short(args.pattern) + (args.directory ? ` in ${relativePath(String(args.directory), workspace)}` : "") };
    case "Grep":
      return { icon: "search", verb: "Search", subject: short(args.pattern) + (args.path ? ` in ${relativePath(String(args.path), workspace)}` : "") };
    case "SearchWeb":
      return { icon: "globe", verb: "Search the web", subject: short(args.query) };
    case "FetchURL":
      return { icon: "globe", verb: "Fetch", subject: short(args.url) };
    case "SetTodoList": {
      const todos = Array.isArray(args.todos) ? args.todos : [];
      const done = todos.filter((t: any) => String(t.status).toLowerCase() === "done").length;
      return { icon: "todo", verb: "Update plan", subject: todos.length ? `${done}/${todos.length} done` : "" };
    }
    case "Task":
      return { icon: "agent", verb: `Delegate to ${args.subagent_name ?? "subagent"}`, subject: short(args.description) };
    case "CreateSubagent":
      return { icon: "agent", verb: "Create subagent", subject: short(args.name) };
    case "memory_recall":
      return { icon: "memory", verb: "Recall", subject: short(args.query) };
    case "memory_remember":
      return { icon: "memory", verb: "Remember", subject: short(args.content) };
    case "memory_checkpoint":
      return { icon: "memory", verb: "Checkpoint", subject: short(args.summary) };
    case "Think":
      return { icon: "agent", verb: "Think", subject: short(args.thought) };
    default:
      return { icon: "plug", verb: name, subject: short(Object.values(args)[0] ?? "") };
  }
}
