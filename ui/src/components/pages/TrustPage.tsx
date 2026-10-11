import {
  AlertTriangle,
  CheckCircle2,
  Lock,
  RotateCcw,
  Shield,
  ShieldCheck,
  Terminal,
} from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { api } from "../../lib/api.ts";
import type { TrustEntry } from "../../lib/types.ts";

const SAMPLE_COMMANDS = [
  { cmd: "git status", desc: "Read workspace Git state" },
  { cmd: "pytest -q tests/test_auth.py", desc: "Run verification test suite" },
  { cmd: "npm run build", desc: "Compile frontend assets" },
  { cmd: "git push origin main", desc: "Network publish to remote repo" },
  { cmd: "rm -rf /tmp/scratch", desc: "Destructive file removal" },
];

export function TrustPage() {
  const [entries, setEntries] = useState<TrustEntry[] | null>(null);
  const [promoteAfter, setPromoteAfter] = useState(3);
  const [command, setCommand] = useState("");
  const [verdict, setVerdict] = useState<{ tier: string; key: string; reasons: string[] } | null>(null);
  const [loadingVerdict, setLoadingVerdict] = useState(false);

  const load = useCallback(
    () =>
      api.trust().then((d) => {
        setEntries(d.entries);
        setPromoteAfter(d.promote_after);
      }),
    [],
  );

  useEffect(() => {
    void load();
  }, [load]);

  const handleClassify = (cmdToTest: string) => {
    if (!cmdToTest.trim()) return;
    setLoadingVerdict(true);
    api
      .classify(cmdToTest.trim())
      .then(setVerdict)
      .finally(() => setLoadingVerdict(false));
  };

  const promotedCount = entries?.filter((e) => e.promoted).length ?? 0;

  return (
    <div className="multicaShell" style={{ padding: "20px 24px", overflowY: "auto" }}>
      {/* Header */}
      <div className="flowHeader">
        <div>
          <div className="flowEyebrow">
            <Shield size={13} style={{ color: "var(--accent)" }} />
            <span>SECURITY BOUNDARY & TRUST TIERS</span>
          </div>
          <h1 className="flowTitle">Approvals & Command Trust</h1>
          <p className="flowLede">
            Deterministic security policy governing what coding agents may run automatically vs when they must ask for your approval.
          </p>
        </div>
      </div>

      {/* 3 Security Tier Visual Cards */}
      <div className="trustTiersGrid">
        <div className="trustTierCard tierRead">
          <div className="tierBadge">
            <CheckCircle2 size={13} style={{ color: "var(--ok)" }} />
            <span>TIER 1: READ-ONLY</span>
          </div>
          <h3>Always Auto-Runs</h3>
          <p>Commands that only read or inspect files run instantly without interrupting you.</p>
          <div className="tierExamples">
            <code>git status</code> <code>git diff</code> <code>ls</code> <code>grep</code> <code>cat</code>
          </div>
        </div>

        <div className="trustTierCard tierVerify">
          <div className="tierBadge">
            <ShieldCheck size={13} style={{ color: "var(--accent)" }} />
            <span>TIER 2: WORKSPACE CHECKS</span>
          </div>
          <h3>Auto-Promotes After {promoteAfter}x</h3>
          <p>
            Builds and test scripts within your workspace ask first. Approve {promoteAfter} times in a row and root trusts them automatically.
          </p>
          <div className="tierExamples">
            <code>pytest -q</code> <code>npm test</code> <code>cargo build</code>
          </div>
        </div>

        <div className="trustTierCard tierDanger">
          <div className="tierBadge">
            <AlertTriangle size={13} style={{ color: "var(--err)" }} />
            <span>TIER 3: SENSITIVE & EXTERNAL</span>
          </div>
          <h3>Always Asks (Never Promoted)</h3>
          <p>Access outside workspace, destructive removals, or network push always requires explicit confirmation.</p>
          <div className="tierExamples">
            <code>git push</code> <code>rm -rf</code> <code>curl external</code>
          </div>
        </div>
      </div>

      {/* Interactive Command Safety Simulator */}
      <div className="trustSimCard">
        <div className="simHead">
          <div className="simTitle">
            <Terminal size={14} style={{ color: "var(--icon-blue)" }} />
            <span>Command Safety Simulator</span>
          </div>
          <span className="simTip">Test any terminal command to preview its approval tier</span>
        </div>

        <form
          className="simInputRow"
          onSubmit={(e) => {
            e.preventDefault();
            handleClassify(command);
          }}
        >
          <input
            className="simInput"
            placeholder="Type a command (e.g. npm test or git push)..."
            value={command}
            onChange={(e) => setCommand(e.target.value)}
          />
          <button type="submit" className="simCheckBtn" disabled={loadingVerdict || !command.trim()}>
            {loadingVerdict ? "Evaluating..." : "Check Safety"}
          </button>
        </form>

        {/* Quick Sample Chips */}
        <div className="simSampleRow">
          <span className="sampleLabel">Try sample:</span>
          {SAMPLE_COMMANDS.map((sample) => (
            <button
              key={sample.cmd}
              type="button"
              className="sampleChip"
              onClick={() => {
                setCommand(sample.cmd);
                handleClassify(sample.cmd);
              }}
            >
              <code>{sample.cmd}</code>
            </button>
          ))}
        </div>

        {/* Verdict Result */}
        {verdict && (
          <div className={`verdictResultCard ${verdict.tier}`}>
            <div className="verdictHead">
              <span className="verdictTierBadge">
                {verdict.tier === "read" && "🟢 TIER 1: READ-ONLY (Auto-runs)"}
                {verdict.tier === "verify" && "🟡 TIER 2: WORKSPACE CHECK (Promotable)"}
                {verdict.tier === "needs_trust" && "🔴 TIER 3: REQUIRES APPROVAL (Will ask)"}
              </span>
              <span className="verdictKey">Class: {verdict.key.replace(/^run command:/, "")}</span>
            </div>
            <p className="verdictDesc">
              {verdict.tier === "read" && "This command is classified as read-only and will execute silently without human interruption."}
              {verdict.tier === "verify" && `This command is a project check. It runs automatically in accept-edits mode or will be trusted after ${promoteAfter} approvals.`}
              {verdict.tier === "needs_trust" && "This command can modify repository state or reaches outside sandbox. An approval dialog will be shown."}
            </p>
            {verdict.reasons.length > 0 && (
              <div className="verdictReasons">
                <span>Evaluation reasons: </span>
                {verdict.reasons.join(", ")}
              </div>
            )}
          </div>
        )}
      </div>

      {/* Trusted Commands Ledger */}
      <div className="trustLedgerSection">
        <div className="ledgerHeader">
          <div className="ledgerTitle">
            <Lock size={14} style={{ color: "var(--accent)" }} />
            <span>Trusted Commands Ledger ({entries?.length ?? 0})</span>
          </div>
          <span className="ledgerStats">
            {promotedCount} auto-trusted · {promoteAfter} consecutive approvals needed to promote
          </span>
        </div>

        {entries && entries.length > 0 ? (
          <div className="ledgerList">
            {entries.map((entry) => (
              <div key={entry.key} className="ledgerRow">
                <div className="ledgerStatus">
                  {entry.promoted ? (
                    <span className="trustedBadge">
                      <ShieldCheck size={12} /> Trusted
                    </span>
                  ) : (
                    <span className="pendingBadge">
                      {entry.approvals}/{promoteAfter} Approvals
                    </span>
                  )}
                </div>

                <div className="ledgerCommand">
                  <code>{entry.key.replace(/^run command:/, "")}</code>
                  <span className="ledgerNotes">
                    {entry.promoted
                      ? "Runs automatically without prompting"
                      : `Approved ${entry.approvals}x in a row${entry.rejections ? ` · rejected ${entry.rejections}x` : ""}`}
                  </span>
                </div>

                <button
                  className="revokeBtn"
                  onClick={() => api.revokeTrust(entry.key).then(load)}
                  title="Revoke trust and ask again"
                >
                  <RotateCcw size={11} />
                  {entry.promoted ? "Revoke Trust" : "Forget"}
                </button>
              </div>
            ))}
          </div>
        ) : (
          <div className="ledgerEmpty">
            <ShieldCheck size={20} style={{ color: "var(--ok)", marginBottom: 6 }} />
            <p>No customized trust decisions yet. Standard safe policies are active.</p>
            <span>As your team approves tool commands in sessions, approved patterns will appear here.</span>
          </div>
        )}
      </div>
    </div>
  );
}
