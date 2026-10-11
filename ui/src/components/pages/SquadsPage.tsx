import {
  Activity,
  AlertCircle,
  Bot,
  Check,
  ChevronDown,
  ChevronRight,
  Clock,
  Copy,
  Cpu,
  FileCode,
  Folder,
  GitBranch,
  Globe,
  Layers,
  Lock,
  MessageSquare,
  Plus,
  Radio,
  RefreshCw,
  Search,
  Send,
  ShieldCheck,
  Terminal,
  Trash2,
  User,
  Users,
  X,
  Zap,
} from "lucide-react";
import { Fragment, useCallback, useEffect, useMemo, useState } from "react";

import { api } from "../../lib/api.ts";
import { parseUnifiedDiff } from "../../lib/diff.ts";
import type {
  Issue,
  IssuePriority,
  IssueStatus,
  TeamCollaborator,
  WorkspaceScope,
} from "../../lib/types.ts";

import { DiffHeader, DiffRows } from "../DiffView.tsx";

// ── Initial Team (Teammates) ──

export const INITIAL_TEAM: TeamCollaborator[] = [
  {
    user_id: "chitranjan",
    user_name: "Chitranjan",
    agent_id: "",
    agent_name: "",
    status: "idle",
    current_activity: "Active in workspace",
  },
  {
    user_id: "nitin",
    user_name: "Nitin",
    agent_id: "",
    agent_name: "",
    status: "idle",
    current_activity: "Active in workspace",
  },
  {
    user_id: "ashish",
    user_name: "Ashish",
    agent_id: "",
    agent_name: "",
    status: "idle",
    current_activity: "Active in workspace",
  },
];

export const DEFAULT_TEAM = INITIAL_TEAM;

// ── Multica Status Icons (SVG exact geometry) ──

function MulticaStatusIcon({ status, size = 14 }: { status: IssueStatus; size?: number }) {
  if (status === "backlog") {
    const count = 12;
    return (
      <svg width={size} height={size} viewBox="0 0 14 14" fill="none" style={{ color: "var(--ink-faint)" }}>
        {Array.from({ length: count }, (_, i) => {
          const angle = (i / count) * Math.PI * 2 - Math.PI / 2;
          const cx = 7 + 5 * Math.cos(angle);
          const cy = 7 + 5 * Math.sin(angle);
          return <circle key={i} cx={cx} cy={cy} r={0.7} fill="currentColor" />;
        })}
      </svg>
    );
  }
  if (status === "in_progress") {
    return (
      <svg width={size} height={size} viewBox="0 0 14 14" fill="none" style={{ color: "#e3a473" }}>
        <circle cx={7} cy={7} r={5.2} stroke="currentColor" strokeWidth={1.3} strokeDasharray="2.5 1.5" />
        <path d="M7,7 L7,2.5 A4.5,4.5 0 0,1 7,11.5 Z" fill="currentColor" />
      </svg>
    );
  }
  if (status === "blocked") {
    return (
      <svg width={size} height={size} viewBox="0 0 14 14" fill="none" style={{ color: "var(--icon-red)" }}>
        <circle cx={7} cy={7} r={5.2} stroke="currentColor" strokeWidth={1.3} />
        <line x1={4} y1={4} x2={10} y2={10} stroke="currentColor" strokeWidth={1.3} />
      </svg>
    );
  }
  if (status === "in_review") {
    return (
      <svg width={size} height={size} viewBox="0 0 14 14" fill="none" style={{ color: "var(--icon-blue)" }}>
        <circle cx={7} cy={7} r={5.2} stroke="currentColor" strokeWidth={1.3} />
        <path d="M7,7 L7,2.5 A4.5,4.5 0 1,1 2.5,7 Z" fill="currentColor" />
      </svg>
    );
  }
  if (status === "done") {
    return (
      <svg width={size} height={size} viewBox="0 0 14 14" fill="none" style={{ color: "var(--ok)" }}>
        <circle cx={7} cy={7} r={5.5} fill="currentColor" />
        <path d="M4.5,7 L6.2,8.8 L9.5,5.2" stroke="#000" strokeWidth={1.4} strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    );
  }
  return <div style={{ width: size, height: size, borderRadius: "50%", border: "1.3px solid currentColor" }} />;
}

// ── Multica Priority Icons ──

function MulticaPriorityIcon({ priority, size = 14 }: { priority: IssuePriority; size?: number }) {
  if (priority === "urgent") {
    return (
      <span title="Urgent" style={{ display: "inline-flex", alignItems: "center" }}>
        <svg width={size} height={size} viewBox="0 0 14 14" fill="none" style={{ color: "var(--icon-red)" }}>
          <path d="M7 2.2L12 11H2L7 2.2Z" stroke="currentColor" strokeWidth={1.2} />
          <line x1={7} y1={5.5} x2={7} y2={8} stroke="currentColor" strokeWidth={1.2} strokeLinecap="round" />
          <circle cx={7} cy={9.6} r={0.6} fill="currentColor" />
        </svg>
      </span>
    );
  }
  if (priority === "high") {
    return (
      <span title="High" style={{ display: "inline-flex", alignItems: "center" }}>
        <svg width={size} height={size} viewBox="0 0 14 14" fill="none" style={{ color: "#e3a473" }}>
          <rect x={2.5} y={8.5} width={2} height={3.5} rx={0.5} fill="currentColor" />
          <rect x={6} y={6} width={2} height={6} rx={0.5} fill="currentColor" />
          <rect x={9.5} y={3.5} width={2} height={8.5} rx={0.5} fill="currentColor" />
        </svg>
      </span>
    );
  }
  if (priority === "medium") {
    return (
      <span title="Medium" style={{ display: "inline-flex", alignItems: "center" }}>
        <svg width={size} height={size} viewBox="0 0 14 14" fill="none" style={{ color: "var(--icon-blue)" }}>
          <rect x={2.5} y={8.5} width={2} height={3.5} rx={0.5} fill="currentColor" />
          <rect x={6} y={6} width={2} height={6} rx={0.5} fill="currentColor" />
          <rect x={9.5} y={3.5} width={2} height={8.5} rx={0.5} fill="var(--line)" />
        </svg>
      </span>
    );
  }
  return (
    <span title="Low" style={{ display: "inline-flex", alignItems: "center" }}>
      <svg width={size} height={size} viewBox="0 0 14 14" fill="none" style={{ color: "var(--ink-faint)" }}>
        <rect x={2.5} y={8.5} width={2} height={3.5} rx={0.5} fill="currentColor" />
        <rect x={6} y={6} width={2} height={6} rx={0.5} fill="var(--line)" />
        <rect x={9.5} y={3.5} width={2} height={8.5} rx={0.5} fill="var(--line)" />
      </svg>
    </span>
  );
}

// ── Agent Runner Color Tag ──

function AgentRunnerBadge({ agentName }: { agentName: string }) {
  const norm = agentName.toLowerCase();
  let badgeClass = "runnerGeneric";
  if (norm.includes("antigravity")) badgeClass = "runnerAntigravity";
  else if (norm.includes("claude")) badgeClass = "runnerClaude";
  else if (norm.includes("codex")) badgeClass = "runnerCodex";
  else if (norm.includes("root")) badgeClass = "runnerRoot";

  return (
    <span className={`runnerBadge ${badgeClass}`}>
      <Bot size={10} />
      <span>{agentName}</span>
    </span>
  );
}

const COLUMNS: { id: IssueStatus; title: string }[] = [
  { id: "backlog", title: "Backlog" },
  { id: "in_progress", title: "In Progress" },
  { id: "blocked", title: "Blocked" },
  { id: "in_review", title: "In Review" },
  { id: "done", title: "Done" },
];

