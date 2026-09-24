import { FolderGit2, Moon, PanelLeftClose, PanelLeftOpen, Plus, Settings2, Sun, Trash2 } from "lucide-react";

import type { Session } from "../lib/types.ts";
import { Brand, TuraMark } from "./TuraBrand.tsx";

function basename(path: string): string {
  return path.split("/").filter(Boolean).pop() ?? path;
}

export function Rail({
  sessions,
  activeId,
  collapsed,
  theme,
  onToggleCollapsed,
  onSelect,
  onNew,
  onDelete,
  onSettings,
  onTheme,
}: {
  sessions: Session[];
  activeId: string | null;
  collapsed: boolean;
  theme: "dark" | "light";
  onToggleCollapsed: () => void;
  onSelect: (id: string) => void;
  onNew: () => void;
  onDelete: (session: Session) => void;
  onSettings: () => void;
  onTheme: () => void;
}) {
  if (collapsed) {
    return (
      <aside className="card rail" style={{ alignItems: "center", padding: "14px 6px 10px" }}>
        <TuraMark />
        <button className="iconButton" onClick={onToggleCollapsed} title="Expand sidebar">
          <PanelLeftOpen size={17} />
        </button>
        <button className="primaryButton" style={{ width: 40, padding: 0 }} onClick={onNew} title="New session">
          <Plus size={18} />
        </button>
        <div style={{ flex: 1 }} />
        <button className="iconButton" onClick={onTheme} title="Toggle theme">
          {theme === "dark" ? <Sun size={16} /> : <Moon size={16} />}
        </button>
        <button className="iconButton" onClick={onSettings} title="Settings">
          <Settings2 size={16} />
        </button>
      </aside>
    );
  }

  const groups = new Map<string, Session[]>();
  for (const session of sessions) {
    const list = groups.get(session.workspace) ?? [];
    list.push(session);
    groups.set(session.workspace, list);
  }

  return (
    <aside className="card rail">
      <div className="railHead">
        <Brand />
        <button className="iconButton" onClick={onToggleCollapsed} title="Collapse sidebar">
          <PanelLeftClose size={17} />
        </button>
      </div>
      <button className="primaryButton" onClick={onNew}>
        <Plus size={17} /> New session
      </button>
      <div className="railLabel">Sessions</div>
      <nav className="sessionList scroll">
        {sessions.length === 0 ? <p className="faint small" style={{ padding: "0 8px" }}>No sessions yet. Start one in any folder.</p> : null}
        {[...groups.entries()].map(([workspace, list]) => (
          <div key={workspace} className="workspaceGroup">
            <div className="workspaceName" title={workspace}>
              <FolderGit2 size={13} /> {basename(workspace)}
            </div>
            {list.map((session) => (
              <div key={session.id} className={`sessionRow${session.id === activeId ? " active" : ""}`} role="button" tabIndex={0} onClick={() => onSelect(session.id)} onKeyDown={(e) => e.key === "Enter" && onSelect(session.id)}>
                {session.running ? <span className="runningDot" title="Working" /> : <span className="idleDot" />}
                <span className="title" title={session.title}>
                  {session.title}
                </span>
                <button
                  className="iconButton rowAction"
                  style={{ minHeight: 24, minWidth: 24, padding: 0 }}
                  title="Delete session"
                  onClick={(e) => {
                    e.stopPropagation();
                    onDelete(session);
                  }}
                >
                  <Trash2 size={13} />
                </button>
              </div>
            ))}
          </div>
        ))}
      </nav>
      <div className="railFoot">
        <button className="iconButton" onClick={onSettings} style={{ flex: 1, justifyContent: "flex-start" }}>
          <Settings2 size={16} /> Settings
        </button>
        <button className="iconButton" onClick={onTheme} title="Toggle theme">
          {theme === "dark" ? <Sun size={16} /> : <Moon size={16} />}
        </button>
      </div>
    </aside>
  );
}
