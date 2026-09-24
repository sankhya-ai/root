import { Search, Trash2 } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { api } from "../../lib/api.ts";
import type { MemoryItem } from "../../lib/types.ts";

export function MemoryPanel({ workspace, refreshKey }: { workspace: string; refreshKey: number }) {
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
      {status?.error ? <p className="small" style={{ color: "var(--accent)" }}>{status.error}</p> : null}
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
        <div key={item.id} className="listCard">
          <div className="row">
            <span className="tag">{item.scope}</span>
            <span className="grow small">{item.memory}</span>
            <button
              className="iconButton"
              title="Forget"
              onClick={() => api.forget(item.id, workspace).then(() => setItems((current) => current?.filter((i) => i.id !== item.id) ?? null))}
            >
              <Trash2 size={13} />
            </button>
          </div>
        </div>
      ))}
    </>
  );
}

