import {
  Bot,
  Brain,
  Check,
  ChevronDown,
  ChevronRight,
  FilePen,
  FilePlus2,
  FileText,
  FolderSearch,
  Globe,
  Image,
  ListTodo,
  Loader2,
  Plug,
  Search,
  ShieldAlert,
  SquareTerminal,
  X,
} from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";

import { describeTool, relativePath, type ToolIcon } from "../lib/tools.ts";
import { outputText, parseArgs, type ApprovalState, type ToolBlock } from "../lib/transcript.ts";
import type { DisplayBlock } from "../lib/types.ts";
import { TextDiff } from "./DiffView.tsx";
import { Blocks } from "./Transcript.tsx";

const ICONS: Record<ToolIcon, ReactNode> = {
  terminal: <SquareTerminal size={16} />,
  file: <FileText size={16} />,
  edit: <FilePen size={16} />,
  new: <FilePlus2 size={16} />,
  search: <Search size={16} />,
  folder: <FolderSearch size={16} />,
  globe: <Globe size={16} />,
  todo: <ListTodo size={16} />,
  agent: <Bot size={16} />,
  memory: <Brain size={16} />,
  image: <Image size={16} />,
  plug: <Plug size={16} />,
};

export type ApproveFn = (requestId: string, response: "approve" | "approve_for_session" | "reject") => void;

function Displays({ blocks, workspace }: { blocks: DisplayBlock[]; workspace: string }) {
  return (
    <>
      {blocks.map((block, index) => {
        if (block.type === "diff") {
          return <TextDiff key={index} path={relativePath(String(block.path ?? ""), workspace)} oldText={String(block.old_text ?? "")} newText={String(block.new_text ?? "")} />;
        }
        if (block.type === "shell") {
          return (
            <pre key={index} className="toolOutput">
              <span className="faint">$ </span>
              {block.command}
            </pre>
          );
        }
        if (block.type === "todo" && Array.isArray(block.items)) {
          return <TodoItems key={index} items={block.items} />;
        }
        return null;
      })}
    </>
  );
}

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

export function ApprovalPanel({ approval, onApprove, showDisplay }: { approval: ApprovalState; onApprove: ApproveFn; showDisplay?: ReactNode }) {
  const { request, status, auto } = approval;
  if (status !== "pending") {
    const label = status === "reject" ? "Rejected" : status === "approve_for_session" ? "Approved for this session" : auto ? "Auto-approved" : "Approved";
    return <div className="resolved">{label} · {request.action}</div>;
  }
  return (
    <div className="approval">
      <div className="question">
        <ShieldAlert size={16} color="var(--tura-accent)" />
        <span>
          <strong>Allow {request.sender}</strong> to {request.action}?
        </span>
      </div>
      {showDisplay}
      <div className="approvalActions">
        <button className="button primary" onClick={() => onApprove(request.id, "approve")} autoFocus>
          Allow <span className="kbd">↵</span>
        </button>
        <button className="button" onClick={() => onApprove(request.id, "approve_for_session")}>
          Allow “{request.action}” for this session
        </button>
        <button className="button danger" onClick={() => onApprove(request.id, "reject")}>
          Reject <span className="kbd">esc</span>
        </button>
      </div>
    </div>
  );
}

export function ToolCard({ block, workspace, onApprove, running }: { block: ToolBlock; workspace: string; onApprove: ApproveFn; running: boolean }) {
  const view = describeTool(block.name, block.args, workspace);
  const pending = block.approval?.status === "pending";
  const result = block.result;
  const isError = Boolean(result?.is_error);
  const hasDisplays = Boolean(result?.display?.some((d) => d.type === "diff" || d.type === "todo"));
  const [open, setOpen] = useState<boolean>(pending || isError);
  useEffect(() => {
    if (pending || isError) setOpen(true);
  }, [pending, isError]);

  const done = Boolean(result);
  const rejected = block.approval?.status === "reject";
  let status: ReactNode;
  if (pending) status = <span className="toolStatus wait">Waiting for you</span>;
  else if (rejected) status = <span className="toolStatus err"><X size={14} /> Rejected</span>;
  else if (!done) status = running ? <span className="toolStatus"><Loader2 size={14} className="spinner" /></span> : <span className="toolStatus">Interrupted</span>;
  else if (isError) status = <span className="toolStatus err"><X size={14} /> {result?.display?.find((d) => d.type === "brief")?.text || "Failed"}</span>;
  else status = <span className="toolStatus ok"><Check size={14} /> {result?.display?.find((d) => d.type === "brief")?.text || ""}</span>;

  const output = outputText(result);
  const args = parseArgs(block.args);
  const approvalDisplay = block.approval?.request.display?.length ? <Displays blocks={block.approval.request.display} workspace={workspace} /> : null;

  return (
    <div className={`tool${pending ? " pending" : ""}${isError ? " error" : ""}`}>
      <button className="toolHead" onClick={() => setOpen((v) => !v)} aria-expanded={open}>
        <span className="toolIcon">{ICONS[view.icon]}</span>
        <span className="toolVerb">{view.verb}</span>
        <span className="toolSubject" title={view.subject}>{view.subject}</span>
        {status}
        {open ? <ChevronDown size={14} className="faint" /> : <ChevronRight size={14} className="faint" />}
      </button>
      {open && !pending ? (
        <div className="toolBody">
          {block.name === "Task" && args?.prompt ? (
            <details>
              <summary className="pixelLabel">Assignment</summary>
              <pre className="toolOutput">{String(args.prompt)}</pre>
            </details>
          ) : null}
          {block.children && block.children.blocks.length ? (
            <div className="subagent">
              <Blocks state={block.children} workspace={workspace} onApprove={onApprove} running={running && !done} nested />
            </div>
          ) : null}
          {result?.display?.length ? <Displays blocks={result.display} workspace={workspace} /> : null}
          {!hasDisplays && block.name !== "Task" && !result && args && Object.keys(args).length ? (
            <pre className="toolOutput">{JSON.stringify(args, null, 2)}</pre>
          ) : null}
          {output && (!hasDisplays || isError) ? <pre className="toolOutput">{output}</pre> : null}
          {result?.message ? <p className={`toolMessage${isError ? " err" : ""}`}>{result.message}</p> : null}
        </div>
      ) : null}
      {block.approval ? <ApprovalPanel approval={block.approval} onApprove={onApprove} showDisplay={pending ? approvalDisplay : undefined} /> : null}
    </div>
  );
}
