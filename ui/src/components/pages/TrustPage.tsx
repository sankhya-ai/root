import { ShieldCheck } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { api } from "../../lib/api.ts";
import type { TrustEntry } from "../../lib/types.ts";
import { Page } from "./Page.tsx";

const TIER: Record<string, string> = { read: "Runs without asking — it only reads.", verify: "A project check: runs without asking in Accept edits and Plan mode.", needs_trust: "Asks you — it can change things." };

export function TrustPage() {
  const [entries, setEntries] = useState<TrustEntry[] | null>(null);
  const [promoteAfter, setPromoteAfter] = useState(3);
  const [command, setCommand] = useState("");
  const [verdict, setVerdict] = useState<{ tier: string; key: string; reasons: string[] } | null>(null);
  const load = useCallback(
    () =>
      api.trust().then((d) => {
        setEntries(d.entries);
        setPromoteAfter(d.promote_after);
      }),
    [],
  );
  useEffect(() => void load(), [load]);
  return (
    <Page
      eyebrow="Approvals"
      title="What root may do without asking"
      lede={
        <>
          Commands that only read run on their own. Anything that can change state asks you first. Approve the same kind of command {promoteAfter} times in a row and root
          stops asking for it; reject it once and it asks again. You can take trust back here at any time.
        </>
      }
    >
      <form
        className="panelTools"
        onSubmit={(e) => {
          e.preventDefault();
          if (command.trim()) api.classify(command).then(setVerdict);
        }}
      >
        <input className="input mono" placeholder="Check a command, e.g. npm run build && git push" value={command} onChange={(e) => setCommand(e.target.value)} />
        <button className="pill small" type="submit">
          Check
        </button>
      </form>
      {verdict ? (
        <div className="listCard">
          <div className="row">
            <span className={`tag${verdict.tier === "needs_trust" ? " accent" : ""}`}>{verdict.tier.replace("_", " ")}</span>
            <span className="grow small">
              {TIER[verdict.tier]} <span className="faint mono">{verdict.key.replace(/^run command:/, "")}</span>
              {verdict.reasons.length ? <span className="faint"> · {verdict.reasons.join(", ")}</span> : null}
            </span>
          </div>
        </div>
      ) : null}
      <div className="sectionLabel">Your decisions</div>
      {entries && !entries.length ? <p className="faint small">No decisions yet. They appear as you approve or reject commands.</p> : null}
      {entries?.map((entry) => (
        <div key={entry.key} className="listCard">
          <div className="row">
            {entry.promoted ? <ShieldCheck size={15} style={{ color: "var(--ok)" }} /> : <span className="tag">{entry.approvals}/{promoteAfter}</span>}
            <div className="grow">
              <h4 className="mono">{entry.key.replace(/^run command:/, "")}</h4>
              <p className="faint">
                {entry.promoted ? "Trusted — runs without asking" : `Approved ${entry.approvals} time${entry.approvals === 1 ? "" : "s"} in a row`}
                {entry.rejections ? ` · rejected ${entry.rejections} time${entry.rejections === 1 ? "" : "s"}` : ""}
              </p>
            </div>
            <button className="pill small" onClick={() => api.revokeTrust(entry.key).then(load)}>
              {entry.promoted ? "Take back" : "Forget"}
            </button>
          </div>
        </div>
      ))}
    </Page>
  );
}
