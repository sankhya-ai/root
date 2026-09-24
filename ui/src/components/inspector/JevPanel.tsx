import { RefreshCw } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { api } from "../../lib/api.ts";

export function JevPanel({ sessionId, refreshKey }: { sessionId: string; refreshKey: number }) {
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
        <span className="sectionLabel grow">Recent decisions</span>
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
