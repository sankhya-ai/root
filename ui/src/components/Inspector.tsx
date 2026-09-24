import { ChevronDown, ChevronRight, File, Folder, RefreshCw, Search, Trash2, X } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";

import { api } from "../lib/api.ts";
import { parseUnifiedDiff } from "../lib/diff.ts";
import type { TodoItem } from "../lib/transcript.ts";
import type { MemoryItem } from "../lib/types.ts";
import { DiffRows } from "./DiffView.tsx";
import { TodoItems } from "./ToolCard.tsx";

export type InspectorTab = "plan" | "changes" | "files" | "memory" | "jev";

const TABS: { id: InspectorTab; label: string }[] = [
  { id: "plan", label: "Plan" },
  { id: "changes", label: "Changes" },
  { id: "files", label: "Files" },
  { id: "memory", label: "Memory" },
  { id: "jev", label: "Jev" },
];

export function Inspector({
  tab,
  onTab,
  onClose,
  workspace,
  sessionId,
  todos,
  refreshKey,
  files,
  onMention,
}: {
  tab: InspectorTab;
  onTab: (tab: InspectorTab) => void;
  onClose: () => void;
  workspace: string;
  sessionId: string;
  todos: TodoItem[];
  refreshKey: number;
  files: string[];
  onMention: (path: string) => void;
}) {
  return (
    <aside className="card inspector">
      <div className="tabs">
        {TABS.map((t) => (
          <button key={t.id} className={`tab${tab === t.id ? " active" : ""}`} onClick={() => onTab(t.id)}>
            {t.label}
          </button>
        ))}
        <span style={{ flex: 1 }} />
        <button className="iconButton" onClick={onClose} title="Close panel">
          <X size={15} />
        </button>
      </div>
      <div className="tabBody scroll">
        {tab === "plan" ? <PlanTab todos={todos} /> : null}
        {tab === "changes" ? <ChangesTab workspace={workspace} refreshKey={refreshKey} /> : null}
        {tab === "files" ? <FilesTab workspace={workspace} files={files} onMention={onMention} /> : null}
        {tab === "memory" ? <MemoryTab workspace={workspace} refreshKey={refreshKey} /> : null}
        {tab === "jev" ? <JevTab sessionId={sessionId} refreshKey={refreshKey} /> : null}
      </div>
    </aside>
  );
}

function PlanTab({ todos }: { todos: TodoItem[] }) {
  if (!todos.length) {
    return <p className="muted small">The agent writes its plan here with SetTodoList when a task has several steps.</p>;
  }
  const done = todos.filter((t) => t.status.toLowerCase() === "done").length;
  return (
    <>
      <div className="panelTools">
        <span className="pixelLabel grow">Plan</span>
        <span className="faint small">
          {done}/{todos.length} done
        </span>
      </div>
      <TodoItems items={todos} />
    </>
  );
}

const STATUS_LABEL: Record<string, string> = { M: "modified", A: "added", D: "deleted", R: "renamed", "??": "new", AM: "added", MM: "modified" };

