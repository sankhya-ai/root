// A session as Chotu's coding mode showed it: the owner's message in a box,
// then root's turn — its words, quiet trace lines for the tools it used, any
// approval it is waiting on — and a footer with the time and a Copy button.

import { Brain, ClipboardList, Paperclip, Sparkles } from "lucide-react";
import { useEffect, useLayoutEffect, useRef, useState, type ReactNode } from "react";

import { groupBlocks, type RenderItem } from "../lib/activity.ts";
import type { Block, ToolBlock, TranscriptState } from "../lib/transcript.ts";
import type { Flow } from "../lib/types.ts";
import { Markdown } from "./Markdown.tsx";
import { Activity } from "./turn/Activity.tsx";
import { ApprovalCard, type ApproveFn } from "./turn/ApprovalCard.tsx";
import { FlowCard } from "./turn/FlowCard.tsx";
import { Working } from "./turn/Working.tsx";

type UserBlock = Extract<Block, { kind: "user" }>;
type EndBlock = Extract<Block, { kind: "turn_end" }>;
interface Turn {
  key: string;
  user: UserBlock | null;
  blocks: Block[];
  end: EndBlock | null;
}

function turnsOf(blocks: Block[]): Turn[] {
  const turns: Turn[] = [];
  let current: Turn = { key: "start", user: null, blocks: [], end: null };
  for (const block of blocks) {
    if (block.kind === "user") {
      if (current.user || current.blocks.length) turns.push(current);
      current = { key: block.key, user: block, blocks: [], end: null };
    } else if (block.kind === "turn_end") {
      current.end = block;
    } else {
      current.blocks.push(block);
    }
  }
  if (current.user || current.blocks.length) turns.push(current);
  return turns;
}

function when(ts: number): string {
  const date = new Date(ts * 1000);
  const today = new Date().toDateString() === date.toDateString();
  const time = date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  return today ? time : `${date.toLocaleDateString([], { weekday: "long" })} ${time}`;
}

function tokens(n: number): string {
  return n >= 1_000_000 ? `${(n / 1_000_000).toFixed(1)}M` : n >= 1_000 ? `${(n / 1_000).toFixed(1)}k` : String(n);
}

function Footer({ end, text }: { end: EndBlock; text: string }) {
  const [copied, setCopied] = useState(false);
  const failed = end.status === "error" || end.status === "budget_exhausted";
  const status =
    end.status === "cancelled" ? "Stopped" : end.status === "max_steps_reached" ? "Stopped at the step limit — say “continue”" : failed ? "Failed" : "";
  return (
    <>
      {failed && end.error ? <div className="turnError">{end.error}</div> : null}
      <div className="messageActions">
        <span>{when(end.ts)}</span>
        {status ? <span className={failed ? "err" : ""}>{status}</span> : null}
        {end.duration != null ? <span>{end.duration < 60 ? `${end.duration.toFixed(1)}s` : `${Math.floor(end.duration / 60)}m ${Math.round(end.duration % 60)}s`}</span> : null}
        {end.files.length ? <span title={end.files.join("\n")}>{end.files.length} file{end.files.length === 1 ? "" : "s"} changed</span> : null}
        {end.usage.input || end.usage.output ? (
          <span>
            {tokens(end.usage.input)} in · {tokens(end.usage.output)} out{end.usage.cost ? ` · $${end.usage.cost.toFixed(4)}` : ""}
          </span>
        ) : null}
        {text ? (
          <button
            onClick={() => {
              void navigator.clipboard?.writeText(text).then(() => {
                setCopied(true);
                setTimeout(() => setCopied(false), 1500);
              });
            }}
          >
            {copied ? "Copied" : "Copy"}
          </button>
        ) : null}
      </div>
    </>
  );
}

