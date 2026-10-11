import {
  Archive,
  BookOpen,
  Brain,
  Check,
  CheckCircle2,
  History,
  RotateCcw,
  Search,
  Sparkles,
  Trash2,
  X,
} from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { api } from "../../lib/api.ts";
import type { LearningCandidate, Settings } from "../../lib/types.ts";
import { Markdown } from "../Markdown.tsx";

const MODES: { mode: Settings["learning_mode"]; label: string; desc: string }[] = [
  { mode: "review", label: "Ask Me First", desc: "You approve lessons before agents memorize them" },
  { mode: "auto", label: "Auto-Learn", desc: "Reviewer automatically retains verified skills" },
  { mode: "off", label: "Disabled", desc: "No new skills or facts are recorded" },
];

export function LearningPage() {
  const [data, setData] = useState<Awaited<ReturnType<typeof api.learning>> | null>(null);
  const [skill, setSkill] = useState<{ name: string; text: string } | null>(null);
  const [activeTab, setActiveTab] = useState<"skills" | "pending" | "history">("skills");
  const [searchQuery, setSearchQuery] = useState("");
  const [error, setError] = useState("");

  const load = useCallback(() => {
    return api
      .learning()
      .then(setData)
      .catch((e) => setError(String(e.message)));
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const decide = (candidate: LearningCandidate, verb: "promote" | "reject") =>
    (verb === "promote" ? api.promote(candidate.id) : api.reject(candidate.id)).then(load, (e) =>
      setError(String(e.message)),
    );

  const setMode = (mode: Settings["learning_mode"]) =>
    api.saveSettings({ learning_mode: mode }).then(load);

  const pending = data?.candidates.filter((c) => c.status === "candidate") ?? [];
  const decided = data?.candidates.filter((c) => c.status !== "candidate") ?? [];
  const skills = data?.skills ?? [];

  const filteredDecided = decided.filter((c) => {
    if (!searchQuery.trim()) return true;
    const q = searchQuery.toLowerCase();
    const text = c.kind === "skill" ? c.title : c.body.content || "";
    return text.toLowerCase().includes(q);
  });

  return (
    <div className="squadShell" style={{ padding: "20px 24px", overflowY: "auto" }}>
      {/* Header */}
      <div className="flowHeader">
        <div>
          <div className="flowEyebrow">
            <Sparkles size={13} style={{ color: "var(--accent)" }} />
            <span>KNOWLEDGE & CONTINUOUS LEARNING</span>
          </div>
          <h1 className="flowTitle">Agent Knowledge & Skills</h1>
          <p className="flowLede">
            Procedural skills, codebase patterns, and team conventions retained in Dhee to make your coding agents smarter with every task.
          </p>
        </div>

        {/* Mode Selector */}
        <div className="learningModeSelector">
          <span className="modeLabel">Learning Mode:</span>
          <div className="modePills">
            {MODES.map((m) => (
              <button
                key={m.mode}
                className={`modePillBtn ${data?.mode === m.mode ? "active" : ""}`}
                onClick={() => setMode(m.mode)}
                title={m.desc}
              >
                {m.label}
              </button>
            ))}
          </div>
        </div>
      </div>

      {error && <div className="modalError">{error}</div>}

      {/* KPI Cards */}
      <div className="flowStatsGrid">
        <div
          className={`flowStatCard clickable ${activeTab === "skills" ? "activeCard" : ""}`}
          onClick={() => setActiveTab("skills")}
        >
          <div className="statLabel">ACTIVE SKILLS</div>
          <div className="statValue" style={{ color: "var(--accent)" }}>
            {skills.length}
          </div>
          <div className="statSub">Procedural capabilities loaded across all sessions</div>
        </div>

        <div
          className={`flowStatCard clickable ${activeTab === "pending" ? "activeCard" : ""}`}
          onClick={() => setActiveTab("pending")}
        >
          <div className="statLabel">PENDING REVIEW</div>
          <div className="statValue" style={{ color: pending.length > 0 ? "var(--ok)" : "inherit" }}>
            {pending.length}
          </div>
          <div className="statSub">Lessons extracted from recent turns awaiting review</div>
        </div>

        <div
          className={`flowStatCard clickable ${activeTab === "history" ? "activeCard" : ""}`}
          onClick={() => setActiveTab("history")}
        >
          <div className="statLabel">DECISION AUDIT LOG</div>
          <div className="statValue">{decided.length}</div>
          <div className="statSub">Historical lessons promoted or dismissed</div>
        </div>

        <div className="flowStatCard">
          <div className="statLabel">MEMORY BACKEND</div>
          <div className="statValue" style={{ fontSize: "16px", paddingTop: "6px", color: "var(--ok)" }}>
            <Brain size={18} style={{ display: "inline", verticalAlign: "middle", marginRight: 6 }} />
            Dhee Engram Active
          </div>
          <div className="statSub">Cross-session continuity & AST context engine</div>
        </div>
      </div>

      {/* Navigation Tabs */}
      <div className="learningTabsRow">
        <button
          className={`learningTabBtn ${activeTab === "skills" ? "active" : ""}`}
          onClick={() => setActiveTab("skills")}
        >
          <Sparkles size={13} /> Loaded Skills ({skills.length})
        </button>
        <button
          className={`learningTabBtn ${activeTab === "pending" ? "active" : ""}`}
          onClick={() => setActiveTab("pending")}
        >
          <BookOpen size={13} /> Waiting for Review ({pending.length})
        </button>
        <button
          className={`learningTabBtn ${activeTab === "history" ? "active" : ""}`}
          onClick={() => setActiveTab("history")}
        >
          <History size={13} /> Decision History ({decided.length})
        </button>
      </div>

      {/* Tab 1: Loaded Skills */}
      {activeTab === "skills" && (
        <div className="tabContentSection">
          {skills.length > 0 ? (
            <div className="skillsCardGrid">
              {skills.map((s) => (
                <div key={s.name} className="skillDisplayCard">
                  <div className="skillCardHead">
                    <div className="skillTitleGroup">
                      <Sparkles size={13} style={{ color: "var(--accent)" }} />
                      <h4 className="skillName mono">{s.name}</h4>
                    </div>
                    {s.versions ? <span className="versionBadge">v{s.versions}</span> : null}
                  </div>
                  <p className="skillDesc">{s.description || "Procedural skill automatically applied by agents."}</p>

                  <div className="skillActions">
                    <button className="skillActionBtn" onClick={() => api.skill(s.name).then(setSkill)}>
                      Read Spec
                    </button>
                    {s.versions ? (
                      <button className="skillActionBtn" onClick={() => api.rollbackSkill(s.name).then(load)}>
                        <RotateCcw size={11} /> Rollback
                      </button>
                    ) : null}
                    <button
                      className="skillActionBtn danger"
                      onClick={() => confirm(`Forget skill "${s.name}"?`) && api.forgetSkill(s.name).then(load)}
                    >
                      <Trash2 size={11} /> Forget
                    </button>
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <div className="emptySkillsState">
              <Sparkles size={24} style={{ color: "var(--accent)", marginBottom: 8 }} />
              <h3>No Custom Skills Loaded</h3>
              <p>
                As your team works with coding agents, successful multi-step patterns and debugging procedures are automatically proposed here for retention.
              </p>
            </div>
          )}
        </div>
      )}

      {/* Tab 2: Waiting for Review */}
      {activeTab === "pending" && (
        <div className="tabContentSection">
          {pending.length > 0 ? (
            <div className="pendingStack">
              {pending.map((candidate) => (
                <div key={candidate.id} className="pendingCandidateCard">
                  <div className="candidateHead">
                    <div className="candidateBadge">
                      {candidate.kind === "skill" ? <Sparkles size={13} /> : <Brain size={13} />}
                      <span>{candidate.kind === "skill" ? `Proposed Skill: ${candidate.title}` : "Proposed Memory"}</span>
                    </div>
                    {candidate.updates_existing && <span className="refinesBadge">Improves Existing</span>}
                  </div>

                  <div className="candidateContent">
                    {candidate.kind === "memory" ? (
                      <p>{candidate.body.content}</p>
                    ) : (
                      <>
                        <div className="candidateTrigger">
                          <strong>Trigger:</strong> {candidate.body.trigger}
                        </div>
                        <div className="candidateLesson">{candidate.body.lesson}</div>
                      </>
                    )}
                  </div>

                  <div className="candidateFooter">
                    <button className="candidateKeepBtn" onClick={() => decide(candidate, "promote")}>
                      <Check size={12} /> Keep & Memorize
                    </button>
                    <button className="candidateRejectBtn" onClick={() => decide(candidate, "reject")}>
                      <X size={12} /> Dismiss
                    </button>
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <div className="emptySkillsState">
              <CheckCircle2 size={24} style={{ color: "var(--ok)", marginBottom: 8 }} />
              <h3>All Caught Up</h3>
              <p>Nothing waiting for review. Lessons appear here after substantial coding sessions.</p>
            </div>
          )}
        </div>
      )}

      {/* Tab 3: Decision History (Clean compact table) */}
      {activeTab === "history" && (
        <div className="tabContentSection">
          <div className="historySearchRow">
            <div className="searchBox">
              <Search size={13} />
              <input
                type="text"
                placeholder="Filter decisions..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
              />
            </div>
            <span className="historyCount">Showing {filteredDecided.length} items</span>
          </div>

          {filteredDecided.length > 0 ? (
            <div className="historyTableContainer">
              <table className="historyTable">
                <thead>
                  <tr>
                    <th>STATUS</th>
                    <th>TYPE</th>
                    <th>LESSON / SUMMARY</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredDecided.map((c) => (
                    <tr key={c.id}>
                      <td style={{ width: "110px" }}>
                        <span className={`statusTag ${c.status === "promoted" ? "kept" : "rejected"}`}>
                          {c.status === "promoted" ? "Kept" : "Dismissed"}
                        </span>
                      </td>
                      <td style={{ width: "90px" }}>
                        <span className="typeTag">{c.kind}</span>
                      </td>
                      <td className="lessonCell">
                        <span>{c.kind === "skill" ? c.title : c.body.content}</span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <div className="emptySkillsState">
              <Archive size={24} style={{ color: "var(--ink-faint)", marginBottom: 8 }} />
              <h3>No Matching Decision Logs</h3>
            </div>
          )}
        </div>
      )}

      {/* Skill Spec Modal */}
      {skill && (
        <div className="flowModalBackdrop" onClick={() => setSkill(null)}>
          <div className="flowModal" onClick={(e) => e.stopPropagation()} style={{ maxWidth: 640 }}>
            <div className="modalHead">
              <div className="modalTitle">
                <Sparkles size={15} style={{ color: "var(--accent)" }} />
                <span className="mono">{skill.name}</span>
              </div>
              <button className="closeBtn" onClick={() => setSkill(null)}>
                <X size={15} />
              </button>
            </div>
            <div className="modalBody" style={{ maxHeight: "65vh", overflowY: "auto" }}>
              <div className="markdown">
                <Markdown text={skill.text.replace(/^---[\s\S]*?---\n/, "")} />
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
