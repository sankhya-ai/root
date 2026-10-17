// Settings → Plugins: what root can do beyond its core tools, as one quiet
// list (after Codex): a row per plugin — icon, name, one line, and a switch or
// its connection state. A row opens to show what it gives the agent and, for a
// connection, how to connect it. The owner's MCP servers come last.

import { AlarmClock, Brain, ChevronDown, ChevronRight, FileText, GitMerge, Github, Globe, Mail, Plus, Search, Server, Terminal, Trash2 } from "lucide-react";
import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";

import { api } from "../../lib/api.ts";
import type { Connections, DeviceFlow, McpServerInfo, Plugin, PluginCatalog } from "../../lib/types.ts";
import { Group, Section, Switch } from "./controls.tsx";

const ICONS: Record<string, ReactNode> = {
  file: <FileText size={16} />,
  terminal: <Terminal size={16} />,
  github: <Github size={16} />,
  mail: <Mail size={16} />,
  search: <Search size={16} />,
  clock: <AlarmClock size={16} />,
  branch: <GitMerge size={16} />,
  globe: <Globe size={16} />,
  brain: <Brain size={16} />,
};

function PluginRow({ icon, name, summary, right, children }: { icon: ReactNode; name: string; summary: string; right: ReactNode; children?: ReactNode }) {
  const [open, setOpen] = useState(false);
  return (
    <div className={`pluginRow${open ? " open" : ""}`}>
      <div className="pluginHead">
        <button type="button" className="pluginMain" onClick={() => setOpen((v) => !v)} aria-expanded={open}>
          <span className="pluginIcon">{icon}</span>
          <span className="pluginText">
            <span className="pluginName">{name}</span>
            <span className="pluginSummary">{summary}</span>
          </span>
          {children ? open ? <ChevronDown size={14} className="faint" /> : <ChevronRight size={14} className="faint" /> : null}
        </button>
        <div className="pluginRight">{right}</div>
      </div>
      {open && children ? <div className="pluginBody">{children}</div> : null}
    </div>
  );
}

function Capabilities({ items }: { items: string[] }) {
  return (
    <div className="pluginCaps">
      {items.map((item) => (
        <span key={item} className="pluginCap">
          {item}
        </span>
      ))}
    </div>
  );
}

function GitHubDetails({ state, refresh }: { state: Connections["github"]; refresh: () => void }) {
  const [token, setToken] = useState("");
  const [device, setDevice] = useState<DeviceFlow | null>(null);
  const [error, setError] = useState("");
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);
  useEffect(() => () => (timer.current ? clearInterval(timer.current) : undefined), []);

  const signIn = async () => {
    setError("");
    try {
      const flow = await api.githubDevice();
      setDevice(flow);
      timer.current = setInterval(() => {
        api.githubDevicePoll(flow.device_code).then(
          (r) => {
            if (!r.pending) {
              if (timer.current) clearInterval(timer.current);
              setDevice(null);
              refresh();
            }
          },
          (e: Error) => {
            if (timer.current) clearInterval(timer.current);
            setDevice(null);
            setError(e.message);
          },
        );
      }, Math.max(flow.interval, 2) * 1000);
    } catch (e) {
      setError((e as Error).message);
    }
  };

  if (state.connected && state.source === "connected") {
    return (
      <p className="pluginNote">
        Connected as @{state.login} with a token root keeps.{" "}
        <button className="linkish" onClick={() => api.githubDisconnect().then(refresh)}>
          Disconnect
        </button>
      </p>
    );
  }
  return (
    <>
      {state.connected ? <p className="pluginNote">Using your {state.source} login. Connect a token below to use another account.</p> : null}
      <div className="settingsInline">
        <input className="input" type="password" autoComplete="off" placeholder="GitHub token with the repo scope" value={token} onChange={(e) => setToken(e.target.value)} />
        <button
          className="pill ink"
          disabled={!token.trim()}
          onClick={() =>
            api.githubToken(token.trim()).then(
              () => {
                setToken("");
                refresh();
              },
              (e: Error) => setError(e.message),
            )
          }
        >
          Connect
        </button>
        {state.device_flow ? (
          <button className="pill" disabled={!!device} onClick={() => void signIn()}>
            Sign in with GitHub
          </button>
        ) : null}
      </div>
      {device ? (
        <p className="pluginNote">
          Enter <strong className="mono">{device.user_code}</strong> at{" "}
          <a href={device.verification_uri} target="_blank" rel="noreferrer">
            {device.verification_uri}
          </a>
          ; this updates when you are done.
        </p>
      ) : null}
      {error ? <p className="pluginError">{error}</p> : null}
    </>
  );
}