export function SquadsPage() {
  const [issues, setIssues] = useState<Issue[]>([]);
  const [scopeFilter, setScopeFilter] = useState<"all" | "shared" | "personal">("all");
  const [searchQuery, setSearchQuery] = useState("");

  // Modals & Drawers
  const [showNewIssue, setShowNewIssue] = useState(false);
  const [newIssueInitialStatus, setNewIssueInitialStatus] = useState<IssueStatus>("backlog");
  const [activeIssueId, setActiveIssueId] = useState<string | null>(null);

  // Actions & Messaging state
  const [loading, setLoading] = useState(false);
  const [actionError, setActionError] = useState("");
  const [rejectFeedback, setRejectFeedback] = useState("");
  const [showRejectBox, setShowRejectBox] = useState(false);

  // Dynamic Team & Teammates state
  const [teamMembers, setTeamMembers] = useState<TeamCollaborator[]>(INITIAL_TEAM);
  const [squadId, setSquadId] = useState<string>("team-product");
  const [showAddTeammate, setShowAddTeammate] = useState(false);
  const [newTeammateName, setNewTeammateName] = useState("");
  const [addingTeammate, setAddingTeammate] = useState(false);

  // Connect Agent & Team Modal State
  const [showTeamModal, setShowTeamModal] = useState(false);
  const [teamModalTab, setTeamModalTab] = useState<"connect" | "roster">("roster");
  const [connectAgentName, setConnectAgentName] = useState("Claude Code");
  const [connectUserName, setConnectUserName] = useState("Nitin");
  const [copiedCmdId, setCopiedCmdId] = useState<string | null>(null);

  // Live Intercom state
  const [intercomSpeaker, setIntercomSpeaker] = useState<{ id: string; name: string; type: "human" | "agent"; agent: string }>({
    id: "chitranjan",
    name: "Chitranjan",
    type: "human",
    agent: "",
  });
  const [intercomRecipient, setIntercomRecipient] = useState("@all-agents");
  const [intercomContent, setIntercomContent] = useState("");

  // Autonomous Agent Discussion State
  const [autonomousTopic, setAutonomousTopic] = useState("Contract negotiation between schema.py and client.ts");
  const [discussing, setDiscussing] = useState(false);
  const [copiedBridge, setCopiedBridge] = useState(false);

  // Multica Execution Room State
  const [drawerTab, setDrawerTab] = useState<"execution" | "intercom" | "diff">("execution");
  const [timelineFilter, setTimelineFilter] = useState<string>("all");
  const [expandedStepIds, setExpandedStepIds] = useState<Record<string, boolean>>({});
  const [triggeringStep, setTriggeringStep] = useState(false);
  const [copiedStepOutput, setCopiedStepOutput] = useState<string | null>(null);

  // New Lease Input
  const [leasePathInput, setLeasePathInput] = useState("");


  // New Issue Form State
  const [newTitle, setNewTitle] = useState("");
  const [newDescription, setNewDescription] = useState("");
  const [newPriority, setNewPriority] = useState<IssuePriority>("medium");
  const [newScope, setNewScope] = useState<WorkspaceScope>("shared");
  const [newWorkspacePath, setNewWorkspacePath] = useState("");
  const [newVerificationCmd, setNewVerificationCmd] = useState("pytest -q tests/test_auth.py");
  const [selectedCollaboratorIds, setSelectedCollaboratorIds] = useState<string[]>(["chitranjan", "nitin"]);

  const handleAddTeammate = async (e?: React.FormEvent) => {
    if (e) e.preventDefault();
    const name = newTeammateName.trim();
    if (!name || addingTeammate) return;
    setAddingTeammate(true);
    const userId = name.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "") || `user-${Date.now()}`;
    const newMember: TeamCollaborator = {
      user_id: userId,
      user_name: name,
      agent_id: "",
      agent_name: "",
      status: "idle",
      current_activity: "Active in workspace",
    };
    try {
      await api.addSquadMember(squadId, { user_name: name, user_id: userId });
      setTeamMembers((prev) => {
        if (prev.some((m) => m.user_id === userId)) return prev;
        return [...prev, newMember];
      });
      setSelectedCollaboratorIds((prev) => (prev.includes(userId) ? prev : [...prev, userId]));
      setNewTeammateName("");
      setShowAddTeammate(false);
    } catch (err) {
      setActionError(String((err as Error).message));
    } finally {
      setAddingTeammate(false);
    }
  };

  const handleDeleteTeammate = async (userId: string) => {
    try {
      await api.removeSquadMember(squadId, userId);
      setTeamMembers((prev) => prev.filter((m) => m.user_id !== userId));
      setSelectedCollaboratorIds((prev) => prev.filter((id) => id !== userId));
      await loadData();
    } catch (err) {
      setActionError(String((err as Error).message));
    }
  };

  const loadData = useCallback(async () => {
    try {
      setLoading(true);
      const [issuesRes, wsRes, squadsRes] = await Promise.all([
        api.issues(),
        api.workspaces().catch(() => ({ workspaces: [], personal: [], shared: [] })),
        api.squads().catch(() => ({ squads: [] })),
      ]);
      setIssues(issuesRes.issues);
      if (squadsRes?.squads?.length) {
        const primary = squadsRes.squads[0];
        setSquadId(primary.id);
        if (primary.members && primary.members.length > 0) {
          setTeamMembers(primary.members);
        }
      }
      if (!newWorkspacePath && wsRes.workspaces?.length) {
        setNewWorkspacePath(wsRes.workspaces[0].path);
      }
    } catch (e) {
      setActionError(String((e as Error).message));
    } finally {
      setLoading(false);
    }
  }, [newWorkspacePath]);

  useEffect(() => {
    void loadData();
    const interval = setInterval(loadData, 3000);
    return () => clearInterval(interval);
  }, [loadData]);

  // Selected issue
  const activeIssue = useMemo(() => {
    return issues.find((i) => i.id === activeIssueId) || null;
  }, [issues, activeIssueId]);

  // Real-time execution trajectory filtered by phase
  const filteredTimeline = useMemo(() => {
    if (!activeIssue?.execution_timeline) return [];
    if (timelineFilter === "all") return activeIssue.execution_timeline;
    return activeIssue.execution_timeline.filter(
      (s) => s.phase.toLowerCase() === timelineFilter.toLowerCase()
    );
  }, [activeIssue?.execution_timeline, timelineFilter]);

  const handleTriggerAgentStep = async (issueId: string) => {
    setTriggeringStep(true);
    setActionError("");
    try {
      const res = await api.triggerAgentStep(issueId, {
        agent_name: connectAgentName || "Claude Code",
        user_name: connectUserName || "Nitin",
      });
      setIssues((prev) => prev.map((i) => (i.id === issueId ? res.issue : i)));
    } catch (err) {
      setActionError(String((err as Error).message));
    } finally {
      setTriggeringStep(false);
    }
  };

  const toggleStepExpanded = (stepId: string) => {
    setExpandedStepIds((prev) => ({ ...prev, [stepId]: !prev[stepId] }));
  };


  // Filtered issues
  const filteredIssues = useMemo(() => {
    return issues.filter((issue) => {
      if (scopeFilter !== "all" && issue.workspace_scope !== scopeFilter) return false;
      if (searchQuery.trim()) {
        const q = searchQuery.toLowerCase();
        return (
          issue.title.toLowerCase().includes(q) ||
          issue.id.toLowerCase().includes(q) ||
          (issue.branch && issue.branch.toLowerCase().includes(q))
        );
      }
      return true;
    });
  }, [issues, scopeFilter, searchQuery]);

  // Actions
  const handleUpdateStatus = async (issueId: string, nextStatus: IssueStatus) => {
    try {
      await api.updateIssue(issueId, { status: nextStatus });
      await loadData();
    } catch (e) {
      setActionError(String((e as Error).message));
    }
  };

  const handleApprove = async (issueId: string) => {
    setActionError("");
    try {
      await api.approveIssue(issueId);
      await loadData();
    } catch (e) {
      setActionError(String((e as Error).message));
    }
  };

  const handleReject = async (issueId: string) => {
    if (!rejectFeedback.trim()) return;
    setActionError("");
    try {
      await api.rejectIssue(issueId, rejectFeedback);
      setRejectFeedback("");
      setShowRejectBox(false);
      await loadData();
    } catch (e) {
      setActionError(String((e as Error).message));
    }
  };

  const handleSendMessage = async (issueId: string) => {
    if (!intercomContent.trim()) return;
    setActionError("");
    try {
      await api.sendIssueMessage(issueId, {
        content: intercomContent,
        sender_id: intercomSpeaker.id,
        sender_name: intercomSpeaker.name,
        sender_type: intercomSpeaker.type,
        agent_name: intercomSpeaker.agent,
        recipient: intercomRecipient,
      });
      setIntercomContent("");
      await loadData();
    } catch (e) {
      setActionError(String((e as Error).message));
    }
  };

  const handleStartAutonomousDiscussion = async (issueId: string) => {
    if (!autonomousTopic.trim()) return;
    setDiscussing(true);
    setActionError("");
    try {
      await api.startAutonomousDiscussion(issueId, {
        topic: autonomousTopic.trim(),
        agent_a: "Antigravity",
        user_a: "Chitranjan",
        agent_b: "Claude Code",
        user_b: "Nitin",
      });
      await loadData();
    } catch (e) {
      setActionError(String((e as Error).message));
    } finally {
      setDiscussing(false);
    }
  };

  const handleClaimLease = async (issueId: string) => {
    if (!leasePathInput.trim()) return;
    try {
      await api.claimIssueLease(issueId, leasePathInput.trim(), intercomSpeaker.agent || "Antigravity");
      setLeasePathInput("");
      await loadData();
    } catch (e) {
      setActionError(String((e as Error).message));
    }
  };

  const handleReleaseLease = async (issueId: string, filePath: string) => {
    try {
      await api.releaseIssueLease(issueId, filePath);
      await loadData();
    } catch (e) {
      setActionError(String((e as Error).message));
    }
  };

  const handleCreateIssueSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newTitle.trim()) return;
    setActionError("");

    const assignedCollabs = teamMembers.filter((m) => selectedCollaboratorIds.includes(m.user_id));

    try {
      await api.createIssue({
        title: newTitle.trim(),
        description: newDescription.trim(),
        priority: newPriority,
        status: newIssueInitialStatus,
        workspace_scope: newScope,
        workspace_path: newWorkspacePath || "shared:repo",
        verification_command: newVerificationCmd.trim(),
        created_by: teamMembers[0]?.user_name || "Chitranjan",
        collaborators: assignedCollabs.length > 0 ? assignedCollabs : [teamMembers[0] || INITIAL_TEAM[0]],
      });
      setNewTitle("");
      setNewDescription("");
      setShowNewIssue(false);
      await loadData();
    } catch (err) {
      setActionError(String((err as Error).message));
    }
  };

  const parsedDiff = useMemo(() => {
    return activeIssue?.diff ? parseUnifiedDiff(activeIssue.diff) : [];
  }, [activeIssue?.diff]);

  return (
    <div className="multicaShell">
      {/* Multica Header Bar */}
      <header className="multicaHeader">
        <div className="multicaHeaderLeft">
          <div className="multicaTitle">
            <Users size={14} style={{ color: "var(--accent)" }} />
            <span>Development Team</span>
          </div>

          {/* Scope Filter Switch */}
          <div className="multicaScopeSwitch">
            <button
              className={`multicaScopeTab ${scopeFilter === "all" ? "active" : ""}`}
              onClick={() => setScopeFilter("all")}
            >
              All
            </button>
            <button
              className={`multicaScopeTab ${scopeFilter === "shared" ? "active" : ""}`}
              onClick={() => setScopeFilter("shared")}
              title="Shared repository issues"
            >
              <Globe size={11} />
              Shared
            </button>
            <button
              className={`multicaScopeTab ${scopeFilter === "personal" ? "active" : ""}`}
              onClick={() => setScopeFilter("personal")}
              title="Personal branch tasks"
            >
              <Folder size={11} />
              Personal
            </button>
          </div>
        </div>

        <div className="multicaHeaderRight">
          {/* Quick Search */}
          <div className="multicaSearch">
            <Search size={12} className="multicaSearchIcon" />
            <input
              type="text"
              placeholder="Filter issues..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
            />
            {searchQuery ? (
              <button className="clearBtn" onClick={() => setSearchQuery("")}>
                <X size={11} />
              </button>
            ) : null}
          </div>

          {/* Connect Coding Agent Button */}
          <button
            type="button"
            className="connectAgentHeaderBtn"
            onClick={() => {
              setTeamModalTab("connect");
              setShowTeamModal(true);
            }}
            title="Connect your local coding agent (Claude Code, Antigravity, Codex)"
          >
            <Terminal size={12} />
            <span>Connect Agent</span>
          </button>

          {/* Manage Team Button */}
          <button
            type="button"
            className="multicaTeammateBtn"
            onClick={() => {
              setTeamModalTab("roster");
              setShowTeamModal(true);
            }}
            title="View team roster & manage teammates"
          >
            <Users size={12} />
            <span>Team ({teamMembers.length})</span>
          </button>

          {/* Primary Action Button */}
          <button
            className="multicaNewIssueBtn"
            onClick={() => {
              setNewIssueInitialStatus("backlog");
              setShowNewIssue(true);
            }}
          >
            <Plus size={13} />
            <span>New issue</span>
          </button>

          <button className="iconButton" onClick={() => void loadData()} title="Refresh">
            <RefreshCw size={13} className={loading ? "spinner" : ""} />
          </button>
        </div>
      </header>

      {/* Error Strip */}
      {actionError ? (
        <div className="multicaErrorStrip">
          <AlertCircle size={13} />
          <span>{actionError}</span>
          <button className="iconButton" onClick={() => setActionError("")}>
            <X size={12} />
          </button>
        </div>
      ) : null}

      {/* Multica Board View Container */}
      <div className="multicaBoardContainer">
        <div className="multicaColumnsRow">
          {COLUMNS.map((col) => {
            const colIssues = filteredIssues.filter((i) => i.status === col.id);
            const isReviewGate = col.id === "in_review";

            return (
              <div key={col.id} className={`multicaColumn ${isReviewGate ? "reviewGate" : ""}`}>
                {/* Column Header */}
                <div className="multicaColHeader">
                  <div className="multicaColHeaderTitle">
                    <MulticaStatusIcon status={col.id} size={13} />
                    <span className="multicaColName">{col.title}</span>
                    <span className="multicaColCount">{colIssues.length}</span>
                  </div>
                  <button
                    className="multicaColAddBtn"
                    title={`Add issue to ${col.title}`}
                    onClick={() => {
                      setNewIssueInitialStatus(col.id);
                      setShowNewIssue(true);
                    }}
                  >
                    <Plus size={12} />
                  </button>
                </div>

                {/* Column Cards List */}
                <div className="multicaCardList scroll">
                  {colIssues.length === 0 ? (
                    <div className="multicaEmptyCol">
                      <span>No issues</span>
                    </div>
                  ) : (
                    colIssues.map((issue) => {
                      const isSelected = issue.id === activeIssueId;
                      const collabs = issue.collaborators || [];
                      const hasActiveAgent = collabs.some((c) => c.status === "working" || c.status === "holding_lease");
                      const activeAgentActivity = collabs.find((c) => c.status === "working")?.current_activity;

                      return (
                        <div
                          key={issue.id}
                          className={`multicaCard ${isSelected ? "selected" : ""} ${
                            issue.status === "in_review" ? "inReview" : ""
                          }`}
                          onClick={() => setActiveIssueId(issue.id)}
                        >
                          {/* Row 1: Priority + Identifier (left), Live Agent Working Badge (right) */}
                          <div className="multicaCardTop">
                            <div className="multicaCardKeyGroup">
                              <MulticaPriorityIcon priority={issue.priority} size={13} />
                              <span className="multicaIdentifier">{issue.id}</span>
                            </div>

                            {hasActiveAgent ? (
                              <span
                                className="multicaAgentWorkingBadge"
                                title={activeAgentActivity || "Agent executing in background"}
                              >
                                <span className="miniDot" />
                                <span>Agent Active</span>
                              </span>
                            ) : null}
                          </div>

                          {/* Row 2: Title (crisp, 2 lines max) */}
                          <div className="multicaCardTitle" title={issue.title}>
                            {issue.title}
                          </div>

                          {/* Row 3: Scope Tag & Branch Tag */}
                          <div className="multicaCardChipRow">
                            <span className={`multicaScopeChip ${issue.workspace_scope}`}>
                              {issue.workspace_scope === "shared" ? <Globe size={10} /> : <Folder size={10} />}
                              {issue.workspace_scope}
                            </span>
                            {issue.branch ? (
                              <span className="multicaBranchChip" title={issue.branch}>
                                <GitBranch size={9} />
                                {issue.branch.replace("feat/", "").replace("squad/", "")}
                              </span>
                            ) : null}
                          </div>

                          {/* Row 4: Collaborator Human + Agent Pairs & Review Gate Indicator */}
                          <div className="multicaCardBottom">
                            <div className="multicaCollabsPillRow">
                              {collabs.length > 0 ? (
                                collabs.map((c) => (
                                  <div
                                    key={c.user_id}
                                    className="collabMiniChip"
                                    title={c.agent_name ? `${c.user_name} paired with ${c.agent_name}${c.current_activity ? ` (${c.current_activity})` : ""}` : `${c.user_name} (Teammate)`}
                                  >
                                    <span className="collabUser">{c.user_name}</span>
                                    {c.agent_name ? (
                                      <>
                                        <span className="collabSep">·</span>
                                        <span className="collabAgent">{c.agent_name}</span>
                                      </>
                                    ) : null}
                                  </div>
                                ))
                              ) : (
                                <span className="unassignedTag">Unassigned</span>
                              )}
                            </div>

                            {issue.status === "in_review" ? (
                              <span className="multicaReviewGatePill">
                                <ShieldCheck size={11} /> Review Gate
                              </span>
                            ) : null}
                          </div>
                        </div>
                      );
                    })
                  )}
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* Multica Issue Execution Workspace Room */}
      {activeIssue ? (
        <div className="multicaDrawerBackdrop" onClick={() => setActiveIssueId(null)}>
          <aside className="multicaDrawer wideWorkspace" onClick={(e) => e.stopPropagation()}>
            {/* Top Bar */}
            <div className="workspaceTopBar">
              <div className="workspaceTopLeft">
                <span className="drawerId">{activeIssue.id}</span>
                <select
                  className="drawerStatusSelect"
                  value={activeIssue.status}
                  onChange={(e) => handleUpdateStatus(activeIssue.id, e.target.value as IssueStatus)}
                >
                  <option value="backlog">Backlog</option>
                  <option value="in_progress">In Progress</option>
                  <option value="blocked">Blocked</option>
                  <option value="in_review">In Review (Gate)</option>
                  <option value="done">Done</option>
                </select>
                <div className="drawerPriorityWrap">
                  <MulticaPriorityIcon priority={activeIssue.priority} size={14} />
                  <span className="priorityText">{activeIssue.priority}</span>
                </div>
                <span className="scopeBadge">
                  {activeIssue.workspace_scope === "shared" ? <Globe size={11} /> : <Folder size={11} />}
                  <span>{activeIssue.workspace_scope === "shared" ? "Shared Repo" : "Personal"}</span>
                </span>
                {activeIssue.branch && (
                  <span className="branchPill">
                    <GitBranch size={11} />
                    <span>{activeIssue.branch}</span>
                  </span>
                )}
              </div>

              <div className="workspaceTopRight" style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                <button
                  type="button"
                  className="triggerStepTopBtn"
                  onClick={() => void handleTriggerAgentStep(activeIssue.id)}
                  disabled={triggeringStep}
                  title="Advance next live agent execution step"
                >
                  <Zap size={12} style={{ color: "var(--accent)" }} />
                  <span>{triggeringStep ? "Advancing..." : "Advance Step"}</span>
                </button>
                <button className="iconButton" onClick={() => setActiveIssueId(null)}>
                  <X size={15} />
                </button>
              </div>
            </div>

            {/* Header Title & Brief */}
            <div className="workspaceHeaderInfo">
              <h2 className="drawerTitle">{activeIssue.title}</h2>
              {activeIssue.description ? (
                <p className="drawerDescription">{activeIssue.description}</p>
              ) : null}
            </div>

            {/* Workspace Navigation Tabs */}
            <div className="workspaceTabs">
              <button
                type="button"
                className={`workspaceTabBtn ${drawerTab === "execution" ? "active" : ""}`}
                onClick={() => setDrawerTab("execution")}
              >
                <Activity size={12} />
                <span>Realtime Execution</span>
                <span className="tabBadge">{activeIssue.execution_timeline?.length || 0}</span>
                {activeIssue.status === "in_progress" && <span className="tabLivePulse" />}
              </button>
              <button
                type="button"
                className={`workspaceTabBtn ${drawerTab === "intercom" ? "active" : ""}`}
                onClick={() => setDrawerTab("intercom")}
              >
                <MessageSquare size={12} />
                <span>Team & Agent Intercom</span>
                <span className="tabBadge">{activeIssue.messages?.length || 0}</span>
              </button>
              <button
                type="button"
                className={`workspaceTabBtn ${drawerTab === "diff" ? "active" : ""}`}
                onClick={() => setDrawerTab("diff")}
              >
                <ShieldCheck size={12} />
                <span>Review Gate & Diff</span>
                {activeIssue.diff && <span className="tabBadge">Diff ready</span>}
              </button>
            </div>

            {/* Dual Column Workspace Layout */}
            <div className="workspaceLayout">
              {/* Main Column */}
              <div className="workspaceMain scroll">
                {/* ── TAB 1: REALTIME EXECUTION TIMELINE & RUN SPOTLIGHT ── */}
                {drawerTab === "execution" && (
                  <>
                    {/* Active Run Spotlight Card */}
                    {activeIssue.active_run ? (
                      <div className="activeRunBanner">
                        <div className="activeRunTop">
                          <div className="activeRunIdentity">
                            <span className="liveRunPulse">
                              <span className="liveRunDot" />
                              <span className="liveRunPing" />
                            </span>
                            <span className="runIdTitle">Run #{activeIssue.active_run.id}</span>
                            <AgentRunnerBadge agentName={activeIssue.active_run.agent_name} />
                            <span className="runUserName">({activeIssue.active_run.user_name})</span>
                          </div>
                          <div className="activeRunMeta">
                            <span className={`phaseTag phase-${(activeIssue.active_run.phase || "edit").toLowerCase()}`}>
                              {activeIssue.active_run.phase || "Edit"}
                            </span>
                            <span className="runDurationText">
                              <Clock size={11} />
                              <span>Live in progress</span>
                            </span>
                          </div>
                        </div>

                        {/* Progress Bar */}
                        <div className="runProgressWrap">
                          <div className="runProgressLabels">
                            <span>Step Progress</span>
                            <span>
                              Step {activeIssue.active_run.current_step} of {Math.max(activeIssue.active_run.step_count, 5)} (
                              {Math.round(((activeIssue.active_run.current_step) / Math.max(activeIssue.active_run.step_count, 5)) * 100)}%)
                            </span>
                          </div>
                          <div className="runProgressBar">
                            <div
                              className="runProgressFill"
                              style={{
                                width: `${Math.min(100, Math.round(((activeIssue.active_run.current_step) / Math.max(activeIssue.active_run.step_count, 5)) * 100))}%`,
                              }}
                            />
                          </div>
                        </div>

                        {/* Current Action Highlight */}
                        <div className="runCurrentAction">
                          <div className="currentActionHeader">
                            <span className="actionPill">{activeIssue.active_run.last_tool || "active_tool"}</span>
                            {activeIssue.active_run.active_file && (
                              <span className="filePill">
                                <FileCode size={11} />
                                {activeIssue.active_run.active_file}
                              </span>
                            )}
                          </div>
                          <p className="currentActionText">
                            {activeIssue.active_run.current_activity || "Agent executing next operation..."}
                          </p>
                        </div>

                        {/* Controls Row */}
                        <div className="runControlsRow">
                          <button
                            type="button"
                            className="advanceStepBtn"
                            onClick={() => void handleTriggerAgentStep(activeIssue.id)}
                            disabled={triggeringStep}
                          >
                            <Zap size={11} />
                            <span>{triggeringStep ? "Advancing..." : "Advance Next Agent Step"}</span>
                          </button>
                          <button
                            type="button"
                            className="bridgePulseCopyBtn"
                            onClick={() => {
                              void navigator.clipboard.writeText(
                                `python -m tura_code.squads.bridge pulse --issue ${activeIssue.id} --user "${connectUserName || "Developer"}" --agent "${connectAgentName || "Claude Code"}" --activity "Working on implementation"`
                              );
                              setCopiedBridge(true);
                              setTimeout(() => setCopiedBridge(false), 2000);
                            }}
                          >
                            {copiedBridge ? <Check size={11} /> : <Copy size={11} />}
                            <span>{copiedBridge ? "Copied CLI" : "Copy CLI Heartbeat"}</span>
                          </button>
                        </div>
                      </div>
                    ) : (
                      <div className="noActiveRunBanner">
                        <div className="noRunInfo">
                          <Bot size={16} style={{ color: "var(--ink-muted)" }} />
                          <span>No active run in progress. Connect your agent CLI or advance a step to start executing.</span>
                        </div>
                        <button
                          type="button"
                          className="advanceStepBtn"
                          onClick={() => void handleTriggerAgentStep(activeIssue.id)}
                          disabled={triggeringStep}
                        >
                          <Zap size={11} />
                          <span>Start Agent Run</span>
                        </button>
                      </div>
                    )}

                    {/* Trajectory Timeline Feed */}
                    <div className="timelineSection">
                      <div className="timelineHeader">
                        <div className="timelineTitleWrap">
                          <Layers size={13} style={{ color: "var(--icon-blue)" }} />
                          <h4>Real-Time Execution Trajectory</h4>
                          <span className="timelineCountBadge">{filteredTimeline.length} steps</span>
                        </div>
                        <div className="phaseFilterBar">
                          {["all", "Search", "Inspect", "Edit", "Test", "Gate"].map((phaseKey) => (
                            <button
                              key={phaseKey}
                              type="button"
                              className={`phaseFilterBtn ${timelineFilter === phaseKey ? "active" : ""}`}
                              onClick={() => setTimelineFilter(phaseKey)}
                            >
                              {phaseKey}
                            </button>
                          ))}
                        </div>
                      </div>

                      <div className="timelineTrail">
                        {filteredTimeline.length > 0 ? (
                          filteredTimeline.map((step, idx) => {
                            const isExpanded = !!expandedStepIds[step.id];
                            const isRunning = step.status === "running";
                            const isLast = idx === filteredTimeline.length - 1;
                            return (
                              <div key={step.id || idx} className={`timelineStepItem ${isRunning ? "running" : ""}`}>
                                <div className="timelineStepGutter">
                                  <div className={`stepNode ${step.status}`}>
                                    {isRunning ? (
                                      <div className="stepSpinner" />
                                    ) : step.status === "failed" ? (
                                      <AlertCircle size={10} />
                                    ) : (
                                      <Check size={10} />
                                    )}
                                  </div>
                                  {!isLast && <div className="stepConnectorLine" />}
                                </div>

                                <div className="timelineStepCard">
                                  <div className="stepCardHead">
                                    <div className="stepBadges">
                                      <span className={`phaseTag phase-${step.phase.toLowerCase()}`}>
                                        {step.phase}
                                      </span>
                                      <span className="stepToolTag">{step.tool || "action"}</span>
                                      <span className="stepAgentName">
                                        {step.agent_name} ({step.user_name})
                                      </span>
                                    </div>
                                    <div className="stepHeadRight">
                                      <span className="stepTimestamp">
                                        {new Date(step.timestamp * 1000).toLocaleTimeString([], {
                                          hour: "2-digit",
                                          minute: "2-digit",
                                          second: "2-digit",
                                        })}
                                      </span>
                                      <span className={`stepStatusChip ${step.status}`}>
                                        {step.status === "running" ? "In Progress" : "Completed"}
                                      </span>
                                    </div>
                                  </div>

                                  <p className="stepActivityDesc">{step.activity}</p>

                                  {step.target_file && (
                                    <div className="stepTargetFile">
                                      <FileCode size={11} />
                                      <code>{step.target_file}</code>
                                    </div>
                                  )}

                                  {step.output_snippet && (
                                    <div className="stepOutputContainer">
                                      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                                        <button
                                          type="button"
                                          className="stepOutputToggle"
                                          onClick={() => toggleStepExpanded(step.id)}
                                        >
                                          <Terminal size={10} />
                                          <span>Execution Output & Trace</span>
                                          {isExpanded ? <ChevronDown size={11} /> : <ChevronRight size={11} />}
                                        </button>
                                        {isExpanded && (
                                          <button
                                            type="button"
                                            className="btnSecondary"
                                            style={{ padding: "2px 6px", fontSize: "10px", height: "auto", display: "inline-flex", alignItems: "center", gap: "4px" }}
                                            onClick={() => {
                                              void navigator.clipboard.writeText(step.output_snippet || "");
                                              setCopiedStepOutput(step.id);
                                              setTimeout(() => setCopiedStepOutput(null), 2000);
                                            }}
                                          >
                                            {copiedStepOutput === step.id ? <Check size={10} /> : <Copy size={10} />}
                                            <span>{copiedStepOutput === step.id ? "Copied" : "Copy Trace"}</span>
                                          </button>
                                        )}
                                      </div>
                                      {isExpanded && (
                                        <pre className="stepOutputPre">
                                          <code>{step.output_snippet}</code>
                                        </pre>
                                      )}
                                    </div>
                                  )}
                                </div>
                              </div>
                            );
                          })
                        ) : (
                          <div className="emptyIntercom">
                            <span>No execution steps recorded matching "{timelineFilter}". Advance step or trigger tool to view real-time trajectory.</span>
                          </div>
                        )}
                      </div>
                    </div>
                  </>
                )}

                {/* ── TAB 2: INTERCOM & AUTONOMOUS AGENT DISCUSSION ── */}
                {drawerTab === "intercom" && (
                  <div className="drawerSection" style={{ borderTop: "none", paddingTop: 0 }}>
                    {/* Autonomous Agent-to-Agent Discussion Card */}
                    <div className="autonomousSyncCard">
                      <div className="syncCardHead">
                        <div className="syncCardTitle">
                          <Zap size={13} style={{ color: "var(--accent)" }} />
                          <span>Autonomous Agent Discussion</span>
                        </div>
                        <span className="syncTag">Zero Human Friction</span>
                      </div>
                      <p className="syncDescription">
                        Let your local agent (Antigravity) and your teammate's agent (Claude Code) discuss interfaces, file leases, and tests across the cloud without human intervention.
                      </p>
                      <div className="syncActionRow">
                        <input
                          type="text"
                          value={autonomousTopic}
                          onChange={(e) => setAutonomousTopic(e.target.value)}
                          placeholder="Discussion topic (e.g. Contract negotiation between schema.py and client.ts)..."
                        />
                        <button
                          className="syncTriggerBtn"
                          onClick={() => void handleStartAutonomousDiscussion(activeIssue.id)}
                          disabled={discussing}
                        >
                          {discussing ? "Agents Conversing..." : "⚡ Let Agents Discuss"}
                        </button>
                      </div>
                      <div className="quickTopics">
                        <button
                          type="button"
                          className="quickTopicBtn"
                          onClick={() => setAutonomousTopic("Align token schema and client.ts parser")}
                        >
                          Contract sync
                        </button>
                        <button
                          type="button"
                          className="quickTopicBtn"
                          onClick={() => setAutonomousTopic("Optimistic lock handover and pytest verification")}
                        >
                          Lock handover
                        </button>
                        <button
                          type="button"
                          className="quickTopicBtn"
                          onClick={() => setAutonomousTopic("Review diff and approve PR")}
                        >
                          Pre-merge check
                        </button>
                      </div>
                    </div>

                    {/* Messages Feed */}
                    <div className="intercomFeed scroll" style={{ maxHeight: "380px" }}>
                      {activeIssue.messages && activeIssue.messages.length > 0 ? (
                        activeIssue.messages.map((msg) => {
                          const isAutonomous =
                            msg.action_type === "agent_query" ||
                            msg.action_type === "agent_response" ||
                            msg.action_type === "lease_claimed" ||
                            msg.action_type === "agreement_synced";
                          return (
                            <div
                              key={msg.id}
                              className={`intercomMessageItem ${
                                isAutonomous
                                  ? "autonomous"
                                  : msg.sender_type === "agent"
                                  ? "fromAgent"
                                  : "fromHuman"
                              }`}
                            >
                              <div className="messageHead">
                                <div className="messageSender">
                                  {msg.sender_type === "agent" ? (
                                    <span className="senderPill agent">
                                      <Bot size={11} />
                                      {msg.agent_name || msg.sender_name}
                                    </span>
                                  ) : (
                                    <span className="senderPill human">
                                      <User size={11} />
                                      {msg.sender_name}
                                    </span>
                                  )}
                                  <span className="mentionTag">{msg.recipient}</span>
                                  {isAutonomous && <span className="ipcTag">🤖 Autonomous IPC</span>}
                                </div>
                                <span className="messageTime">
                                  {new Date(msg.created_at * 1000).toLocaleTimeString([], {
                                    hour: "2-digit",
                                    minute: "2-digit",
                                  })}
                                </span>
                              </div>
                              <div className="messageBody">{msg.content}</div>
                              {msg.files_mentioned && msg.files_mentioned.length > 0 && (
                                <div className="filesMentionedRow">
                                  {msg.files_mentioned.map((file) => (
                                    <span key={file} className="fileMentionPill">
                                      <FileCode size={10} />
                                      {file}
                                    </span>
                                  ))}
                                </div>
                              )}
                            </div>
                          );
                        })
                      ) : (
                        <div className="emptyIntercom">
                          <span>No messages yet. Send an instruction or start an autonomous discussion to coordinate with agents in real time.</span>
                        </div>
                      )}
                    </div>

                    {/* Intercom Composer */}
                    <div className="intercomComposer">
                      <div className="composerControls">
                        <div className="controlGroup">
                          <label>Speaking as:</label>
                          <select
                            value={`${intercomSpeaker.id}:${intercomSpeaker.type}`}
                            onChange={(e) => {
                              const [id, type] = e.target.value.split(":");
                              const member = teamMembers.find((m) => m.user_id === id);
                              if (member) {
                                setIntercomSpeaker({
                                  id: member.user_id,
                                  name: type === "agent" ? (member.agent_name || `${member.user_name}'s Agent`) : member.user_name,
                                  type: type as "human" | "agent",
                                  agent: member.agent_name || "Agent",
                                });
                              }
                            }}
                          >
                            {teamMembers.map((member) => (
                              <Fragment key={member.user_id}>
                                <option value={`${member.user_id}:human`}>{member.user_name} (Teammate)</option>
                                <option value={`${member.user_id}:agent`}>
                                  {member.agent_name ? `${member.agent_name} (Agent)` : `${member.user_name}'s Agent`}
                                </option>
                              </Fragment>
                            ))}
                          </select>
                        </div>

                        <div className="quickMentions">
                          {["@all-agents", ...teamMembers.map((m) => `@${m.user_name}`)].map((target) => (
                            <button
                              key={target}
                              type="button"
                              className={`mentionBtn ${intercomRecipient === target ? "active" : ""}`}
                              onClick={() => setIntercomRecipient(target)}
                            >
                              {target}
                            </button>
                          ))}
                        </div>
                      </div>

                      <div className="composerInputRow">
                        <input
                          type="text"
                          placeholder={`Message ${intercomRecipient}... (e.g. "Keep auth payload backwards compatible")`}
                          value={intercomContent}
                          onChange={(e) => setIntercomContent(e.target.value)}
                          onKeyDown={(e) => {
                            if (e.key === "Enter" && !e.shiftKey) {
                              e.preventDefault();
                              void handleSendMessage(activeIssue.id);
                            }
                          }}
                        />
                        <button
                          className="composerSendBtn"
                          onClick={() => void handleSendMessage(activeIssue.id)}
                          disabled={!intercomContent.trim()}
                          title="Send message to agent"
                        >
                          <Send size={13} />
                        </button>
                      </div>
                    </div>
                  </div>
                )}

                {/* ── TAB 3: REVIEW GATE & DIFF ── */}
                {drawerTab === "diff" && (
                  <div className="drawerSection" style={{ borderTop: "none", paddingTop: 0 }}>
                    <div className="multicaReviewGateCard">
                      <div className="gateHeader">
                        <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
                          <ShieldCheck size={14} style={{ color: "var(--ok)" }} />
                          <span className="gateCmd">{activeIssue.verification_command || "Verification command not specified"}</span>
                        </div>
                        <span className={`gateBadge ${activeIssue.verification_passed ? "pass" : "fail"}`}>
                          {activeIssue.verification_passed ? "PASS" : "FAIL"}
                        </span>
                      </div>

                      {activeIssue.verification_output ? (
                        <div className="gateTerminal">
                          <div className="terminalBar">
                            <Terminal size={11} />
                            <span>Verification Test Output</span>
                          </div>
                          <pre className="terminalLog">{activeIssue.verification_output}</pre>
                        </div>
                      ) : null}

                      {/* Diffs */}
                      {parsedDiff.length > 0 ? (
                        <div className="gateDiffSection">
                          {parsedDiff.map((file) => (
                            <div key={file.path} className="diffFileContainer">
                              <DiffHeader path={file.path} added={file.added} removed={file.removed} />
                              <DiffRows rows={file.rows} />
                            </div>
                          ))}
                        </div>
                      ) : (
                        <div className="emptyIntercom">
                          <span>No source diff submitted yet. Once the agent finishes edits, the code diff will appear here.</span>
                        </div>
                      )}

                      {/* Approval buttons */}
                      <div className="gateButtons">
                        <button className="gateApproveBtn" onClick={() => void handleApprove(activeIssue.id)}>
                          <Check size={13} />
                          Approve & Merge
                        </button>
                        <button
                          className="gateRejectBtn"
                          onClick={() => setShowRejectBox((v) => !v)}
                        >
                          Request changes
                        </button>
                      </div>

                      {showRejectBox ? (
                        <div className="gateFeedbackBox">
                          <input
                            type="text"
                            placeholder="Explain what needs to be changed..."
                            value={rejectFeedback}
                            onChange={(e) => setRejectFeedback(e.target.value)}
                          />
                          <button className="gateRejectBtn" onClick={() => void handleReject(activeIssue.id)}>
                            Submit
                          </button>
                        </div>
                      ) : null}
                    </div>
                  </div>
                )}
              </div>

              {/* Right Meta Sidebar */}
              <aside className="workspaceSidebar scroll">
                {/* Section A: Execution Runs History */}
                <div className="sidebarCard">
                  <div className="sidebarCardHead">
                    <div style={{ display: "flex", alignItems: "center", gap: "5px" }}>
                      <Cpu size={12} style={{ color: "var(--accent)" }} />
                      <span>Execution Runs</span>
                    </div>
                    <span className="sidebarChip">
                      {(activeIssue.runs?.length || (activeIssue.active_run ? 1 : 0))} runs
                    </span>
                  </div>

                  <div className="runsHistoryList">
                    {(activeIssue.runs && activeIssue.runs.length > 0
                      ? activeIssue.runs
                      : activeIssue.active_run
                      ? [activeIssue.active_run]
                      : []
                    ).map((run) => (
                      <div key={run.id} className="runHistoryItem">
                        <div className="runHistoryTop">
                          <span className={`runStatusDot ${run.status}`} />
                          <span className="runHistoryId">#{run.id}</span>
                          <span className="runHistoryAgent">{run.agent_name}</span>
                        </div>
                        <div className="runHistoryBottom">
                          <span className="runHistoryPhase">{run.phase || "Work"}</span>
                          <span className="runHistorySteps">
                            {run.current_step || run.step_count || 1} steps
                          </span>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>

                {/* Section B: Collaborators & Agents */}
                <div className="sidebarCard">
                  <div className="sidebarCardHead">
                    <div style={{ display: "flex", alignItems: "center", gap: "5px" }}>
                      <Users size={12} style={{ color: "var(--icon-blue)" }} />
                      <span>Team Roster</span>
                    </div>
                    <span className="sidebarChip">{(activeIssue.collaborators || []).length}</span>
                  </div>

                  <div style={{ display: "flex", flexDirection: "column", gap: "6px" }}>
                    {(activeIssue.collaborators || []).map((collab) => (
                      <div key={collab.user_id} className="collabCard" style={{ padding: "6px 8px" }}>
                        <div className="collabCardTop">
                          <div className="collabIdentity">
                            <span className="userAvatar" style={{ width: "18px", height: "18px", fontSize: "10px" }}>
                              {collab.user_name[0]}
                            </span>
                            <span className="collabUserName" style={{ fontSize: "11px" }}>{collab.user_name}</span>
                          </div>
                          {collab.agent_name ? (
                            <AgentRunnerBadge agentName={collab.agent_name} />
                          ) : (
                            <span className="teammateBadge" style={{ fontSize: "9px" }}>Teammate</span>
                          )}
                        </div>
                        <div className="collabStatusRow">
                          <span className={`liveDot ${collab.status === "working" ? "pulse" : ""}`} />
                          <span className="activityText" style={{ fontSize: "10px" }}>
                            {collab.current_activity || (collab.agent_name ? `Paired with ${collab.agent_name}` : "Teammate in workspace")}
                          </span>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>

                {/* Section C: Optimistic File Leases (Locks) */}
                <div className="sidebarCard">
                  <div className="sidebarCardHead">
                    <div style={{ display: "flex", alignItems: "center", gap: "5px" }}>
                      <Lock size={12} style={{ color: "var(--accent)" }} />
                      <span>Optimistic File Leases</span>
                    </div>
                    <span className="sidebarChip">{Object.keys(activeIssue.active_leases || {}).length}</span>
                  </div>

                  <div className="leaseList">
                    {Object.entries(activeIssue.active_leases || {}).map(([file, holderAgent]) => (
                      <div key={file} className="leaseItem" style={{ padding: "4px 6px" }}>
                        <div className="leaseInfo" style={{ gap: "4px" }}>
                          <FileCode size={11} />
                          <span className="leaseFile" style={{ fontSize: "10px" }}>
                            {file} <span style={{ opacity: 0.6, fontSize: "9px" }}>({holderAgent})</span>
                          </span>
                        </div>
                        <button
                          className="releaseBtn"
                          onClick={() => void handleReleaseLease(activeIssue.id, file)}
                          title="Release lease"
                          style={{ fontSize: "9px", padding: "1px 5px" }}
                        >
                          Release
                        </button>
                      </div>
                    ))}

                    <div className="claimLeaseRow" style={{ marginTop: "4px" }}>
                      <input
                        type="text"
                        placeholder="Lock file path..."
                        value={leasePathInput}
                        onChange={(e) => setLeasePathInput(e.target.value)}
                        style={{ fontSize: "10.5px", padding: "3px 6px" }}
                        onKeyDown={(e) => {
                          if (e.key === "Enter") {
                            e.preventDefault();
                            void handleClaimLease(activeIssue.id);
                          }
                        }}
                      />
                      <button className="claimBtn" style={{ fontSize: "10px", padding: "3px 8px" }} onClick={() => void handleClaimLease(activeIssue.id)}>
                        Lock
                      </button>
                    </div>
                  </div>
                </div>

                {/* Section D: Verification Gate Criteria */}
                {activeIssue.verification_command && (
                  <div className="sidebarCard">
                    <div className="sidebarCardHead">
                      <div style={{ display: "flex", alignItems: "center", gap: "5px" }}>
                        <ShieldCheck size={12} style={{ color: "var(--ok)" }} />
                        <span>Review Criteria</span>
                      </div>
                      <span className={`gateBadge ${activeIssue.verification_passed ? "pass" : "fail"}`} style={{ fontSize: "9px", padding: "1px 5px" }}>
                        {activeIssue.verification_passed ? "PASS" : "PENDING"}
                      </span>
                    </div>
                    <code style={{ fontSize: "10px", fontFamily: "var(--font-mono)", color: "var(--ink-muted)", wordBreak: "break-all" }}>
                      {activeIssue.verification_command}
                    </code>
                  </div>
                )}

                {/* Section E: Local Agent Bridge CLI */}
                <div className="bridgeConnectionBox">
                  <div className="bridgeBoxHead">
                    <div className="bridgeBoxTitle" style={{ fontSize: "11px" }}>
                      <Terminal size={11} style={{ color: "var(--accent)" }} />
                      <span>Local Agent CLI</span>
                    </div>
                    <span className="bridgeStatusChip" style={{ fontSize: "9px" }}>Connected</span>
                  </div>
                  <div className="bridgeCommandSnippet">
                    <code>python -m tura_code.squads.bridge pulse --issue {activeIssue.id} --user "{connectUserName || "Developer"}" --agent "{connectAgentName || "Claude Code"}" --activity "Working on implementation"</code>
                    <button
                      className="copySnippetBtn"
                      onClick={() => {
                        void navigator.clipboard.writeText(
                          `python -m tura_code.squads.bridge pulse --issue ${activeIssue.id} --user "${connectUserName || "Developer"}" --agent "${connectAgentName || "Claude Code"}" --activity "Working on implementation"`
                        );
                        setCopiedBridge(true);
                        setTimeout(() => setCopiedBridge(false), 2000);
                      }}
                      title="Copy CLI bridge command"
                    >
                      {copiedBridge ? (
                        <>
                          <Check size={9} /> Done
                        </>
                      ) : (
                        <>
                          <Copy size={9} /> Copy
                        </>
                      )}
                    </button>
                  </div>
                </div>
              </aside>
            </div>
          </aside>
        </div>
      ) : null}




      {/* Multica-Styled Clean Create Issue Modal */}
      {showNewIssue ? (
        <div className="multicaModalBackdrop" onClick={() => setShowNewIssue(false)}>
          <div className="multicaDialog" onClick={(e) => e.stopPropagation()}>
            <div className="multicaDialogHead">
              <h3>Create Collaborative Issue</h3>
              <button className="iconButton" onClick={() => setShowNewIssue(false)}>
                <X size={15} />
              </button>
            </div>

            <form onSubmit={handleCreateIssueSubmit}>
              <div className="multicaDialogBody">
                <input
                  type="text"
                  className="multicaDialogInput"
                  placeholder="Issue title"
                  value={newTitle}
                  onChange={(e) => setNewTitle(e.target.value)}
                  autoFocus
                  required
                />

                <textarea
                  className="multicaDialogTextarea"
                  rows={3}
                  placeholder="Description or specifications for the team and agents..."
                  value={newDescription}
                  onChange={(e) => setNewDescription(e.target.value)}
                />

                {/* Team Collaborators Multi-Select */}
                <div className="formField">
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 6 }}>
                    <label style={{ margin: 0 }}>Assign Teammates</label>
                    <button
                      type="button"
                      style={{
                        background: "none",
                        border: "none",
                        color: "var(--accent)",
                        cursor: "pointer",
                        fontSize: "11px",
                        display: "inline-flex",
                        alignItems: "center",
                        gap: 4,
                        padding: 0,
                      }}
                      onClick={() => {
                        setTeamModalTab("connect");
                        setShowTeamModal(true);
                      }}
                    >
                      <Terminal size={11} />
                      Connect Agent CLI
                    </button>
                  </div>
                  <div className="collabSelectGrid">
                    {teamMembers.map((member) => {
                      const isSelected = selectedCollaboratorIds.includes(member.user_id);
                      return (
                        <div
                          key={member.user_id}
                          className={`collabOptionCard ${isSelected ? "selected" : ""}`}
                          onClick={() => {
                            setSelectedCollaboratorIds((prev) =>
                              isSelected ? prev.filter((id) => id !== member.user_id) : [...prev, member.user_id]
                            );
                          }}
                        >
                          <div className="collabOptionCheck">
                            {isSelected ? <Check size={12} /> : null}
                          </div>
                          <span className="collabOptionAvatar">
                            {member.user_name[0]?.toUpperCase() || "U"}
                          </span>
                          <span className="collabOptionName">{member.user_name}</span>
                          <button
                            type="button"
                            className="collabRemoveBtn"
                            title={`Remove ${member.user_name} from squad`}
                            onClick={(e) => {
                              e.stopPropagation();
                              void handleDeleteTeammate(member.user_id);
                            }}
                          >
                            <X size={11} />
                          </button>
                        </div>
                      );
                    })}

                    {/* Inline Add Teammate Card */}
                    {showAddTeammate ? (
                      <div className="addTeammateInlineCard" onClick={(e) => e.stopPropagation()}>
                        <input
                          type="text"
                          placeholder="Teammate name..."
                          value={newTeammateName}
                          onChange={(e) => setNewTeammateName(e.target.value)}
                          onKeyDown={(e) => {
                            if (e.key === "Enter") {
                              e.preventDefault();
                              void handleAddTeammate();
                            } else if (e.key === "Escape") {
                              setShowAddTeammate(false);
                            }
                          }}
                          autoFocus
                        />
                        <div className="addTeammateActions">
                          <button
                            type="button"
                            className="cancelAddBtn"
                            onClick={() => setShowAddTeammate(false)}
                          >
                            Cancel
                          </button>
                          <button
                            type="button"
                            className="addBtn"
                            disabled={!newTeammateName.trim() || addingTeammate}
                            onClick={() => void handleAddTeammate()}
                          >
                            Add
                          </button>
                        </div>
                      </div>
                    ) : (
                      <button
                        type="button"
                        className="addTeammateTriggerCard"
                        onClick={() => setShowAddTeammate(true)}
                      >
                        <Plus size={13} />
                        <span>Add Teammate</span>
                      </button>
                    )}
                  </div>
                </div>

                <div className="multicaFormRow">
                  <div className="formField">
                    <label>Workspace Scope</label>
                    <select
                      value={newScope}
                      onChange={(e) => setNewScope(e.target.value as WorkspaceScope)}
                    >
                      <option value="shared">Shared (Team Repo)</option>
                      <option value="personal">Personal (Scratch Branch)</option>
                    </select>
                  </div>

                  <div className="formField">
                    <label>Priority</label>
                    <select
                      value={newPriority}
                      onChange={(e) => setNewPriority(e.target.value as IssuePriority)}
                    >
                      <option value="low">Low</option>
                      <option value="medium">Medium</option>
                      <option value="high">High</option>
                      <option value="urgent">Urgent</option>
                    </select>
                  </div>
                </div>

                <div className="formField">
                  <label>Verification Command (CI / Test Suite)</label>
                  <input
                    type="text"
                    value={newVerificationCmd}
                    onChange={(e) => setNewVerificationCmd(e.target.value)}
                    placeholder="pytest -q tests/test_auth.py or npm test"
                  />
                </div>
              </div>

              <div className="multicaDialogFoot">
                <button
                  type="button"
                  className="dialogCancelBtn"
                  onClick={() => setShowNewIssue(false)}
                >
                  Cancel
                </button>
                <button type="submit" className="dialogSubmitBtn">
                  Create issue
                </button>
              </div>
            </form>
          </div>
        </div>
      ) : null}

      {/* Unified Team & Agent Workspace Modal */}
      {showTeamModal ? (
        <div className="multicaDialogBackdrop" onClick={() => setShowTeamModal(false)}>
          <div
            className="multicaDialog mediumDialog"
            onClick={(e) => e.stopPropagation()}
            role="dialog"
            aria-label="Team & Agent Workspace"
          >
            <div className="multicaDialogHead">
              <div className="modalHeadTitleRow">
                <div className="modalHeadIconWrap">
                  {teamModalTab === "connect" ? <Terminal size={16} /> : <Users size={16} />}
                </div>
                <div>
                  <h3>Team & Agent Workspace</h3>
                  <p className="modalHeadSubtitle">
                    Connect local coding agents (Claude Code, Antigravity, Codex) & manage teammates
                  </p>
                </div>
              </div>
              <button
                type="button"
                className="dialogCloseBtn"
                onClick={() => setShowTeamModal(false)}
                aria-label="Close"
              >
                <X size={15} />
              </button>
            </div>

            {/* Segmented Tab Bar */}
            <div className="modalSegmentedTabs">
              <button
                type="button"
                className={`modalSegmentedTab ${teamModalTab === "connect" ? "active" : ""}`}
                onClick={() => setTeamModalTab("connect")}
              >
                <Terminal size={12} />
                <span>Connect Coding Agent</span>
                <span
                  style={{
                    background: "var(--accent-soft)",
                    color: "var(--accent)",
                    border: "1px solid var(--accent-line)",
                    fontSize: "9.5px",
                    fontWeight: 600,
                    padding: "1px 5px",
                    borderRadius: "4px",
                  }}
                >
                  Recommended
                </span>
              </button>
              <button
                type="button"
                className={`modalSegmentedTab ${teamModalTab === "roster" ? "active" : ""}`}
                onClick={() => setTeamModalTab("roster")}
              >
                <Users size={12} />
                <span>Team Members ({teamMembers.length})</span>
              </button>
            </div>

            <div className="multicaDialogBody">
              {teamModalTab === "connect" ? (
                <>
                  <p style={{ margin: 0, fontSize: "12.5px", color: "var(--ink-muted)", lineHeight: 1.5 }}>
                    Give this command to your coding agent (<strong>Claude Code</strong>, <strong>Antigravity</strong>, <strong>Codex</strong>) or run it in your project terminal. It links your agent directly to this shared workspace, registers you as a teammate, and streams your activity live in real time.
                  </p>

                  {/* Agent Selection Tabs */}
                  <div className="connectAgentTabs">
                    {[
                      { id: "Claude Code", label: "Claude Code" },
                      { id: "Antigravity", label: "Antigravity" },
                      { id: "Codex", label: "Codex" },
                      { id: "Cursor", label: "Cursor" },
                    ].map((t) => (
                      <button
                        key={t.id}
                        type="button"
                        className={`connectAgentTab ${connectAgentName === t.id ? "active" : ""}`}
                        onClick={() => setConnectAgentName(t.id)}
                      >
                        {t.label}
                      </button>
                    ))}
                  </div>

                  {/* Developer Name Input */}
                  <div className="formField" style={{ marginTop: 2 }}>
                    <label style={{ fontSize: "11.5px", fontWeight: 600, color: "var(--ink-muted)", marginBottom: 4 }}>
                      Developer Name
                    </label>
                    <input
                      type="text"
                      className="multicaDialogInput"
                      placeholder="Your name (e.g. Nitin, Chitranjan, Ashish)"
                      value={connectUserName}
                      onChange={(e) => setConnectUserName(e.target.value)}
                    />
                  </div>

                  {/* Generated Connection Command */}
                  <div className="connectAgentBox">
                    <div className="connectAgentBoxTitle">
                      <Radio size={13} style={{ color: "var(--accent)" }} />
                      <span>1. Instant Connect Command</span>
                    </div>
                    <div className="connectSnippetRow">
                      <code>python -m tura_code.squads.bridge connect --user "{connectUserName || "Developer"}" --agent "{connectAgentName}"</code>
                      <button
                        type="button"
                        className="copyBtn"
                        onClick={() => {
                          void navigator.clipboard.writeText(`python -m tura_code.squads.bridge connect --user "${connectUserName || "Developer"}" --agent "${connectAgentName}"`);
                          setCopiedCmdId("connect");
                          setTimeout(() => setCopiedCmdId(null), 2000);
                        }}
                      >
                        {copiedCmdId === "connect" ? <Check size={12} style={{ color: "var(--ok)" }} /> : <Copy size={12} />}
                        <span>{copiedCmdId === "connect" ? "Copied" : "Copy"}</span>
                      </button>
                    </div>
                  </div>

                  {/* Active Issue Pulse Command */}
                  {activeIssue ? (
                    <div className="connectAgentBox">
                      <div className="connectAgentBoxTitle">
                        <Radio size={13} style={{ color: "#38bdf8" }} />
                        <span>2. Stream Progress on Active Issue ({activeIssue.id})</span>
                      </div>
                      <div className="connectSnippetRow">
                        <code>python -m tura_code.squads.bridge pulse --issue {activeIssue.id} --user "{connectUserName || "Developer"}" --agent "{connectAgentName}" --activity "Working on implementation"</code>
                        <button
                          type="button"
                          className="copyBtn"
                          onClick={() => {
                            void navigator.clipboard.writeText(`python -m tura_code.squads.bridge pulse --issue ${activeIssue.id} --user "${connectUserName || "Developer"}" --agent "${connectAgentName}" --activity "Working on implementation"`);
                            setCopiedCmdId("pulse");
                            setTimeout(() => setCopiedCmdId(null), 2000);
                          }}
                        >
                          {copiedCmdId === "pulse" ? <Check size={12} style={{ color: "var(--ok)" }} /> : <Copy size={12} />}
                          <span>{copiedCmdId === "pulse" ? "Copied" : "Copy"}</span>
                        </button>
                      </div>
                    </div>
                  ) : null}

                  {/* Direct cURL fallback */}
                  <div className="connectAgentBox">
                    <div className="connectAgentBoxTitle">
                      <Globe size={13} style={{ color: "var(--ink-muted)" }} />
                      <span>Direct cURL HTTP API</span>
                    </div>
                    <div className="connectSnippetRow">
                      <code>curl -s -X POST http://localhost:8787/api/squads/{squadId}/connect -H "Content-Type: application/json" -d '{JSON.stringify({ user_name: connectUserName || "Developer", agent_name: connectAgentName })}'</code>
                      <button
                        type="button"
                        className="copyBtn"
                        onClick={() => {
                          void navigator.clipboard.writeText(`curl -s -X POST http://localhost:8787/api/squads/${squadId}/connect -H "Content-Type: application/json" -d '{"user_name":"${connectUserName || "Developer"}","agent_name":"${connectAgentName}"}'`);
                          setCopiedCmdId("curl");
                          setTimeout(() => setCopiedCmdId(null), 2000);
                        }}
                      >
                        {copiedCmdId === "curl" ? <Check size={12} style={{ color: "var(--ok)" }} /> : <Copy size={12} />}
                        <span>{copiedCmdId === "curl" ? "Copied" : "Copy"}</span>
                      </button>
                    </div>
                  </div>
                </>
              ) : (
                <>
                  <p style={{ margin: 0, fontSize: "12.5px", color: "var(--ink-muted)", lineHeight: 1.5 }}>
                    Teammates currently registered in this shared workspace. You can remove teammates or manually add someone by name.
                  </p>

                  <div className="teammateRosterList">
                    {teamMembers.map((m) => (
                      <div key={m.user_id} className="teammateRosterRow">
                        <div className="teammateRosterLeft">
                          <span className="teammateAvatarBadge">
                            {m.user_name[0]?.toUpperCase() || "U"}
                          </span>
                          <div>
                            <div className="teammateRosterName">{m.user_name}</div>
                            <div className="teammateRosterSub">
                              {m.agent_name ? (
                                <>
                                  <Cpu size={11} style={{ color: "var(--accent)" }} />
                                  <span>Paired with {m.agent_name}</span>
                                </>
                              ) : (
                                <span>{m.current_activity || "Teammate in workspace"}</span>
                              )}
                            </div>
                          </div>
                        </div>
                        <button
                          type="button"
                          className="deleteTeammateBtn"
                          title={`Remove ${m.user_name} from squad`}
                          onClick={() => void handleDeleteTeammate(m.user_id)}
                        >
                          <Trash2 size={13} />
                        </button>
                      </div>
                    ))}
                  </div>

                  {/* Add Teammate Manually Form */}
                  <form
                    onSubmit={(e) => {
                      e.preventDefault();
                      void handleAddTeammate();
                    }}
                    style={{ marginTop: 6, borderTop: "1px solid var(--line)", paddingTop: 14 }}
                  >
                    <label style={{ fontSize: "11.5px", fontWeight: 600, color: "var(--ink)", display: "block", marginBottom: 6 }}>
                      Add Teammate Manually
                    </label>
                    <div style={{ display: "flex", gap: 8 }}>
                      <input
                        type="text"
                        className="multicaDialogInput"
                        placeholder="Teammate name (e.g. Rahul)..."
                        value={newTeammateName}
                        onChange={(e) => setNewTeammateName(e.target.value)}
                        style={{ flex: 1, fontSize: "12.5px" }}
                      />
                      <button
                        type="submit"
                        className="dialogSubmitBtn"
                        disabled={!newTeammateName.trim() || addingTeammate}
                        style={{ whiteSpace: "nowrap" }}
                      >
                        + Add Teammate
                      </button>
                    </div>
                  </form>
                </>
              )}
            </div>

            <div className="multicaDialogFoot">
              <button
                type="button"
                className="dialogSubmitBtn"
                onClick={() => setShowTeamModal(false)}
              >
                Done
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
