// What root learned: lessons waiting for review, and the skills it now loads.

import { Brain, RotateCcw, Sparkles, Trash2 } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { api } from "../../lib/api.ts";
import type { LearnedSkill, LearningCandidate, Settings } from "../../lib/types.ts";
import { Markdown } from "../Markdown.tsx";
import { Page } from "./Page.tsx";

const MODES: { mode: Settings["learning_mode"]; label: string }[] = [
  { mode: "review", label: "Ask me" },
  { mode: "auto", label: "Learn automatically" },
  { mode: "off", label: "Off" },
];

function CandidateBody({ candidate }: { candidate: LearningCandidate }) {
  const body = candidate.body;
  if (candidate.kind === "memory") return <p>{body.content} <span className="tag">{body.scope}</span></p>;
  return (
    <>
      <p>
        <strong>When:</strong> {body.trigger}
      </p>
      <p>{body.lesson}</p>
      {body.steps?.length ? <ul className="small">{body.steps.map((s) => <li key={s}>{s}</li>)}</ul> : null}
      {body.verification?.length ? <p className="small faint">Verify: {body.verification.join("; ")}</p> : null}
      {body.pitfalls?.length ? <p className="small faint">Pitfalls: {body.pitfalls.join("; ")}</p> : null}
    </>
  );
}

export function LearningPage() {
  const [data, setData] = useState<Awaited<ReturnType<typeof api.learning>> | null>(null);
  const [skill, setSkill] = useState<{ name: string; text: string } | null>(null);
  const [error, setError] = useState("");
  const load = useCallback(() => api.learning().then(setData, (e) => setError(String(e.message))), []);
  useEffect(() => void load(), [load]);

  const decide = (candidate: LearningCandidate, verb: "promote" | "reject") =>
    (verb === "promote" ? api.promote(candidate.id) : api.reject(candidate.id)).then(load, (e) => setError(String(e.message)));
  const setMode = (mode: Settings["learning_mode"]) => api.saveSettings({ learning_mode: mode }).then(load);

  const pending = data?.candidates.filter((c) => c.status === "candidate") ?? [];
  const decided = data?.candidates.filter((c) => c.status !== "candidate").slice(0, 20) ?? [];

  return (
    <Page
      eyebrow="Self-improvement"
      title="What root has learned"
      lede={
        <>
          After a turn that did real work or went wrong, a reviewer reads what happened and proposes <strong>skills</strong> (ways of working root loads in every later
          session) and <strong>memories</strong> (facts kept in Dhee). Lessons tied to one task are filtered out. Nothing is kept until you say so, unless you choose to learn
          automatically.
        </>
      }
      actions={
        <div className="segmented">
          {MODES.map((m) => (
            <button key={m.mode} className={data?.mode === m.mode ? "active" : ""} onClick={() => setMode(m.mode)}>
              {m.label}
            </button>
          ))}
        </div>
      }
    >
      {error ? <div className="banner error">{error}</div> : null}
      <div className="sectionLabel">Waiting for you · {pending.length}</div>
      {data && !pending.length ? <p className="faint small">Nothing to review. Lessons appear here after substantial turns.</p> : null}
      {pending.map((candidate) => (
        <div key={candidate.id} className="listCard">
          <div className="row">
            {candidate.kind === "skill" ? <Sparkles size={15} className="faint" /> : <Brain size={15} className="faint" />}
            <div className="grow">
              <h4>
                {candidate.kind === "skill" ? `Skill: ${candidate.title}` : "Memory"} {candidate.updates_existing ? <span className="tag accent">improves existing</span> : null}
              </h4>
              <CandidateBody candidate={candidate} />
            </div>
          </div>
          <div className="actions">
            <button className="pill ink small" onClick={() => decide(candidate, "promote")}>
              Keep
            </button>
            <button className="pill small" onClick={() => decide(candidate, "reject")}>
              Reject
            </button>
          </div>
        </div>
      ))}

      <div className="sectionLabel">Skills root loads · {data?.skills.length ?? 0}</div>
      {data && !data.skills.length ? <p className="faint small">No learned skills yet.</p> : null}
      {data?.skills.map((s) => (
        <div key={s.name} className="listCard">
          <div className="row">
            <Sparkles size={15} className="faint" />
            <div className="grow">
              <h4 className="mono">{s.name}</h4>
              <p className="muted">{s.description}</p>
            </div>
          </div>
          <div className="actions">
            <button className="pill small" onClick={() => api.skill(s.name).then(setSkill)}>
              Read
            </button>
            {s.versions ? (
              <button className="pill small" onClick={() => api.rollbackSkill(s.name).then(load)}>
                <RotateCcw size={12} /> Previous version
              </button>
            ) : null}
            <button className="pill small danger" onClick={() => confirm(`Forget the skill “${s.name}”?`) && api.forgetSkill(s.name).then(load)}>
              <Trash2 size={12} /> Forget
            </button>
          </div>
          {skill?.name === s.name ? (
            <div className="markdown skillText">
              <Markdown text={skill.text.replace(/^---[\s\S]*?---\n/, "")} />
            </div>
          ) : null}
        </div>
      ))}

      {decided.length ? (
        <>
          <div className="sectionLabel">Decided</div>
          {decided.map((c) => (
            <div key={c.id} className="listCard">
              <div className="row">
                <span className={`tag${c.status === "promoted" ? " accent" : ""}`}>{c.status === "promoted" ? "kept" : "rejected"}</span>
                <span className="grow small">{c.kind === "skill" ? c.title : c.body.content}</span>
              </div>
            </div>
          ))}
        </>
      ) : null}
    </Page>
  );
}

export type { LearnedSkill };
