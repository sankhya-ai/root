import { Brain, Compass, Cpu, PanelRight, Shield, WifiOff, X } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { api } from "../lib/api.ts";
import { useSession } from "../lib/useSession.ts";
import type { Attachment, Health, PermissionMode, Session, SlashCommand } from "../lib/types.ts";
import { Composer } from "./Composer.tsx";
import { Inspector, type InspectorTab } from "./inspector/Inspector.tsx";
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
  initialPrompt,
  onInitialSent,
  inspectorOpen,
  onToggleInspector,
  onSessionChange,
  onOpenSettings,
}: {
  sessionId: string;
  health: Health | null;
  initialPrompt?: string;
  onInitialSent?: () => void;
  inspectorOpen: boolean;
  onToggleInspector: () => void;
  onSessionChange: (session: Session) => void;
  onOpenSettings: () => void;
}) {
  const handle = useSession(sessionId, onSessionChange);
  const { transcript, session, connection, error } = handle;
  const [tab, setTab] = useState<InspectorTab>("changes");
  const [files, setFiles] = useState<string[]>([]);
  const [refreshKey, setRefreshKey] = useState(0);
  const [injected, setInjected] = useState<{ text: string; n: number } | null>(null);
  const turnsSeen = useRef(0);
  const sentInitial = useRef(false);

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

  useEffect(() => {
    if (initialPrompt && connection === "open" && session && !sentInitial.current) {
      sentInitial.current = true;
      handle.send(initialPrompt, []);
      onInitialSent?.();
    }
  }, [initialPrompt, connection, session, handle, onInitialSent]);

  const slashCommands = useMemo(() => {
    const fromRuntime = session?.runtime?.slash_commands;
    return fromRuntime && fromRuntime.length ? fromRuntime : DEFAULT_COMMANDS;
  }, [session]);

  const setMode = useCallback((mode: PermissionMode) => handle.setMode(mode), [handle]);

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
        setMode(MODE_ORDER[(MODE_ORDER.indexOf(session.permission_mode) + 1) % MODE_ORDER.length]);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [transcript, handle, session, setMode]);

  const send = (text: string, attachments: Attachment[]) => handle.send(text, attachments);
  const approvePlan = () => {
    setMode("accept_edits");
    handle.send("The plan is approved. Implement it now, then verify the result.", []);
  };

  const context = transcript.contextUsage;
  const needsKey = health && !health.api_key_set && !health.scripted;
  const runtime = session?.runtime;

  const empty = (
    <div className="home" style={{ minHeight: 360 }}>
      <div className="eyebrow">{workspace.split("/").filter(Boolean).pop() ?? "workspace"}</div>
      <h2 className="greeting">What should we build?</h2>
      <div className="homeActions">
        {SUGGESTIONS.map((s) => (
          <button key={s} className="pill" onClick={() => setInjected({ text: s, n: Date.now() })}>
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
          {runtime?.director && runtime.director !== "off" ? (
            <span className="chip quiet" title="Jev decides each step: reply, or which tool to call">
              <Compass size={13} /> Jev{runtime.director === "shadow" ? " (shadow)" : ""}
            </span>
          ) : null}
          {runtime?.memory && runtime.memory !== "off" ? (
            <span className="chip quiet" title="Dhee long-term memory">
              <Brain size={13} /> Dhee
            </span>
          ) : null}
          {runtime?.sandbox && runtime.sandbox !== "none" ? (
            <span className="chip quiet" title="Commands run in a sandbox">
              <Shield size={13} /> Sandboxed
            </span>
          ) : null}
          {context != null ? (
            <span className="meter" title={`Context used: ${Math.round(context * 100)}%`}>
              <span className="track">
                <span className="fill" style={{ width: `${Math.min(100, Math.round(context * 100))}%` }} />
              </span>
              {Math.round(context * 100)}%
            </span>
          ) : null}
          <button className={`iconButton${inspectorOpen ? " on" : ""}`} onClick={onToggleInspector} title="Changes, files, plan, memory, processes">
            <PanelRight size={17} />
          </button>
        </header>
        {health?.runtime.error ? <div className="banner error">{health.runtime.error}</div> : null}
        {needsKey ? (
          <div className="banner">
            <span className="grow">Add an OpenRouter API key to start working.</span>
            <button className="pill ink small" onClick={onOpenSettings}>
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
        <Transcript
          state={transcript}
          workspace={workspace}
          onApprove={handle.approve}
          empty={empty}
          hasMore={handle.hasMore}
          onLoadEarlier={() => void handle.loadEarlier()}
          planMode={session?.permission_mode === "plan"}
          onApprovePlan={approvePlan}
        />
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
              chips={
                <>
                  {session ? <ModeMenu mode={session.permission_mode} onChange={setMode} /> : null}
                  {runtime?.model ? (
                    <button className="chip quiet" onClick={onOpenSettings} title="Model (change in settings)">
                      <Cpu size={13} /> {runtime.model}
                    </button>
                  ) : null}
                </>
              }
            />
          </div>
        </div>
      </main>
      {inspectorOpen && session ? (
        <Inspector
          tab={tab}
          onTab={setTab}
          onClose={onToggleInspector}
          workspace={workspace}
          session={session}
          todos={transcript.todos}
          processes={[...transcript.processes.values()]}
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
