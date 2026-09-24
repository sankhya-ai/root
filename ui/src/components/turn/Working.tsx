import { useEffect, useState } from "react";

function elapsed(seconds: number): string {
  if (seconds < 60) return `${seconds}s`;
  return `${Math.floor(seconds / 60)}m ${String(seconds % 60).padStart(2, "0")}s`;
}

/** The breathing orb and the time this turn has taken so far. */
export function Working({ since, label }: { since: number; label: string }) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, []);
  return (
    <div className="working" role="status">
      <span className="orb" aria-hidden="true" />
      <span>{label}</span>
      <span className="elapsed">{elapsed(Math.max(0, Math.round((now - since) / 1000)))}</span>
    </div>
  );
}