function GmailDetails({ state, refresh }: { state: Connections["gmail"]; refresh: () => void }) {
  const [waiting, setWaiting] = useState(false);
  const [error, setError] = useState("");
  if (state.connected) {
    return (
      <p className="pluginNote">
        Connected as {state.email}.{" "}
        <button className="linkish" onClick={() => api.googleDisconnect().then(refresh)}>
          Disconnect
        </button>
      </p>
    );
  }
  if (!state.configured) return <p className="pluginNote">This install has no Google sign-in configured, so Gmail cannot be connected here.</p>;
  return (
    <>
      <button
        className="pill ink"
        disabled={waiting}
        onClick={() =>
          api.googleStart().then(
            ({ url }) => {
              window.open(url, "_blank", "noopener");
              setWaiting(true);
              let checks = 0;
              const timer = setInterval(() => {
                checks += 1;
                api.connections().then((c) => {
                  if (c.gmail.connected || checks > 90) {
                    clearInterval(timer);
                    setWaiting(false);
                    refresh();
                  }
                });
              }, 2000);
            },
            (e: Error) => setError(e.message),
          )
        }
      >
        {waiting ? "Waiting for Google…" : "Connect Gmail"}
      </button>
      {error ? <p className="pluginError">{error}</p> : null}
    </>
  );
}

function ToolboxDetails({ path }: { path: string }) {
  const [packages, setPackages] = useState<{ name: string; version: string }[] | null>(null);
  useEffect(() => {
    api.toolboxPackages().then((d) => setPackages(d.packages), () => setPackages([]));
  }, []);
  return (
    <>
      <p className="pluginNote">
        Packages root installed for tasks live here, not in your system or projects: <span className="mono">{path}</span>
      </p>
      {packages === null ? null : packages.length ? (
        <Capabilities items={packages.map((p) => `${p.name} ${p.version}`)} />
      ) : (
        <p className="pluginNote">Nothing installed yet — root installs on demand.</p>
      )}
    </>
  );
}

function McpForm({ onSaved, onCancel }: { onSaved: (servers: McpServerInfo[]) => void; onCancel: () => void }) {
  const [name, setName] = useState("");
  const [remote, setRemote] = useState(false);
  const [command, setCommand] = useState("");
  const [url, setUrl] = useState("");
  const [env, setEnv] = useState("");
  const [error, setError] = useState("");
  const save = () => {
    const words = command.trim().split(/\s+/).filter(Boolean);
    const vars = Object.fromEntries(
      env
        .split("\n")
        .map((line) => line.trim())
        .filter((line) => line.includes("="))
        .map((line) => [line.slice(0, line.indexOf("=")).trim(), line.slice(line.indexOf("=") + 1).trim()]),
    );
    api
      .saveMcp(name.trim(), remote ? { url: url.trim(), env: vars } : { command: words[0] ?? "", args: words.slice(1), env: vars })
      .then((r) => onSaved(r.mcp), (e: Error) => setError(e.message));
  };
  return (
    <div className="mcpForm">
      <div className="settingsInline">
        <input className="input" placeholder="Name, e.g. linear" value={name} onChange={(e) => setName(e.target.value)} />
        <div className="segmented">
          <button type="button" className={remote ? "" : "active"} onClick={() => setRemote(false)}>
            Local command
          </button>
          <button type="button" className={remote ? "active" : ""} onClick={() => setRemote(true)}>
            Remote URL
          </button>
        </div>
      </div>
      {remote ? (
        <input className="input mono" placeholder="https://mcp.example.com/sse" value={url} onChange={(e) => setUrl(e.target.value)} />
      ) : (
        <input className="input mono" placeholder="npx -y @modelcontextprotocol/server-github" value={command} onChange={(e) => setCommand(e.target.value)} />
      )}
      <textarea className="input mono" rows={2} placeholder={"Environment, one per line: TOKEN=…"} value={env} onChange={(e) => setEnv(e.target.value)} />
      {error ? <p className="pluginError">{error}</p> : null}
      <div className="mcpFormActions">
        <button className="pill" onClick={onCancel}>
          Cancel
        </button>
        <button className="pill ink" disabled={!name.trim() || !(remote ? url.trim() : command.trim())} onClick={save}>
          Add server
        </button>
      </div>
    </div>
  );
}

