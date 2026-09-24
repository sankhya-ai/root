import { useCallback, useEffect, useState } from "react";

import { Home } from "./components/Home.tsx";
import { NewSessionDialog } from "./components/NewSessionDialog.tsx";
import { FlowsPage } from "./components/pages/FlowsPage.tsx";
import { LearningPage } from "./components/pages/LearningPage.tsx";
import { TrustPage } from "./components/pages/TrustPage.tsx";
import { Rail, type View } from "./components/Rail.tsx";
import { SessionView } from "./components/SessionView.tsx";
import { SettingsDialog } from "./components/SettingsDialog.tsx";
import { SignIn } from "./components/SignIn.tsx";
import { api } from "./lib/api.ts";
import type { Health, Me, PermissionMode, Session, Settings } from "./lib/types.ts";

type Theme = "dark" | "light";
type Route = { view: View; id: string | null };

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

function routeFromHash(): Route {
  const session = /^#\/s\/([0-9a-f]+)$/.exec(location.hash);
  if (session) return { view: "session", id: session[1] };
  const page = /^#\/(learning|flows|trust)$/.exec(location.hash);
  return { view: page ? (page[1] as View) : "home", id: null };
}

export function App() {
  const [theme, setTheme] = useState<Theme>(() => stored<Theme>("root:theme", matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark"));
  const [railCollapsed, setRailCollapsed] = useState(() => stored<string>("root:rail", "open") === "collapsed");
  const [inspectorOpen, setInspectorOpen] = useState(() => stored<string>("root:inspector", "closed") === "open");
  const [route, setRoute] = useState<Route>(routeFromHash);
  const [sessions, setSessions] = useState<Session[]>([]);
  const [health, setHealth] = useState<Health | null>(null);
  const [me, setMe] = useState<Me | null>(null);
  const [settings, setSettings] = useState<Settings | null>(null);
  const [learningBadge, setLearningBadge] = useState(0);
  const [dialog, setDialog] = useState<"settings" | "pick" | null>(null);
  const [picked, setPicked] = useState<((path: string) => void) | null>(null);
  const [firstPrompt, setFirstPrompt] = useState<{ id: string; text: string } | null>(null);
  const [loadError, setLoadError] = useState("");

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    persist("root:theme", theme);
  }, [theme]);

  const refresh = useCallback(() => {
    api.sessions().then(
      (d) => {
        setSessions(d.sessions);
        setLoadError("");
      },
      (e) => setLoadError(String(e.message)),
    );
    api.learning().then((d) => setLearningBadge(d.candidates.filter((c) => c.status === "candidate").length), () => undefined);
  }, []);

  useEffect(() => {
    api.health().then((h) => {
      setHealth(h);
      if (h.mode === "hosted" && !h.signed_in) return;
      refresh();
      api.me().then(setMe, () => undefined);
      api.settings().then(setSettings, () => undefined);
    }, (e) => setLoadError(String(e.message)));
    const timer = setInterval(refresh, 8000);
    const onHash = () => setRoute(routeFromHash());
    window.addEventListener("hashchange", onHash);
    return () => {
      clearInterval(timer);
      window.removeEventListener("hashchange", onHash);
    };
  }, [refresh]);

  const go = (hash: string) => {
    location.hash = hash;
    setRoute(routeFromHash());
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

  const pickFolder = (then: (path: string) => void) => {
    setPicked(() => then);
    setDialog("pick");
  };

  const startSession = async (workspace: string, text: string, mode: PermissionMode) => {
    const session = await api.createSession(workspace);
    if (mode !== session.permission_mode) await api.updateSession(session.id, { permission_mode: mode });
    setSessions((current) => [{ ...session, permission_mode: mode }, ...current]);
    if (text.trim()) setFirstPrompt({ id: session.id, text });
    go(`#/s/${session.id}`);
    api.settings().then(setSettings, () => undefined);
  };

  const deleteSession = async (session: Session) => {
    if (!confirm(`Delete “${session.title}”? The conversation is removed; files it changed are not touched.`)) return;
    await api.deleteSession(session.id);
    setSessions((current) => current.filter((s) => s.id !== session.id));
    if (route.id === session.id) go("#/");
  };

  if (health?.mode === "hosted" && !health.signed_in) return <SignIn />;

  const inspector = inspectorOpen && route.view === "session";
  const stageClass = ["stage", inspector ? "withInspector" : "", railCollapsed ? "railCollapsed" : ""].filter(Boolean).join(" ");

  return (
    <div className={stageClass}>
      <Rail
        sessions={sessions}
        activeId={route.id}
        view={route.view}
        collapsed={railCollapsed}
        theme={theme}
        learningBadge={learningBadge}
        user={me?.mode === "hosted" ? me.user.name : null}
        onToggleCollapsed={() => {
          setRailCollapsed((v) => !v);
          persist("root:rail", railCollapsed ? "open" : "collapsed");
        }}
        onNavigate={(view) => go(view === "home" ? "#/" : `#/${view}`)}
        onSelect={(id) => go(`#/s/${id}`)}
        onNew={() => pickFolder((path) => void startSession(path, "", settings?.default_permission_mode ?? "default"))}
        onDelete={deleteSession}
        onSettings={() => setDialog("settings")}
        onTheme={() => setTheme((t) => (t === "dark" ? "light" : "dark"))}
        onSignOut={me?.mode === "hosted" ? () => api.logout().then(() => location.reload()) : undefined}
      />
      {route.view === "session" && route.id ? (
        <SessionView
          key={route.id}
          sessionId={route.id}
          health={health}
          initialPrompt={firstPrompt?.id === route.id ? firstPrompt.text : undefined}
          onInitialSent={() => setFirstPrompt(null)}
          inspectorOpen={inspectorOpen}
          onToggleInspector={() => {
            setInspectorOpen((v) => !v);
            persist("root:inspector", inspectorOpen ? "closed" : "open");
          }}
          onSessionChange={onSessionChange}
          onOpenSettings={() => setDialog("settings")}
        />
      ) : null}
      {route.view === "home" ? (
        <Home
          key={settings?.recent_workspaces?.[0] ?? "none"}
          recent={settings?.recent_workspaces ?? []}
          error={loadError || health?.runtime.error || (health && !health.api_key_set && !health.scripted ? "Add an OpenRouter key in Settings to start." : "")}
          onPickFolder={pickFolder}
          onStart={startSession}
        />
      ) : null}
      {route.view === "learning" ? <LearningPage /> : null}
      {route.view === "flows" ? <FlowsPage /> : null}
      {route.view === "trust" ? <TrustPage /> : null}
      {dialog === "settings" ? (
        <SettingsDialog
          health={health}
          onClose={() => setDialog(null)}
          onSaved={(saved) => {
            setSettings(saved);
            api.health().then(setHealth, () => undefined);
          }}
        />
      ) : null}
      {dialog === "pick" ? (
        <NewSessionDialog
          recent={settings?.recent_workspaces ?? []}
          hosted={health?.mode === "hosted"}
          title="Choose a folder"
          action="Use this folder"
          onClose={() => setDialog(null)}
          onCreate={async (path) => {
            setDialog(null);
            picked?.(path);
          }}
        />
      ) : null}
    </div>
  );
}
