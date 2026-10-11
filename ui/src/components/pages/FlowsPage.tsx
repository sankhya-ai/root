import {
  ArrowRight,
  GitBranch,
  GitFork,
  Layers,
  Play,
  Plus,
  RefreshCw,
  ShieldCheck,
  Terminal,
  X,
} from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { api } from "../../lib/api.ts";
import type { Flow } from "../../lib/types.ts";
import { FlowCard } from "../turn/FlowCard.tsx";

const TEMPLATES = [
  {
    title: "Contract Alignment & Validation",
    prompt: "Verify cross-agent API schema consistency between Pydantic models and TypeScript interfaces.",
    cmd: "pytest -q tests/test_auth.py",
  },
  {
    title: "Optimistic Concurrency Lock Protection",
    prompt: "Add TTL-backed file lease timeouts to prevent edit conflicts across collaborating agents.",
    cmd: "pytest -q tests/test_squads.py",
  },
  {
    title: "Fast Test Suite Runner & AST Lint",
    prompt: "Run full test harness and auto-fix formatting or import issues in a clean worktree.",
    cmd: "git diff --check",
  },
];

export function FlowsPage() {
  const [flows, setFlows] = useState<Flow[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [showModal, setShowModal] = useState(false);
  const [taskPrompt, setTaskPrompt] = useState("");
  const [verifyCmd, setVerifyCmd] = useState("git diff --check");
  const [candidateCount, setCandidateCount] = useState(2);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  const load = useCallback(() => {
    setLoading(true);
    return api
      .flows()
      .then((d) => setFlows(d.flows))
      .catch(() => setFlows([]))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    void load();
    const timer = setInterval(load, 5000);
    return () => clearInterval(timer);
  }, [load]);

  const handleLaunch = async (e?: React.FormEvent) => {
    if (e) e.preventDefault();
    if (!taskPrompt.trim()) return;
    setSubmitting(true);
    setError("");
    try {
      await api.createFlow({
        task: taskPrompt.trim(),
        verification_commands: [verifyCmd.trim() || "git diff --check"],
        candidate_count: candidateCount,
        auto_start: true,
      });
      setShowModal(false);
      setTaskPrompt("");
      await load();
    } catch (err) {
      setError(String((err as Error).message));
    } finally {
      setSubmitting(false);
    }
  };

  const activeCount = flows?.filter((f) => f.status === "working" || f.status === "preparing").length ?? 0;
  const completedCount = flows?.filter((f) => f.status === "ready_to_apply" || f.status === "applied").length ?? 0;

  return (
    <div className="multicaShell" style={{ padding: "20px 24px", overflowY: "auto" }}>
      {/* Header */}
      <div className="flowHeader">
        <div>
          <div className="flowEyebrow">
            <GitFork size={13} style={{ color: "var(--accent)" }} />
            <span>AUTONOMOUS SPEC-TO-PR WORKTREES</span>
          </div>
          <h1 className="flowTitle">Coding Flows</h1>
          <p className="flowLede">
            Agents work in isolated Git worktrees, run tests, repair errors, and present verified patches. Zero changes touch your active workspace until you approve.
          </p>
        </div>

        <div className="flowHeaderActions">
          <button className="flowRefreshBtn" onClick={() => void load()} title="Refresh flows">
            <RefreshCw size={13} className={loading ? "spin" : ""} />
          </button>
          <button className="flowLaunchBtn" onClick={() => setShowModal(true)}>
            <Plus size={14} /> Launch Coding Flow
          </button>
        </div>
      </div>

      {/* KPI Cards */}
      <div className="flowStatsGrid">
        <div className="flowStatCard">
          <div className="statLabel">ACTIVE RUNS</div>
          <div className="statValue" style={{ color: activeCount > 0 ? "var(--ok)" : "inherit" }}>
            {activeCount}
          </div>
          <div className="statSub">Isolated worktrees currently running</div>
        </div>

        <div className="flowStatCard">
          <div className="statLabel">VERIFIED PATCHES</div>
          <div className="statValue">{completedCount}</div>
          <div className="statSub">Ready to inspect or applied</div>
        </div>

        <div className="flowStatCard">
          <div className="statLabel">TOTAL RUNS</div>
          <div className="statValue">{flows?.length ?? 0}</div>
          <div className="statSub">Lifetime automated branch builds</div>
        </div>

        <div className="flowStatCard">
          <div className="statLabel">SAFETY BOUNDARY</div>
          <div className="statValue" style={{ color: "var(--ok)", fontSize: "16px", paddingTop: "6px" }}>
            <ShieldCheck size={18} style={{ display: "inline", verticalAlign: "middle", marginRight: 6 }} />
            100% Isolated
          </div>
          <div className="statSub">Base commit locked · Clean rollback guaranteed</div>
        </div>
      </div>

      {/* Visual Pipeline Banner */}
      <div className="flowPipelineCard">
        <div className="pipelineHead">HOW CODING FLOWS WORK</div>
        <div className="pipelineSteps">
          <div className="pipeStep">
            <div className="stepNum">1</div>
            <div className="stepInfo">
              <strong>Describe Task</strong>
              <span>Prompt & checks</span>
            </div>
          </div>
          <div className="pipeArrow"><ArrowRight size={14} /></div>
          <div className="pipeStep">
            <div className="stepNum">2</div>
            <div className="stepInfo">
              <strong>Parallel Worktrees</strong>
              <span>2 competing branches</span>
            </div>
          </div>
          <div className="pipeArrow"><ArrowRight size={14} /></div>
          <div className="pipeStep">
            <div className="stepNum">3</div>
            <div className="stepInfo">
              <strong>Self-Repair Loop</strong>
              <span>Runs tests & fixes</span>
            </div>
          </div>
          <div className="pipeArrow"><ArrowRight size={14} /></div>
          <div className="pipeStep">
            <div className="stepNum">4</div>
            <div className="stepInfo">
              <strong>Diff & Apply</strong>
              <span>You review & merge</span>
            </div>
          </div>
        </div>
      </div>

      {/* Main Content Area */}
      <div className="flowContentArea">
        {flows && flows.length > 0 ? (
          <div className="flowListSection">
            <div className="sectionLabel">Active & Recent Flows ({flows.length})</div>
            <div className="flowsStack">
              {flows.map((flow) => (
                <FlowCard key={flow.id} flow={flow} onChange={() => void load()} />
              ))}
            </div>
          </div>
        ) : (
          <div className="flowEmptySection">
            <div className="emptyNotice">
              <Layers size={24} style={{ color: "var(--accent)", marginBottom: 8 }} />
              <h3>No Coding Flows Active</h3>
              <p>Launch an isolated coding flow to run agents in dedicated Git worktrees without touching your active branch.</p>
            </div>

            {/* Quick Templates */}
            <div className="templatesSection">
              <div className="templatesTitle">Try a Sample Flow Template:</div>
              <div className="templateGrid">
                {TEMPLATES.map((tmpl) => (
                  <div key={tmpl.title} className="templateCard">
                    <h4>{tmpl.title}</h4>
                    <p>{tmpl.prompt}</p>
                    <div className="tmplCmd">
                      <Terminal size={11} /> <code>{tmpl.cmd}</code>
                    </div>
                    <button
                      className="useTmplBtn"
                      onClick={() => {
                        setTaskPrompt(tmpl.prompt);
                        setVerifyCmd(tmpl.cmd);
                        setShowModal(true);
                      }}
                    >
                      <Play size={11} /> Use Template
                    </button>
                  </div>
                ))}
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Launch Flow Modal */}
      {showModal && (
        <div className="flowModalBackdrop" onClick={() => setShowModal(false)}>
          <div className="flowModal" onClick={(e) => e.stopPropagation()}>
            <div className="modalHead">
              <div className="modalTitle">
                <GitBranch size={15} style={{ color: "var(--accent)" }} />
                <span>Launch New Coding Flow</span>
              </div>
              <button className="closeBtn" onClick={() => setShowModal(false)}>
                <X size={15} />
              </button>
            </div>

            <form onSubmit={handleLaunch} className="modalBody">
              {error && <div className="modalError">{error}</div>}

              <div className="formGroup">
                <label>Task Description / Specification *</label>
                <textarea
                  rows={3}
                  placeholder="Describe the change (e.g. Add validation checks to auth schema and update client parser)..."
                  value={taskPrompt}
                  onChange={(e) => setTaskPrompt(e.target.value)}
                  required
                />
              </div>

              <div className="formRow">
                <div className="formGroup" style={{ flex: 2 }}>
                  <label>Verification Command *</label>
                  <input
                    type="text"
                    value={verifyCmd}
                    onChange={(e) => setVerifyCmd(e.target.value)}
                    placeholder="e.g. pytest -q tests/test_auth.py or git diff --check"
                    required
                  />
                  <span className="fieldTip">Must only read or run tests (e.g. pytest, npm test).</span>
                </div>

                <div className="formGroup" style={{ flex: 1 }}>
                  <label>Parallel Candidates</label>
                  <select
                    value={candidateCount}
                    onChange={(e) => setCandidateCount(Number(e.target.value))}
                  >
                    <option value={1}>1 Candidate</option>
                    <option value={2}>2 Candidates (Recommended)</option>
                    <option value={3}>3 Candidates</option>
                  </select>
                </div>
              </div>

              <div className="modalFoot">
                <button type="button" className="cancelBtn" onClick={() => setShowModal(false)}>
                  Cancel
                </button>
                <button type="submit" className="submitLaunchBtn" disabled={submitting || !taskPrompt.trim()}>
                  {submitting ? "Spawning Worktrees..." : "Launch Flow"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
