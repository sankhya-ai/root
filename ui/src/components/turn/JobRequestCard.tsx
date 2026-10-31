// A job the session proposed. The session starts nothing: the owner's Accept here (an owner-authenticated
// POST) is the only way the job runs, and it runs with exactly the fields the session stored. The card reads
// the request's live status from the API, so a replayed transcript event still shows what actually happened.

import { useEffect, useState } from "react";

import { Briefcase } from "lucide-react";

import { api } from "../../lib/api.ts";

export type JobProposal = { id: string; goal: string; role: string; version: number | null; reason: string; workspace: string };

export function JobRequestCard({ job }: { job: JobProposal }) {
  const [status, setStatus] = useState<string | null>(null);
  const [jobId, setJobId] = useState("");
  const [scope, setScope] = useState<string[]>([]);
  const [limits, setLimits] = useState("");
  const [busy, setBusy] = useState(false);

  const refresh = () => {
    api
      .jobRequests()
      .then(({ requests }) => {
        const found = requests.find((r) => r.id === job.id);
        setStatus(found ? found.status : "gone");
        setJobId(found?.job_id ?? "");
        setScope(found?.scope ?? []);
        const b = found?.budget ?? {};
        const parts = [`wall ${b.timeout_seconds ?? 900}s`];
        parts.push(b.max_steps ? `${b.max_steps} steps` : "no step cap");
        parts.push(b.max_tokens ? `${b.max_tokens} tokens` : "no token cap");
        parts.push(b.max_cost_usd ? `$${b.max_cost_usd} cost cap` : "no cost cap");
        setLimits(parts.join(" · "));
      })
      .catch(() => setStatus("unknown"));
  };
  useEffect(refresh, [job.id]);

  const decide = (action: "accept" | "dismiss") => {
    setBusy(true);
    (action === "accept" ? api.acceptJobRequest(job.id) : api.dismissJobRequest(job.id))
      .catch(() => {})
      .finally(() => {
        setBusy(false);
        refresh();
      });
  };

  return (
    <div className="approvalCard" role="alertdialog" aria-label="Job recommended">
      <header>
        <strong>
          <Briefcase size={15} style={{ color: "var(--accent)", verticalAlign: "-2px", marginRight: 6 }} />
          Start this job?
        </strong>
        <small>
          The session recommends a <code>{job.role}</code>
          {job.version ? ` v${job.version}` : ""} job. Nothing has started - accepting runs exactly what was proposed.
        </small>
      </header>
      <div className="approvalMeta">
        <span className="approvalChip outside" title="The goal, exactly as the session stored it">
          <code>{job.goal}</code>
        </span>
        {job.reason ? <span className="approvalChip" title="Why the session says a job, not this chat, should do it">{job.reason}</span> : null}
      </div>
      <div className="approvalMeta">
        <span className="approvalChip" title="The exact tools the job would run with, resolved when the session proposed it. The job gets no budget beyond the job defaults.">
          tools: {scope.length ? scope.join(", ") : "resolving…"}
        </span>
      </div>
      <div className="approvalMeta">
        <span className="approvalChip" title="Pinned when the session proposed the job; accepting applies exactly these, even if the defaults changed since.">
          limits: {limits || "job defaults"}
        </span>
      </div>
      {status === "pending" || status === null ? (
        <div className="approvalActions">
          <button className="pill ink" disabled={busy} onClick={() => decide("accept")}>
            Start job
          </button>
          <button className="pill danger" disabled={busy} onClick={() => decide("dismiss")}>
            Dismiss
          </button>
        </div>
      ) : (
        <div className="approvalMeta">
          <span className="approvalChip">
            {status === "accepted" ? `Started as job ${jobId}` : status === "dismissed" ? "Dismissed - nothing ran" : "No longer pending"}
          </span>
        </div>
      )}
    </div>
  );
}