function ChangesTab({ workspace, refreshKey }: { workspace: string; refreshKey: number }) {
  const [data, setData] = useState<Awaited<ReturnType<typeof api.changes>> | null>(null);
  const [error, setError] = useState("");
  const [openFiles, setOpenFiles] = useState<Set<string>>(new Set());
  const load = useCallback(() => {
    api.changes(workspace).then(setData, (e) => setError(String(e.message)));
  }, [workspace]);
  useEffect(load, [load, refreshKey]);
  const diffs = useMemo(() => new Map(parseUnifiedDiff(data?.diff ?? "").map((d) => [d.path, d])), [data]);
  if (error) return <p className="small" style={{ color: "var(--err)" }}>{error}</p>;
  if (!data) return <p className="faint small">Loading…</p>;
  if (!data.git) return <p className="muted small">This workspace is not a git repository, so there is no diff to show. The transcript shows every edit the agent made.</p>;
  const toggle = (path: string) =>
    setOpenFiles((current) => {
      const next = new Set(current);
      if (next.has(path)) next.delete(path);
      else next.add(path);
      return next;
    });
  return (
    <>
      <div className="panelTools">
        <span className="pixelLabel grow">
          {data.branch} · {data.files.length} changed
        </span>
        <button className="iconButton" onClick={load} title="Refresh">
          <RefreshCw size={14} />
        </button>
      </div>
      {data.files.length === 0 ? <p className="muted small">Working tree is clean.</p> : null}
      {data.files.map((file) => {
        const diff = diffs.get(file.path);
        const open = openFiles.has(file.path);
        return (
          <div key={file.path} className="diff" style={{ marginBottom: 8 }}>
            <button className="changeRow" onClick={() => diff && toggle(file.path)} disabled={!diff}>
              {diff ? open ? <ChevronDown size={13} /> : <ChevronRight size={13} /> : <span style={{ width: 13 }} />}
              <span className="path">{file.path}</span>
              <span className="faint small">{STATUS_LABEL[file.status] ?? file.status}</span>
              {diff ? (
                <>
                  <span className="plus">+{diff.added}</span>
                  <span className="minus">−{diff.removed}</span>
                </>
              ) : (
                <span className="faint small">binary or empty</span>
              )}
            </button>
            {open && diff ? <DiffRows rows={diff.rows} /> : null}
          </div>
        );
      })}
    </>
  );
}

interface TreeNode {
  name: string;
  path: string;
  children: Map<string, TreeNode>;
  file: boolean;
}

function buildTree(files: string[]): TreeNode {
  const root: TreeNode = { name: "", path: "", children: new Map(), file: false };
  for (const file of files) {
    let node = root;
    const parts = file.split("/");
    parts.forEach((part, index) => {
      const path = parts.slice(0, index + 1).join("/");
      let child = node.children.get(part);
      if (!child) {
        child = { name: part, path, children: new Map(), file: index === parts.length - 1 };
        node.children.set(part, child);
      }
      node = child;
    });
  }
  return root;
}