export function PluginsSection() {
  const [catalog, setCatalog] = useState<PluginCatalog | null>(null);
  const [connections, setConnections] = useState<Connections | null>(null);
  const [adding, setAdding] = useState(false);
  const [error, setError] = useState("");

  const refresh = useCallback(() => {
    api.plugins().then(setCatalog, (e: Error) => setError(e.message));
    api.connections().then(setConnections, () => undefined);
  }, []);
  useEffect(refresh, [refresh]);

  const toggle = (plugin: Plugin, enabled: boolean) => {
    setCatalog((c) => (c ? { ...c, plugins: c.plugins.map((p) => (p.id === plugin.id ? { ...p, enabled } : p)) } : c));
    api.switchPlugin(plugin.id, enabled).catch((e: Error) => {
      setError(e.message);
      refresh();
    });
  };

  const setMcp = (servers: McpServerInfo[]) => setCatalog((c) => (c ? { ...c, mcp: servers } : c));

  if (!catalog) return <Section title="Plugins">{error ? <p className="pluginError">{error}</p> : null}</Section>;
  const connectionPlugins = catalog.plugins.filter((p) => p.kind === "connection");
  const builtIn = catalog.plugins.filter((p) => p.kind === "built-in");

  const connectionState = (plugin: Plugin) => {
    const state = plugin.id === "github" ? connections?.github : connections?.gmail;
    return state?.connected ? (
      <span className="pluginStatus on">{plugin.id === "github" ? (state as Connections["github"]).login ? `@${(state as Connections["github"]).login}` : "Connected" : (state as Connections["gmail"]).email || "Connected"}</span>
    ) : (
      <span className="pluginStatus">Not connected</span>
    );
  };

  return (
    <Section title="Plugins" lede="What root can do beyond reading and editing code. Switch off what you don't use: root then gets none of its tools.">
      <Group title="Connections">
        {connectionPlugins.map((plugin) => (
          <PluginRow
            key={plugin.id}
            icon={ICONS[plugin.icon]}
            name={plugin.name}
            summary={plugin.summary}
            right={
              <>
                {connectionState(plugin)}
                <Switch checked={plugin.enabled} label={`${plugin.name} on`} onChange={(v) => toggle(plugin, v)} />
              </>
            }
          >
            <Capabilities items={plugin.capabilities} />
            {connections ? (
              plugin.id === "github" ? (
                <GitHubDetails state={connections.github} refresh={refresh} />
              ) : (
                <GmailDetails state={connections.gmail} refresh={refresh} />
              )
            ) : null}
          </PluginRow>
        ))}
      </Group>

      <Group title="Built in">
        {builtIn.map((plugin) => (
          <PluginRow key={plugin.id} icon={ICONS[plugin.icon]} name={plugin.name} summary={plugin.summary} right={<Switch checked={plugin.enabled} label={`${plugin.name} on`} onChange={(v) => toggle(plugin, v)} />}>
            <Capabilities items={plugin.capabilities} />
            {plugin.id === "toolbox" ? <ToolboxDetails path={catalog.toolbox.path} /> : null}
          </PluginRow>
        ))}
      </Group>

      <Group
        title="MCP servers"
        action={
          adding ? null : (
            <button className="pill" onClick={() => setAdding(true)}>
              <Plus size={13} /> Add server
            </button>
          )
        }
      >
        {catalog.mcp.map((server) => (
          <PluginRow
            key={server.name}
            icon={<Server size={16} />}
            name={server.name}
            summary={server.url || [server.command, ...server.args].join(" ")}
            right={
              <>
                <button className="iconButton" title={`Remove ${server.name}`} onClick={() => api.deleteMcp(server.name).then((r) => setMcp(r.mcp))}>
                  <Trash2 size={14} />
                </button>
                <Switch
                  checked={server.enabled}
                  label={`${server.name} on`}
                  onChange={(enabled) =>
                    api
                      .saveMcp(server.name, server.url ? { url: server.url, enabled } : { command: server.command, args: server.args, enabled })
                      .then((r) => setMcp(r.mcp), (e: Error) => setError(e.message))
                  }
                />
              </>
            }
          >
            {server.env.length ? <p className="pluginNote">Environment: {server.env.join(", ")} (values stay on this machine)</p> : <p className="pluginNote">No environment variables.</p>}
          </PluginRow>
        ))}
        {adding ? (
          <McpForm
            onSaved={(servers) => {
              setMcp(servers);
              setAdding(false);
            }}
            onCancel={() => setAdding(false)}
          />
        ) : catalog.mcp.length === 0 ? (
          <div className="pluginEmpty">Connect any Model Context Protocol server — Linear, Sentry, a database — and its tools join root's. Changes apply from the next message.</div>
        ) : null}
      </Group>
      {error ? <p className="pluginError">{error}</p> : null}
    </Section>
  );
}
