import { ArrowUp, Folder, FolderGit2, X } from "lucide-react";
import { useEffect, useState } from "react";

import { api } from "../lib/api.ts";
import { useEscape } from "../lib/useEscape.ts";

export function NewSessionDialog({ recent, onClose, onCreate }: { recent: string[]; onClose: () => void; onCreate: (workspace: string) => Promise<void> }) {
  useEscape(onClose);
  const [path, setPath] = useState(recent[0] ?? "");
  const [listing, setListing] = useState<Awaited<ReturnType<typeof api.dirs>> | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const browse = (target?: string) => {
    api.dirs(target).then(
      (d) => {
        setListing(d);
        setPath(d.path);
        setError("");
      },
      (e) => setError(String(e.message)),
    );
  };

  useEffect(() => browse(recent[0] || undefined), []); // eslint-disable-line react-hooks/exhaustive-deps

  const create = async (target: string) => {
    if (!target.trim()) return;
    setBusy(true);
    setError("");
    try {
      await onCreate(target.trim());
    } catch (e) {
      setError(String((e as Error).message));
      setBusy(false);
    }
  };

  return (
    <div className="backdrop" onMouseDown={onClose}>
      <div className="dialog" onMouseDown={(e) => e.stopPropagation()} role="dialog" aria-label="New session">
        <div className="dialogHead">
          <h2>New session</h2>
          <button className="iconButton" onClick={onClose} aria-label="Close">
            <X size={16} />
          </button>
        </div>
        <div className="dialogBody scroll">
          <div className="field">
            <label htmlFor="ws">Workspace folder</label>
            <form
              className="panelTools"
              style={{ marginBottom: 0 }}
              onSubmit={(e) => {
                e.preventDefault();
                browse(path);
              }}
            >
              <input id="ws" className="input mono" value={path} onChange={(e) => setPath(e.target.value)} placeholder="/path/to/project" />
              <button type="submit" className="button">
                Go
              </button>
            </form>
            <span className="help">The agent works inside this folder. Its AGENTS.md or CLAUDE.md is loaded as project instructions.</span>
          </div>
          {recent.length ? (
            <>
              <div className="pixelLabel" style={{ marginBottom: 6 }}>
                Recent
              </div>
              <div className="dirList" style={{ marginBottom: 14 }}>
                {recent.map((r) => (
                  <button key={r} className="dirRow" onClick={() => create(r)} disabled={busy}>
                    <FolderGit2 size={14} className="faint" /> <span className="mono small">{r}</span>
                  </button>
                ))}
              </div>
            </>
          ) : null}
          {listing ? (
            <>
              <div className="pixelLabel" style={{ marginBottom: 6 }}>
                Browse
              </div>
              <div className="dirList scroll">
                {listing.parent ? (
                  <button className="dirRow" onClick={() => browse(listing.parent!)}>
                    <ArrowUp size={14} className="faint" /> ..
                  </button>
                ) : null}
                {listing.entries.map((entry) => (
                  <button key={entry.path} className="dirRow" onClick={() => browse(entry.path)} onDoubleClick={() => create(entry.path)}>
                    {entry.git ? <FolderGit2 size={14} color="var(--tura-dot)" /> : <Folder size={14} className="faint" />} {entry.name}
                  </button>
                ))}
                {listing.entries.length === 0 ? <div className="dirRow faint">No subfolders</div> : null}
              </div>
            </>
          ) : null}
          {error ? <p className="small" style={{ color: "var(--err)" }}>{error}</p> : null}
        </div>
        <div className="dialogFoot">
          <button className="button" onClick={onClose}>
            Cancel
          </button>
          <button className="button primary" onClick={() => create(path)} disabled={busy || !path.trim()}>
            {busy ? "Starting…" : "Start session here"}
          </button>
        </div>
      </div>
    </div>
  );
}
