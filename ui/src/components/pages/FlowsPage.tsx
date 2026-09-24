import { useCallback, useEffect, useState } from "react";

import { api } from "../../lib/api.ts";
import type { Flow } from "../../lib/types.ts";
import { FlowCard } from "../turn/FlowCard.tsx";
import { Page } from "./Page.tsx";

export function FlowsPage() {
  const [flows, setFlows] = useState<Flow[] | null>(null);
  const load = useCallback(() => api.flows().then((d) => setFlows(d.flows), () => setFlows([])), []);
  useEffect(() => {
    void load();
    const timer = setInterval(load, 5000);
    return () => clearInterval(timer);
  }, [load]);
  return (
    <Page
      eyebrow="Coding flows"
      title="Changes built in isolation"
      lede={
        <>
          For a substantial change, root builds candidates in separate Git worktrees, each with its own agent, runs your checks on every one, repairs failures from the
          exact test output, and picks the best verified patch. Nothing reaches your checkout until you review the patch and apply it — and an apply can be rolled back
          exactly. Ask for one in any session: “use a coding flow to …”.
        </>
      }
    >
      {flows && !flows.length ? <p className="faint small">No coding flows yet.</p> : null}
      {flows?.map((flow) => (
        <FlowCard key={flow.id} flow={flow} onChange={() => void load()} />
      ))}
    </Page>
  );
}
