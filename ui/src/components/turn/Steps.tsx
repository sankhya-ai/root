// The detail under an activity line: each call, what it showed, what it returned.

import { Check, Loader2, X } from "lucide-react";

import { stepKind } from "../../lib/activity.ts";
import { describeTool, relativePath } from "../../lib/tools.ts";
import { outputText, parseArgs, type ToolBlock } from "../../lib/transcript.ts";
import type { DisplayBlock } from "../../lib/types.ts";
import { TextDiff } from "../DiffView.tsx";
import { StepIcon } from "./icons.tsx";

export function TodoItems({ items }: { items: { title: string; status: string }[] }) {
  return (
    <ul className="todoList">
      {items.map((item, index) => {
        const status = String(item.status).toLowerCase().replace(" ", "_");
        return (
          <li key={index} className={status}>
            <span className="box">{status === "done" ? <Check size={14} /> : status === "in_progress" ? <Loader2 size={14} className="spinner" /> : <span className="faint">○</span>}</span>
            <span>{item.title}</span>
          </li>
        );
      })}
    </ul>
  );
}

export function Displays({ blocks, workspace }: { blocks: DisplayBlock[]; workspace: string }) {
  return (
    <>
      {blocks.map((block, index) => {
        if (block.type === "diff") {
          return <TextDiff key={index} path={relativePath(String(block.path ?? ""), workspace)} oldText={String(block.old_text ?? "")} newText={String(block.new_text ?? "")} />;
        }
        if (block.type === "shell") {
          return (
            <pre key={index} className="output">
              <span className="faint">$ </span>
              {block.command}
            </pre>
          );
        }
        if (block.type === "todo" && Array.isArray(block.items)) return <TodoItems key={index} items={block.items} />;
        return null;
      })}
    </>
  );
}

function statusOf(step: ToolBlock, running: boolean) {
  if (step.approval?.status === "reject") return <span className="faint">Rejected</span>;
  if (!step.result) return running ? <Loader2 size={13} className="spinner" /> : <span className="faint">Interrupted</span>;
  const brief = step.result.display?.find((d) => d.type === "brief")?.text;
  if (step.result.is_error) return <span style={{ color: "var(--err)" }}><X size={13} /> {brief || "Failed"}</span>;
  return <span className="faint"><Check size={13} /> {brief || ""}</span>;
}

export function Step({ step, workspace, running, renderChildren }: { step: ToolBlock; workspace: string; running: boolean; renderChildren: (step: ToolBlock) => React.ReactNode }) {
  const view = describeTool(step.name, step.args, workspace);
  const result = step.result;
  const output = outputText(result);
  const displays = result?.display?.filter((d) => d.type === "diff" || d.type === "todo" || d.type === "shell") ?? [];
  const shows = displays.some((d) => d.type === "diff" || d.type === "todo");
  const args = parseArgs(step.args);
  const approval = step.approval;
  return (
    <div className="step">
      <div className="stepHead">
        <StepIcon kind={stepKind(step.name)} size={13} />
        <span>{view.verb}</span>
        {view.subject ? <code title={view.subject}>{view.subject}</code> : null}
        <span style={{ marginLeft: "auto" }}>{statusOf(step, running)}</span>
      </div>
      {step.name === "Task" && args?.prompt ? (
        <details className="thinking">
          <summary>Assignment</summary>
          <div className="thoughts">{String(args.prompt)}</div>
        </details>
      ) : null}
      {step.children?.blocks.length ? <div className="subagent">{renderChildren(step)}</div> : null}
      {displays.length ? <Displays blocks={displays} workspace={workspace} /> : null}
      {output && (!shows || result?.is_error) ? <pre className="output">{output}</pre> : null}
      {result?.message ? <p className={`stepMessage${result.is_error ? " err" : ""}`}>{result.message}</p> : null}
      {approval && approval.status !== "pending" ? (
        <p className="stepMessage">
          {approval.status === "reject" ? "Rejected" : approval.auto ? `Allowed automatically${approval.reason ? ` — ${approval.reason}` : ""}` : approval.status === "approve_for_session" ? "Allowed for this session" : "Approved by you"}
        </p>
      ) : null}
    </div>
  );
}
