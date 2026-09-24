import { KeyRound, RefreshCw, X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { api } from "../lib/api.ts";
import { useEscape } from "../lib/useEscape.ts";
import type { Health, ModelInfo, Settings } from "../lib/types.ts";

function price(value?: string | null): string {
  const n = Number(value ?? NaN);
  if (!Number.isFinite(n)) return "";
  if (n === 0) return "free";
  return `$${(n * 1_000_000).toFixed(2)}/M`;
}

function Segmented<T extends string>({ value, options, onChange }: { value: T; options: { value: T; label: string }[]; onChange: (v: T) => void }) {
  return (
    <div className="segmented">
      {options.map((o) => (
        <button key={o.value} type="button" className={o.value === value ? "active" : ""} onClick={() => onChange(o.value)}>
          {o.label}
        </button>
      ))}
    </div>
  );
}

export function SettingsDialog({ onClose, onSaved, health }: { onClose: () => void; onSaved: (settings: Settings) => void; health: Health | null }) {
  useEscape(onClose);
  const [settings, setSettings] = useState<Settings | null>(null);
  const [key, setKey] = useState("");
  const [models, setModels] = useState<ModelInfo[]>([]);
  const [modelsError, setModelsError] = useState("");
  const [filter, setFilter] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    api.settings().then(setSettings, (e) => setError(String(e.message)));
    api.models().then(
      (d) => {
        setModels(d.models);
        setModelsError(d.error);
      },
      (e) => setModelsError(String(e.message)),
    );
  }, []);

  const shown = useMemo(() => {
    const q = filter.toLowerCase();
    return models.filter((m) => m.tools && (!q || m.id.toLowerCase().includes(q) || m.name.toLowerCase().includes(q))).slice(0, 200);
  }, [models, filter]);

  if (!settings) {
    return (
      <div className="backdrop" onMouseDown={onClose}>
        <div className="dialog" onMouseDown={(e) => e.stopPropagation()}>
          <div className="dialogBody">{error || "Loading…"}</div>
        </div>
      </div>
    );
  }

  const set = <K extends keyof Settings>(field: K, value: Settings[K]) => setSettings({ ...settings, [field]: value });

  const save = async () => {
    setSaving(true);
    setError("");
    try {
      const saved = await api.saveSettings({ ...settings, openrouter_api_key: key });
      setKey("");
      onSaved(saved);
      onClose();
    } catch (e) {
      setError(String((e as Error).message));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="backdrop" onMouseDown={onClose}>
      <div className="dialog" onMouseDown={(e) => e.stopPropagation()} role="dialog" aria-label="Settings">
        <div className="dialogHead">
          <h2>Settings</h2>
          <button className="iconButton" onClick={onClose} aria-label="Close">
            <X size={16} />
          </button>
        </div>
        <div className="dialogBody scroll">
          <div className="pixelLabel sectionTitle" style={{ marginTop: 0 }}>
            Model provider · OpenRouter
          </div>
          <div className="field">
            <label htmlFor="key">
              <KeyRound size={13} /> API key
            </label>
            <input
              id="key"
              className="input"
              type="password"
              autoComplete="off"
              placeholder={settings.api_key_set ? `Saved (${settings.api_key_hint}) — leave blank to keep` : "sk-or-v1-…"}
              value={key}
              onChange={(e) => setKey(e.target.value)}
              disabled={settings.api_key_source === "environment"}
            />
            <span className="help">
              {settings.api_key_source === "environment"
                ? "Using OPENROUTER_API_KEY from the server's environment."
                : "Stored on this machine only (0600). One key covers the agent, Jev, web search, and Dhee's OpenRouter lane."}
              {settings.api_key_source === "settings" ? (
                <>
                  {" "}
                  <button type="button" className="iconButton small" style={{ minHeight: 0, padding: 0, textDecoration: "underline" }} onClick={() => api.saveSettings({ clear_api_key: true }).then(setSettings)}>
                    Remove key
                  </button>
                </>
              ) : null}
            </span>
          </div>

          <div className="field">
            <label htmlFor="model">Coding model</label>
            <input id="model" className="input mono" value={settings.model} onChange={(e) => set("model", e.target.value.trim())} />
            <div className="panelTools" style={{ marginBottom: 0 }}>
              <input className="input" placeholder="Filter OpenRouter models with tool support" value={filter} onChange={(e) => setFilter(e.target.value)} />
              <button type="button" className="iconButton" title="Refresh the catalogue" onClick={() => api.models(true).then((d) => setModels(d.models))}>
                <RefreshCw size={14} />
              </button>
            </div>
            {modelsError && !models.length ? <span className="help">Catalogue unavailable ({modelsError}); type a model id above.</span> : null}
            {models.length ? (
              <div className="modelList scroll">
                {shown.map((m) => (
                  <button
                    type="button"
                    key={m.id}
                    className={`modelRow${m.id === settings.model ? " active" : ""}`}
                    onClick={() => setSettings({ ...settings, model: m.id, max_context_size: m.context_length ? Math.max(8000, m.context_length) : settings.max_context_size })}
                  >
                    <span className="mono small">{m.id}</span>
                    <span className="faint small">
                      {m.context_length ? `${Math.round(m.context_length / 1000)}k` : ""} {price(m.prompt_price)}
                      {m.capabilities.includes("image_in") ? " · vision" : ""}
                    </span>
                  </button>
                ))}
              </div>
            ) : null}
          </div>

          <div className="fieldRow">
            <div className="field">
              <label htmlFor="ctx">Context window (tokens)</label>
              <input id="ctx" className="input" type="number" min={8000} value={settings.max_context_size} onChange={(e) => set("max_context_size", Number(e.target.value))} />
              <span className="help">The runtime compacts the conversation before it runs out.</span>
            </div>
            <div className="field">
              <label htmlFor="steps">Max steps per turn</label>
              <input id="steps" className="input" type="number" min={1} max={1000} value={settings.max_steps_per_turn} onChange={(e) => set("max_steps_per_turn", Number(e.target.value))} />
            </div>
          </div>

          <div className="field">
            <label>Reasoning effort</label>
            <Segmented
              value={(settings.reasoning_effort || "") as string}
              options={[
                { value: "", label: "Model default" },
                { value: "low", label: "Low" },
                { value: "medium", label: "Medium" },
                { value: "high", label: "High" },
              ]}
              onChange={(v) => set("reasoning_effort", v)}
            />
          </div>

          <div className="pixelLabel sectionTitle">Jev step director</div>
          <div className="field">
            <Segmented
              value={settings.director_mode}
              options={[
                { value: "on", label: "On" },
                { value: "shadow", label: "Shadow" },
                { value: "off", label: "Off" },
              ]}
              onChange={(v) => set("director_mode", v)}
            />
            <span className="help">
              Jev (<span className="mono">typesafe/jev-1.13</span>) decides, before each step, whether to reply or which tool to call, so small models stop describing work instead of doing it. Shadow records
              its decisions without acting on them.
            </span>
          </div>

          <div className="pixelLabel sectionTitle">Dhee memory</div>
          <div className="field">
            <Segmented
              value={settings.memory_mode}
              options={[
                { value: "local", label: "Local" },
                { value: "openrouter", label: "OpenRouter" },
                { value: "off", label: "Off" },
              ]}
              onChange={(v) => set("memory_mode", v)}
            />
            <span className="help">
              Local works offline with lexical recall. OpenRouter uses real embeddings ({settings.memory_embedding_model}) and an enrichment model ({settings.memory_llm_model}).
              {health && !health.memory.installed ? " Dhee is not installed on the server, so memory is off." : ""}
            </span>
          </div>
          {settings.memory_mode === "openrouter" ? (
            <div className="fieldRow">
              <div className="field">
                <label htmlFor="emb">Embedding model</label>
                <input id="emb" className="input mono" value={settings.memory_embedding_model} onChange={(e) => set("memory_embedding_model", e.target.value)} />
              </div>
              <div className="field">
                <label htmlFor="dims">Embedding dimensions</label>
                <input id="dims" className="input" type="number" value={settings.memory_embedding_dims} onChange={(e) => set("memory_embedding_dims", Number(e.target.value))} />
              </div>
            </div>
          ) : null}

          <div className="pixelLabel sectionTitle">Tools & defaults</div>
          <div className="fieldRow">
            <div className="field">
              <label>Web search</label>
              <Segmented
                value={settings.web_search ? "on" : "off"}
                options={[
                  { value: "on", label: "On" },
                  { value: "off", label: "Off" },
                ]}
                onChange={(v) => set("web_search", v === "on")}
              />
              <span className="help">Through OpenRouter’s web plugin ({settings.search_model}).</span>
            </div>
            <div className="field">
              <label htmlFor="mode">New sessions start in</label>
              <select id="mode" className="input" value={settings.default_permission_mode} onChange={(e) => set("default_permission_mode", e.target.value as Settings["default_permission_mode"])}>
                <option value="default">Ask before acting</option>
                <option value="accept_edits">Accept edits</option>
                <option value="plan">Plan</option>
                <option value="yolo">Auto-approve all</option>
              </select>
            </div>
          </div>
          {error ? <p className="small" style={{ color: "var(--err)" }}>{error}</p> : null}
        </div>
        <div className="dialogFoot">
          <span className="faint small" style={{ marginRight: "auto", alignSelf: "center" }}>
            Changes apply from the next message.
          </span>
          <button className="button" onClick={onClose}>
            Cancel
          </button>
          <button className="button primary" onClick={save} disabled={saving}>
            {saving ? "Saving…" : "Save"}
          </button>
        </div>
      </div>
    </div>
  );
}
