import { useCallback, useEffect, useState } from "react";

import { NewSessionDialog } from "./components/NewSessionDialog.tsx";
import { Rail } from "./components/Rail.tsx";
import { SessionView } from "./components/SessionView.tsx";
import { SettingsDialog } from "./components/SettingsDialog.tsx";
import { TuraMark } from "./components/TuraBrand.tsx";
import { api } from "./lib/api.ts";
import type { Health, Session, Settings } from "./lib/types.ts";

type Theme = "dark" | "light";

function stored<T extends string>(key: string, fallback: T): T {
  try {
    return (localStorage.getItem(key) as T) || fallback;
  } catch {
    return fallback;
  }
}

function persist(key: string, value: string) {
  try {
    localStorage.setItem(key, value);
  } catch {
    /* storage unavailable */
  }
}

function sessionFromHash(): string | null {
  const match = /^#\/s\/([0-9a-f]+)$/.exec(location.hash);
  return match ? match[1] : null;
}

export function App() {
  const [theme, setTheme] = useState<Theme>(() => stored<Theme>("tura-code:theme", matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark"));
  const [railCollapsed, setRailCollapsed] = useState(() => stored<string>("tura-code:rail", "open") === "collapsed");
  const [inspectorOpen, setInspectorOpen] = useState(() => stored<string>("tura-code:inspector", "closed") === "open");
  const [sessions, setSessions] = useState<Session[]>([]);
  const [activeId, setActiveId] = useState<string | null>(sessionFromHash);
  const [health, setHealth] = useState<Health | null>(null);
  const [settings, setSettings] = useState<Settings | null>(null);
  const [dialog, setDialog] = useState<"settings" | "new" | null>(null);
  const [loadError, setLoadError] = useState("");

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    persist("tura-code:theme", theme);
  }, [theme]);

  const refresh = useCallback(() => {
    api.sessions().then(
      (d) => {
        setSessions(d.sessions);
        setLoadError("");
      },
      (e) => setLoadError(String(e.message)),
    );
  }, []);

  useEffect(() => {
    refresh();
    api.health().then(setHealth, () => undefined);
    api.settings().then(setSettings, () => undefined);
    const timer = setInterval(refresh, 8000);
    const onHash = () => setActiveId(sessionFromHash());
    window.addEventListener("hashchange", onHash);
    return () => {
      clearInterval(timer);
      window.removeEventListener("hashchange", onHash);
    };
  }, [refresh]);

  const select = (id: string | null) => {
    location.hash = id ? `#/s/${id}` : "";
    setActiveId(id);
  };

  const onSessionChange = useCallback((session: Session) => {
    setSessions((current) => {
      const index = current.findIndex((s) => s.id === session.id);
      if (index < 0) return [session, ...current];
      const next = current.slice();
      next[index] = { ...current[index], ...session };
      return next;
    });
  }, []);

  const createSession = async (workspace: string) => {
    const session = await api.createSession(workspace);
    setDialog(null);
    setSessions((current) => [session, ...current]);
    select(session.id);
    api.settings().then(setSettings, () => undefined);
  };

  const deleteSession = async (session: Session) => {
    if (!confirm(`Delete “${session.title}”? The conversation is removed; files it changed are not touched.`)) return;
    await api.deleteSession(session.id);
    setSessions((current) => current.filter((s) => s.id !== session.id));
    if (activeId === session.id) select(null);
  };

  const onSettingsSaved = (saved: Settings) => {
    setSettings(saved);
    api.health().then(setHealth, () => undefined);
  };

  const stageClass = ["stage", inspectorOpen && activeId ? "withInspector" : "", railCollapsed ? "railCollapsed" : ""].filter(Boolean).join(" ");

  return (
    <div className={stageClass}>
      <Rail
        sessions={sessions}
        activeId={activeId}
        collapsed={railCollapsed}
        theme={theme}
        onToggleCollapsed={() => {
          setRailCollapsed((v) => !v);
          persist("tura-code:rail", railCollapsed ? "open" : "collapsed");
        }}
        onSelect={select}
        onNew={() => setDialog("new")}
        onDelete={deleteSession}
        onSettings={() => setDialog("settings")}
        onTheme={() => setTheme((t) => (t === "dark" ? "light" : "dark"))}
      />
      {activeId ? (
        <SessionView
          key={activeId}
          sessionId={activeId}
          health={health}
          inspectorOpen={inspectorOpen}
          onToggleInspector={() => {
            setInspectorOpen((v) => !v);
            persist("tura-code:inspector", inspectorOpen ? "closed" : "open");
          }}
          onSessionChange={onSessionChange}
          onOpenSettings={() => setDialog("settings")}
        />
      ) : (
        <main className="card body">
          <div className="empty" style={{ minHeight: "100%" }}>
            <TuraMark size={54} />
            <h2>root</h2>
            <p className="muted" style={{ maxWidth: 520, margin: 0 }}>
              A coding agent that works across your whole project — reading, editing many files, running commands and tests — with <strong>Jev</strong> steering each step
              and <strong>Dhee</strong> remembering what matters between sessions.
            </p>
            {loadError ? <p style={{ color: "var(--err)" }}>{loadError}</p> : null}
            {health?.runtime.error ? <p style={{ color: "var(--err)", maxWidth: 560 }}>{health.runtime.error}</p> : null}
            {health && !health.api_key_set && !health.scripted ? (
              <button className="button" onClick={() => setDialog("settings")}>
                Add your OpenRouter key
              </button>
            ) : null}
            <button className="primaryButton" style={{ marginTop: 6 }} onClick={() => setDialog("new")}>
              Start a session in a folder
            </button>
          </div>
        </main>
      )}
      {dialog === "settings" ? <SettingsDialog health={health} onClose={() => setDialog(null)} onSaved={onSettingsSaved} /> : null}
      {dialog === "new" ? <NewSessionDialog recent={settings?.recent_workspaces ?? []} onClose={() => setDialog(null)} onCreate={createSession} /> : null}
    </div>
  );
}
