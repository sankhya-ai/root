import { Brain, Compass, Cpu, PanelRight, WifiOff, X } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { api } from "../lib/api.ts";
import { useSession } from "../lib/useSession.ts";
import type { Attachment, Health, PermissionMode, Session, SlashCommand } from "../lib/types.ts";
import { Composer } from "./Composer.tsx";
import { Inspector, type InspectorTab } from "./Inspector.tsx";
import { MODE_ORDER, ModeMenu } from "./ModeMenu.tsx";
import { Transcript } from "./Transcript.tsx";

const DEFAULT_COMMANDS: SlashCommand[] = [
  { name: "init", description: "Analyze the codebase and write an AGENTS.md", aliases: [] },
  { name: "compact", description: "Compact the context", aliases: [] },
  { name: "clear", description: "Clear the context", aliases: ["reset"] },
];

const SUGGESTIONS = [
  "Give me a tour of this codebase: structure, entry points, and how to run it.",
  "Find and fix the failing tests.",
  "Review the uncommitted changes for bugs.",
  "Run /init to write an AGENTS.md for this project.",
];

export function SessionView({
  sessionId,
  health,
  inspectorOpen,
  onToggleInspector,
  onSessionChange,
  onOpenSettings,
}: {
  sessionId: string;
  health: Health | null;
  inspectorOpen: boolean;
  onToggleInspector: () => void;
  onSessionChange: (session: Session) => void;
  onOpenSettings: () => void;
}) {
  const handle = useSession(sessionId, onSessionChange);
  const { transcript, session, connection, error } = handle;
  const [tab, setTab] = useState<InspectorTab>("plan");
  const [files, setFiles] = useState<string[]>([]);
  const [refreshKey, setRefreshKey] = useState(0);
  const [injected, setInjected] = useState<{ text: string; n: number } | null>(null);
  const turnsSeen = useRef(0);

  const workspace = session?.workspace ?? "";
  const turnEnds = transcript.blocks.filter((b) => b.kind === "turn_end").length;

  useEffect(() => {
    if (turnEnds !== turnsSeen.current) {
      turnsSeen.current = turnEnds;
      setRefreshKey((k) => k + 1);
    }
  }, [turnEnds]);

  useEffect(() => {
    if (!workspace) return;
    api.files(workspace).then((d) => setFiles(d.files), () => setFiles([]));
  }, [workspace, refreshKey]);

  const slashCommands = useMemo(() => {
    const fromRuntime = session?.runtime?.slash_commands;
    return fromRuntime && fromRuntime.length ? fromRuntime : DEFAULT_COMMANDS;
  }, [session]);

  const setMode = useCallback(
    (mode: PermissionMode) => {
      handle.setMode(mode);
    },
    [handle],
  );

  // Esc: reject a waiting approval, else stop the turn. Shift+Tab: cycle modes.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !document.querySelector(".backdrop")) {
        const waiting = [...transcript.pending.values()][0];
        if (waiting) {
          e.preventDefault();
          handle.approve(waiting.request.id, "reject");
        } else if (transcript.running) {
          e.preventDefault();
          handle.cancel();
        }
      }
      if (e.key === "Tab" && e.shiftKey && session) {
        e.preventDefault();
        const next = MODE_ORDER[(MODE_ORDER.indexOf(session.permission_mode) + 1) % MODE_ORDER.length];
        setMode(next);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [transcript, handle, session, setMode]);

  const send = (text: string, attachments: Attachment[]) => handle.send(text, attachments);

  const context = transcript.contextUsage;
  const needsKey = health && !health.api_key_set && !health.scripted;
  const runtimeMissing = health?.runtime.error;

  const empty = (
    <div className="empty">
      <h2>What should we build?</h2>
      <div className="muted">
        Working in <span className="mono">{workspace || "…"}</span>
      </div>
      <div className="suggestions">
        {SUGGESTIONS.map((s) => (
          <button key={s} className="suggestion" onClick={() => setInjected({ text: s, n: Date.now() })}>
            {s}
          </button>
        ))}
      </div>
    </div>
  );

  return (
    <>
      <main className="card body">
        <header className="header">
          <div className="headerTitle">
            <h1 title={session?.title}>{session?.title ?? "Loading…"}</h1>
            <div className="path" title={workspace}>
              {workspace}
            </div>
          </div>
          {session?.runtime?.model ? (
            <button className="chip" onClick={onOpenSettings} title="Model (change in settings)">
              <Cpu size={13} /> {session.runtime.model}
            </button>
          ) : null}
          {session?.runtime?.director && session.runtime.director !== "off" ? (
            <span className="chip" title="Jev step director">
              <Compass size={13} /> Jev{session.runtime.director === "shadow" ? " (shadow)" : ""}
            </span>
          ) : null}
          {session?.runtime?.memory && session.runtime.memory !== "off" ? (
            <span className="chip" title="Dhee memory">
              <Brain size={13} /> Dhee
            </span>
          ) : null}
          {context != null ? (
            <span className="meter" title={`Context used: ${Math.round(context * 100)}%`}>
              <span className="track">
                <span className="fill" style={{ width: `${Math.min(100, Math.round(context * 100))}%`, display: "block" }} />
              </span>
              {Math.round(context * 100)}%
            </span>
          ) : null}
          {session ? <ModeMenu mode={session.permission_mode} onChange={setMode} /> : null}
          <button className={`iconButton${inspectorOpen ? " on" : ""}`} onClick={onToggleInspector} title="Toggle panel">
            <PanelRight size={17} />
          </button>
        </header>
        {runtimeMissing ? <div className="banner error">{runtimeMissing}</div> : null}
        {needsKey ? (
          <div className="banner">
            <span className="grow">Add an OpenRouter API key to start working.</span>
            <button className="button primary" onClick={onOpenSettings}>
              Open settings
            </button>
          </div>
        ) : null}
        {connection === "closed" ? (
          <div className="banner">
            <WifiOff size={15} /> <span className="grow">Connection lost — reconnecting…</span>
          </div>
        ) : null}
        {error ? (
          <div className="banner error">
            <span className="grow">{error}</span>
            <button className="iconButton" onClick={handle.clearError} aria-label="Dismiss">
              <X size={14} />
            </button>
          </div>
        ) : null}
        <Transcript state={transcript} workspace={workspace} onApprove={handle.approve} empty={empty} />
        <div className="composerWrap">
          <div className="column">
            <ComposerWithInjection
              key={sessionId}
              injected={injected}
              running={transcript.running}
              disabled={!session || connection !== "open"}
              placeholder={transcript.running ? "Working… (Esc to stop)" : "Ask root to change, fix, or explain something"}
              slashCommands={slashCommands}
              files={files}
              onSend={send}
              onStop={handle.cancel}
              draftKey={sessionId}
            />
            <div className="composerHint">root can make mistakes. Review changes before you ship them.</div>
          </div>
        </div>
      </main>
      {inspectorOpen && session ? (
        <Inspector
          tab={tab}
          onTab={setTab}
          onClose={onToggleInspector}
          workspace={workspace}
          sessionId={sessionId}
          todos={transcript.todos}
          refreshKey={refreshKey}
          files={files}
          onMention={(path) => setInjected({ text: `@${path} `, n: Date.now() })}
        />
      ) : null}
    </>
  );
}

/** The composer, remounted with text when a suggestion or mention is pushed into it. */
function ComposerWithInjection({ injected, ...props }: { injected: { text: string; n: number } | null } & React.ComponentProps<typeof Composer>) {
  useEffect(() => {
    if (!injected) return;
    try {
      const key = `draft:${props.draftKey}`;
      const current = localStorage.getItem(key) ?? "";
      localStorage.setItem(key, injected.text.startsWith("@") ? `${current}${current && !current.endsWith(" ") ? " " : ""}${injected.text}` : injected.text);
    } catch {
      /* storage unavailable */
    }
  }, [injected, props.draftKey]);
  return <Composer key={injected?.n ?? 0} {...props} />;
}