export function Items({ items, workspace, running, onApprove, onFlow }: { items: RenderItem[]; workspace: string; running: boolean; onApprove: ApproveFn; onFlow?: (flow: Flow) => void }) {
  const children = (step: ToolBlock): ReactNode =>
    step.children ? <Items items={groupBlocks(step.children.blocks, { running: running && !step.result, workspace })} workspace={workspace} running={running && !step.result} onApprove={onApprove} /> : null;
  return (
    <>
      {items.map((item) => {
        switch (item.kind) {
          case "text":
            return (
              <div key={item.key} className="assistantText">
                <Markdown text={item.text} />
              </div>
            );
          case "think":
            return (
              <details key={item.key} className="thinking">
                <summary>Thinking</summary>
                <div className="thoughts">{item.text}</div>
              </details>
            );
          case "activity":
            return <Activity key={item.key} item={item} workspace={workspace} running={running} onApprove={onApprove} renderChildren={children} />;
          case "approval":
            return item.approval.status === "pending" ? <ApprovalCard key={item.key} approval={item.approval} workspace={workspace} onApprove={onApprove} /> : null;
          case "notice":
            return (
              <div key={item.key} className={`notice ${item.tone}`}>
                {item.text}
              </div>
            );
          case "flow":
            return <FlowCard key={item.key} flow={item.flow} onChange={onFlow} />;
          case "learned":
            return (
              <div key={item.key} className="learnedLine">
                <Sparkles size={13} />
                {item.ok ? (
                  <span>
                    {item.promoted ? `Learned and kept ${item.promoted} lesson${item.promoted === 1 ? "" : "s"}` : "Found something worth learning"}
                    {item.skills.length ? ` — skill ${item.skills.map((s) => `“${s}”`).join(", ")}` : ""}
                    {item.memories ? `${item.skills.length ? " and" : " —"} ${item.memories} memor${item.memories === 1 ? "y" : "ies"}` : ""}.{" "}
                    {item.mode === "review" ? <a href="#/learning">Review</a> : null}
                  </span>
                ) : (
                  <span>The learning review did not run: {item.error}</span>
                )}
              </div>
            );
          default:
            return null;
        }
      })}
    </>
  );
}

export function Transcript({
  state,
  workspace,
  onApprove,
  empty,
  hasMore,
  onLoadEarlier,
  planMode,
  onApprovePlan,
}: {
  state: TranscriptState;
  workspace: string;
  onApprove: ApproveFn;
  empty: ReactNode;
  hasMore: boolean;
  onLoadEarlier: () => void;
  planMode: boolean;
  onApprovePlan: () => void;
}) {
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

  const turns = turnsOf(state.blocks);
  const waiting = state.pending.size > 0;

  return (
    <div className="transcript scroll" ref={scroller}>
      <div className="column">
        {hasMore ? (
          <div className="notice">
            <button className="pill small" onClick={onLoadEarlier}>
              Load earlier messages
            </button>
          </div>
        ) : null}
        {turns.length === 0 ? empty : null}
        {turns.map((turn, index) => {
          const last = index === turns.length - 1;
          const running = last && state.running;
          const items = groupBlocks(turn.blocks, { running, workspace });
          const answer = turn.blocks.filter((b): b is Extract<Block, { kind: "text" }> => b.kind === "text").map((b) => b.text).join("\n\n");
          return (
            <section key={turn.key} className="turn">
              {turn.user ? (
                <div className="message user">
                  <div className="userBox">
                    <div className="messageLabel">You</div>
                    {turn.user.text}
                    {turn.user.attachments.length ? (
                      <div className="memoryNote">
                        <Paperclip size={12} /> {turn.user.attachments.map((a) => a.name).join(", ")}
                      </div>
                    ) : null}
                    {turn.user.memory.length ? (
                      <details className="memoryNote">
                        <summary>
                          <Brain size={12} /> Dhee attached {turn.user.memory.length} memor{turn.user.memory.length === 1 ? "y" : "ies"}
                        </summary>
                        <ul>
                          {turn.user.memory.map((m) => (
                            <li key={m.id || m.memory}>{m.memory}</li>
                          ))}
                        </ul>
                      </details>
                    ) : null}
                  </div>
                </div>
              ) : null}
              {items.length || running || turn.end ? (
                <div className="message assistant">
                  {turn.user ? <div className="messageLabel">root</div> : null}
                  <Items items={items} workspace={workspace} running={running} onApprove={onApprove} />
                  {running && !waiting && turn.user ? <Working since={turn.user.ts * 1000} label={state.compacting ? "Compacting context…" : "Working…"} /> : null}
                  {turn.end ? <Footer end={turn.end} text={answer} /> : null}
                </div>
              ) : null}
              {last && planMode && !state.running && turn.end?.status === "finished" ? (
                <div className="planBar">
                  <ClipboardList size={16} />
                  <span className="grow">Plan mode: nothing has been changed. Approve the plan to let root implement it.</span>
                  <button className="pill ink" onClick={onApprovePlan}>
                    Approve plan
                  </button>
                </div>
              ) : null}
            </section>
          );
        })}
      </div>
    </div>
  );
}
