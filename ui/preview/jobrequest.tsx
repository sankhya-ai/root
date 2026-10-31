import "../src/styles/app.css";
import { createRoot } from "react-dom/client";
import { createTranscript, applyEvent } from "../src/lib/transcript.ts";
import { groupBlocks } from "../src/lib/activity.ts";
import { Items } from "../src/components/Transcript.tsx";

// Fixture: the API answers "pending" so the card shows its decision state (vite preview has no backend).
const originalFetch = window.fetch.bind(window);
window.fetch = (input: RequestInfo | URL, init?: RequestInit) => {
  const url = String(input);
  if (url.includes("/api/auth/bootstrap")) {
    return Promise.resolve(new Response("{}", { status: 200, headers: { "Content-Type": "application/json" } }));
  }
  if (url.includes("/api/job-requests") && !init?.method) {
    return Promise.resolve(new Response(JSON.stringify({ requests: [{
      id: "f3a91c0d2e4b", goal: "Summarise the repo and file a digest", role: "explorer", role_version: 0,
      workspace: "/tmp/demo", reason: "read-only sweep while you sleep", requested_by: "sess-1", status: "pending", created_at: 1,
      scope: ["ReadFile", "Glob", "Grep"],
      budget: { max_steps: 0, timeout_seconds: 900, max_tokens: 0, max_cost_usd: 0 },
    }] }), { status: 200, headers: { "Content-Type": "application/json" } }));
  }
  return originalFetch(input, init);
};

// The real pipeline: the persisted session event -> transcript state -> rendered items.
const state = createTranscript();
applyEvent(state, {
  type: "JobRecommended",
  payload: { id: "f3a91c0d2e4b", goal: "Summarise the repo and file a digest", role: "explorer", version: null, reason: "read-only sweep while you sleep", workspace: "/tmp/demo" },
} as never);
const items = groupBlocks(state.blocks, { running: false, workspace: "/tmp/demo" });

createRoot(document.getElementById("root")!).render(
  <div style={{ maxWidth: 720, margin: "24px auto", padding: "0 16px" }}>
    <Items items={items} workspace="/tmp/demo" running={false} onApprove={() => {}} />
  </div>,
);