function FilesTab({ workspace, files, onMention }: { workspace: string; files: string[]; onMention: (path: string) => void }) {
  const [filter, setFilter] = useState("");
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [viewing, setViewing] = useState<{ path: string; content: string; binary: boolean; truncated: boolean } | null>(null);
  const tree = useMemo(() => buildTree(files), [files]);
  const matches = useMemo(() => (filter ? files.filter((f) => f.toLowerCase().includes(filter.toLowerCase())).slice(0, 200) : []), [files, filter]);

  const open = (path: string) => {
    api.file(workspace, path).then(setViewing, () => setViewing(null));
  };

  const render = (node: TreeNode, depth: number): React.ReactNode[] =>
    [...node.children.values()]
      .sort((a, b) => Number(a.file) - Number(b.file) || a.name.localeCompare(b.name))
      .flatMap((child) => {
        const isOpen = expanded.has(child.path);
        const row = (
          <button
            key={child.path}
            className={`treeRow${viewing?.path === child.path ? " active" : ""}`}
            style={{ paddingLeft: 6 + depth * 14 }}
            onClick={() => {
              if (child.file) open(child.path);
              else
                setExpanded((current) => {
                  const next = new Set(current);
                  if (next.has(child.path)) next.delete(child.path);
                  else next.add(child.path);
                  return next;
                });
            }}
          >
            {child.file ? <File size={13} className="faint" /> : isOpen ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
            {!child.file ? <Folder size={13} className="faint" /> : null}
            {child.name}
          </button>
        );
        return child.file || !isOpen ? [row] : [row, ...render(child, depth + 1)];
      });

  return (
    <>
      <div className="panelTools">
        <Search size={14} className="faint" />
        <input className="input" placeholder="Filter files" value={filter} onChange={(e) => setFilter(e.target.value)} />
      </div>
      <div className="fileTree">
        {filter
          ? matches.map((path) => (
              <button key={path} className={`treeRow${viewing?.path === path ? " active" : ""}`} onClick={() => open(path)}>
                <File size={13} className="faint" /> {path}
              </button>
            ))
          : render(tree, 0)}
      </div>
      {viewing ? (
        <div className="fileView">
          <div className="panelTools">
            <span className="mono small grow" style={{ overflow: "hidden", textOverflow: "ellipsis" }}>
              {viewing.path}
            </span>
            <button className="button" onClick={() => onMention(viewing.path)} title="Mention this file in the composer">
              @ Mention
            </button>
          </div>
          {viewing.binary ? <p className="muted small">Binary file.</p> : <pre>{viewing.content}{viewing.truncated ? "\n… (truncated)" : ""}</pre>}
        </div>
      ) : null}
    </>
  );
}

function MemoryTab({ workspace, refreshKey }: { workspace: string; refreshKey: number }) {
  const [query, setQuery] = useState("");
  const [items, setItems] = useState<MemoryItem[] | null>(null);
  const [status, setStatus] = useState<{ active_mode: string; error: string; installed: boolean } | null>(null);
  const [error, setError] = useState("");
  const load = useCallback(
    (q?: string) => {
      api.memory(workspace, q).then(
        (data) => {
          setItems(data.items);
          setStatus(data.status);
          setError(data.error ?? "");
        },
        (e) => setError(String(e.message)),
      );
    },
    [workspace],
  );
  useEffect(() => load(), [load, refreshKey]);
  return (
    <>
      <p className="muted small" style={{ marginTop: 0 }}>
        Dhee keeps what the agent learns — project conventions, commands, decisions, your preferences — and brings the relevant parts back in later sessions.
        {status ? (
          <>
            {" "}
            Mode: <strong>{status.active_mode}</strong>.
          </>
        ) : null}
      </p>
      {status?.error ? <p className="small" style={{ color: "var(--warn)" }}>{status.error}</p> : null}
      <form
        className="panelTools"
        onSubmit={(e) => {
          e.preventDefault();
          load(query || undefined);
        }}
      >
        <input className="input" placeholder="Search memory" value={query} onChange={(e) => setQuery(e.target.value)} />
        <button className="iconButton" type="submit" title="Search">
          <Search size={14} />
        </button>
      </form>
      {error ? <p className="small" style={{ color: "var(--err)" }}>{error}</p> : null}
      {items && items.length === 0 ? <p className="faint small">Nothing remembered for this project yet.</p> : null}
      {items?.map((item) => (
        <div key={item.id} className="memoryRow">
          <span className="scopeTag">{item.scope}</span>
          <span className="text">{item.memory}</span>
          <button
            className="iconButton"
            style={{ minHeight: 24, minWidth: 24, padding: 0 }}
            title="Forget"
            onClick={() => api.forget(item.id).then(() => setItems((current) => current?.filter((i) => i.id !== item.id) ?? null))}
          >
            <Trash2 size={13} />
          </button>
        </div>
      ))}
    </>
  );
}

function JevTab({ sessionId, refreshKey }: { sessionId: string; refreshKey: number }) {
  const [decisions, setDecisions] = useState<any[] | null>(null);
  const load = useCallback(() => {
    api.director(sessionId).then((d) => setDecisions(d.decisions.slice().reverse()), () => setDecisions([]));
  }, [sessionId]);
  useEffect(load, [load, refreshKey]);
  return (
    <>
      <p className="muted small" style={{ marginTop: 0 }}>
        Before each step, <strong>Jev</strong> (<span className="mono">typesafe/jev-1.13</span>) reads the turn and decides whether the model should reply or which tool it should call. Confident
        calls are made by the harness; unsure ones leave the step to the model.
      </p>
      <div className="panelTools">
        <span className="pixelLabel grow">Recent decisions</span>
        <button className="iconButton" onClick={load} title="Refresh">
          <RefreshCw size={14} />
        </button>
      </div>
      {decisions && decisions.length === 0 ? <p className="faint small">No decisions recorded yet. Jev needs an OpenRouter key and director mode on or shadow.</p> : null}
      {decisions?.map((d, index) => (
        <div key={index} className="decision">
          <div>
            <span className="faint">step {d.step} · {d.phase} · {d.mode}</span>
          </div>
          <div className="directive">{d.directive}</div>
          {Array.isArray(d.ranked) ? <div className="ranked">{d.ranked.map((r: [string, number]) => `${r[0]} ${r[1]}`).join(" · ")}</div> : null}
          {d.ms != null ? <div className="faint small">{d.ms} ms</div> : null}
        </div>
      ))}
    </>
  );
}
