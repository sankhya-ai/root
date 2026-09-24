import { RefreshCw, Square } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { api } from "../../lib/api.ts";
import type { ProcessInfo } from "../../lib/types.ts";

/** Background processes the agent started in this session: dev servers, watchers, long builds. */
export function ProcessesPanel({ sessionId, live }: { sessionId: string; live: ProcessInfo[] }) {
  const [items, setItems] = useState<ProcessInfo[] | null>(null);
  const [log, setLog] = useState<{ id: string; lines: string[] } | null>(null);
  const load = useCallback(() => {
    api.processes(sessionId).then((d) => setItems(d.processes), () => setItems([]));
  }, [sessionId]);
  // Live ProcessUpdated events arrive through the transcript; refetch on each.
  const signature = live.map((p) => `${p.id}:${p.status}`).join(",");
  useEffect(load, [load, signature]);
  const showLog = (id: string) => api.processLog(sessionId, id).then((d) => setLog({ id, lines: d.lines }));
  return (
    <>
      <p className="help">
        Processes root started with its <span className="mono">process</span> tool keep running between turns. They stop when you stop them, or when the session closes.
      </p>
      <div className="panelTools">
        <span className="sectionLabel grow">Processes</span>
        <button className="iconButton" onClick={load} title="Refresh">
          <RefreshCw size={14} />
        </button>
      </div>
      {items && items.length === 0 ? <p className="faint small">No background processes in this session.</p> : null}
      {items?.map((p) => (
        <div key={p.id} className="listCard">
          <div className="row">
            <span className={`tag${p.status === "running" ? " accent" : ""}`}>{p.status}</span>
            <div className="grow">
              <h4 className="mono">{p.label}</h4>
              <p className="faint">
                {p.id} · pid {p.pid ?? "–"} · {p.runtime_seconds}s{p.exit_code != null ? ` · exit ${p.exit_code}` : ""}
              </p>
            </div>
          </div>
          <div className="actions">
            <button className="pill small" onClick={() => showLog(p.id)}>
              Log
            </button>
            {p.status === "running" ? (
              <button className="pill small danger" onClick={() => api.killProcess(sessionId, p.id).then(load)}>
                <Square size={11} fill="currentColor" /> Stop
              </button>
            ) : null}
          </div>
          {log?.id === p.id ? <pre className="output">{log.lines.join("\n") || "(no output)"}</pre> : null}
        </div>
      ))}
    </>
  );
}
