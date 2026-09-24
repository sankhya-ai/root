import { AlertTriangle, Brain, CheckCircle2, Clock, FileDiff, Paperclip, StopCircle } from "lucide-react";
import { useEffect, useLayoutEffect, useRef, type ReactNode } from "react";

import type { Block, TranscriptState } from "../lib/transcript.ts";
import { ApprovalPanel, ToolCard, type ApproveFn } from "./ToolCard.tsx";
import { Markdown } from "./Markdown.tsx";

function formatTokens(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}k`;
  return String(n);
}

function TurnEnd({ block }: { block: Extract<Block, { kind: "turn_end" }> }) {
  const failed = block.status === "error" || block.status === "budget_exhausted" || block.status === "flow_incomplete";
  const parts: ReactNode[] = [];
  if (block.status === "cancelled") parts.push(<span key="s"><StopCircle size={13} /> Stopped</span>);
  else if (block.status === "max_steps_reached") parts.push(<span key="s"><AlertTriangle size={13} /> Stopped at the step limit — say “continue” to keep going</span>);
  else if (failed) parts.push(<span key="s"><AlertTriangle size={13} /> {block.status === "error" ? "Failed" : block.status.replace(/_/g, " ")}</span>);
  else parts.push(<span key="s"><CheckCircle2 size={13} /> Done</span>);
  if (block.duration != null) parts.push(<span key="d"><Clock size={13} /> {block.duration < 60 ? `${block.duration.toFixed(1)}s` : `${Math.floor(block.duration / 60)}m ${Math.round(block.duration % 60)}s`}</span>);
  if (block.files.length) parts.push(<span key="f" title={block.files.join("\n")}><FileDiff size={13} /> {block.files.length} file{block.files.length === 1 ? "" : "s"} changed</span>);
  if (block.usage.input || block.usage.output) {
    parts.push(
      <span key="u">
        {formatTokens(block.usage.input)} in · {formatTokens(block.usage.output)} out{block.usage.cost ? ` · $${block.usage.cost.toFixed(4)}` : ""}
      </span>,
    );
  }
  return (
    <>
      {failed && block.error ? <div className="turnError">{block.error}</div> : null}
    <div className={`turnEnd${failed ? " err" : ""}`}>
      {parts.map((part, index) => (
        <span key={index} style={{ display: "inline-flex", alignItems: "center", gap: 10 }}>
          {index > 0 ? <span className="sep">·</span> : null}
          {part}
        </span>
      ))}
    </div>
    </>
  );
}

export function Blocks({ state, workspace, onApprove, running, nested = false }: { state: TranscriptState; workspace: string; onApprove: ApproveFn; running: boolean; nested?: boolean }) {
  return (
    <>
      {state.blocks.map((block) => {
        switch (block.kind) {
          case "user":
            return (
              <div key={block.key} className="userMessage">
                <div style={{ maxWidth: "82%" }}>
                  <div className="userBubble" style={{ maxWidth: "100%" }}>
                    {block.text}
                    {block.attachments.length ? (
                      <div className="faint small" style={{ marginTop: 6 }}>
                        <Paperclip size={12} /> {block.attachments.map((a) => a.name).join(", ")}
                      </div>
                    ) : null}
                  </div>
                  {block.memory.length ? (
                    <div className="memoryChips" title="Dhee attached these memories to the request">
                      <Brain size={13} className="faint" />
                      {block.memory.map((item) => (
                        <span key={item.id || item.memory} className="memoryChip" title={item.memory}>
                          {item.memory}
                        </span>
                      ))}
                    </div>
                  ) : null}
                </div>
              </div>
            );
          case "text":
            return (
              <div key={block.key} className="assistantText">
                <Markdown text={block.text} />
              </div>
            );
          case "think":
            return (
              <details key={block.key} className="thinking">
                <summary>Thinking</summary>
                <div className="body">{block.text}</div>
              </details>
            );
          case "tool":
            return <ToolCard key={block.key} block={block} workspace={workspace} onApprove={onApprove} running={running} />;
          case "approval":
            return (
              <div key={block.key} className="tool pending">
                <ApprovalPanel approval={block.approval} onApprove={onApprove} />
              </div>
            );
          case "notice":
            return (
              <div key={block.key} className={`notice ${block.tone}`}>
                {block.text}
              </div>
            );
          case "turn_end":
            return nested ? null : <TurnEnd key={block.key} block={block} />;
          default:
            return null;
        }
      })}
    </>
  );
}

export function Transcript({ state, workspace, onApprove, empty }: { state: TranscriptState; workspace: string; onApprove: ApproveFn; empty: ReactNode }) {
  const scroller = useRef<HTMLDivElement>(null);
  const stick = useRef(true);

  useEffect(() => {
    const el = scroller.current;
    if (!el) return;
    const onScroll = () => {
      stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
    };
    el.addEventListener("scroll", onScroll, { passive: true });
    return () => el.removeEventListener("scroll", onScroll);
  }, []);

  useLayoutEffect(() => {
    const el = scroller.current;
    if (el && stick.current) el.scrollTop = el.scrollHeight;
  });

  const lastKind = state.blocks[state.blocks.length - 1]?.kind;
  const showWorking = state.running && state.pending.size === 0 && lastKind !== "text";

  return (
    <div className="transcript scroll" ref={scroller}>
      <div className="column">
        {state.blocks.length === 0 ? empty : <Blocks state={state} workspace={workspace} onApprove={onApprove} running={state.running} />}
        {showWorking ? (
          <div className="working">
            <span className="spark" /> {state.compacting ? "Compacting context…" : "Working…"}
          </div>
        ) : null}
      </div>
    </div>
  );
}
