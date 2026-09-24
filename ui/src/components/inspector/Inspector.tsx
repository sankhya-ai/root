import { X } from "lucide-react";

import type { TodoItem } from "../../lib/transcript.ts";
import type { ProcessInfo, Session } from "../../lib/types.ts";
import { TodoItems } from "../turn/Steps.tsx";
import { ChangesPanel } from "./ChangesPanel.tsx";
import { FilesPanel } from "./FilesPanel.tsx";
import { JevPanel } from "./JevPanel.tsx";
import { MemoryPanel } from "./MemoryPanel.tsx";
import { ProcessesPanel } from "./ProcessesPanel.tsx";

export type InspectorTab = "changes" | "files" | "plan" | "memory" | "processes" | "jev";

const TABS: { id: InspectorTab; label: string }[] = [
  { id: "changes", label: "Changes" },
  { id: "files", label: "Files" },
  { id: "plan", label: "Plan" },
  { id: "memory", label: "Memory" },
  { id: "processes", label: "Processes" },
  { id: "jev", label: "Jev" },
];

export function Inspector({
  tab,
  onTab,
  onClose,
  workspace,
  session,
  todos,
  processes,
  refreshKey,
  files,
  onMention,
}: {
  tab: InspectorTab;
  onTab: (tab: InspectorTab) => void;
  onClose: () => void;
  workspace: string;
  session: Session;
  todos: TodoItem[];
  processes: ProcessInfo[];
  refreshKey: number;
  files: string[];
  onMention: (path: string) => void;
}) {
  const running = processes.filter((p) => p.status === "running").length;
  return (
    <aside className="card inspector">
      <div className="tabs">
        {TABS.map((t) => (
          <button key={t.id} className={`tab${tab === t.id ? " active" : ""}`} onClick={() => onTab(t.id)}>
            {t.label}
            {t.id === "processes" && running ? ` · ${running}` : ""}
          </button>
        ))}
        <span style={{ flex: 1 }} />
        <button className="iconButton" onClick={onClose} title="Close panel">
          <X size={15} />
        </button>
      </div>
      <div className="tabBody scroll">
        {tab === "changes" ? <ChangesPanel workspace={workspace} refreshKey={refreshKey} /> : null}
        {tab === "files" ? <FilesPanel workspace={workspace} files={files} onMention={onMention} /> : null}
        {tab === "plan" ? (
          todos.length ? (
            <TodoItems items={todos} />
          ) : (
            <p className="help">The agent writes its plan here with SetTodoList when a task has several steps.</p>
          )
        ) : null}
        {tab === "memory" ? <MemoryPanel workspace={workspace} refreshKey={refreshKey} /> : null}
        {tab === "processes" ? <ProcessesPanel sessionId={session.id} live={processes} /> : null}
        {tab === "jev" ? <JevPanel sessionId={session.id} refreshKey={refreshKey} /> : null}
      </div>
    </aside>
  );
}
