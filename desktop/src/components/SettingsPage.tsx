/**
 * Settings page with model configuration section.
 *
 * Reads from and writes to pokepoke.config.yaml via the DesktopAPI
 * bridge methods (get_config / save_config).
 */

import { useCallback, useEffect, useState } from "react";
import type { ConfigResponse, ProjectConfig, ModelsConfig, MaintenanceAgent } from "../types";

/** Well-known model names for dropdown suggestions */
const KNOWN_MODELS = [
  "claude-opus-4.5",
  "claude-opus-4.6",
  "claude-sonnet-4",
  "claude-sonnet-4.5",
  "gemini-3-pro",
  "gpt-5",
  "gpt-5-codex",
  "gpt-5.1",
  "gpt-5.1-codex",
  "gpt-5.1-codex-max",
  "gpt-5.2",
  "gpt-5.2-codex",
];

interface Props {
  getConfig: () => Promise<ConfigResponse | null>;
  saveConfig: (config: ProjectConfig) => Promise<boolean>;
  onClose: () => void;
}

export function SettingsPage({ getConfig, saveConfig, onClose }: Props) {
  const [config, setConfig] = useState<ProjectConfig | null>(null);
  const [defaultModel, setDefaultModel] = useState("");
  const [fallbackModel, setFallbackModel] = useState("");
  const [candidateModels, setCandidateModels] = useState<string[]>([]);
  const [chipInput, setChipInput] = useState("");
  const [maintenanceAgents, setMaintenanceAgents] = useState<MaintenanceAgent[]>([]);
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState("");
  const [loading, setLoading] = useState(true);

  // Load config on mount
  useEffect(() => {
    let active = true;
    getConfig().then((resp) => {
      if (!active) return;
      setLoading(false);
      if (!resp) return;
      setConfig(resp.config);
      const models = resp.config.models ?? {};
      setDefaultModel(models.default ?? "");
      setFallbackModel(models.fallback ?? "");
      setCandidateModels(models.candidate_models ?? []);
      
      // Load maintenance agents
      const maintenance = resp.config.maintenance;
      if (maintenance && Array.isArray(maintenance.agents)) {
        setMaintenanceAgents(maintenance.agents);
      }
    });
    return () => {
      active = false;
    };
  }, [getConfig]);

  const markDirty = useCallback(() => {
    setDirty(true);
    setMessage("");
  }, []);

  const handleSave = useCallback(async () => {
    if (!config) return;
    setSaving(true);
    const updated: ProjectConfig = {
      ...config,
      models: {
        ...(config.models ?? {}),
        default: defaultModel || undefined,
        fallback: fallbackModel || undefined,
        candidate_models:
          candidateModels.length > 0 ? candidateModels : undefined,
      } as ModelsConfig,
      maintenance: {
        ...config.maintenance,
        agents: maintenanceAgents,
      },
    };
    const ok = await saveConfig(updated);
    setSaving(false);
    if (ok) {
      setConfig(updated);
      setDirty(false);
      setMessage("Saved");
    } else {
      setMessage("Save failed");
    }
  }, [config, defaultModel, fallbackModel, candidateModels, maintenanceAgents, saveConfig]);

  const handleReset = useCallback(() => {
    if (!config) return;
    const models = config.models ?? {};
    setDefaultModel(models.default ?? "");
    setFallbackModel(models.fallback ?? "");
    setCandidateModels(models.candidate_models ?? []);
    
    // Reset maintenance agents
    const maintenance = config.maintenance;
    if (maintenance && Array.isArray(maintenance.agents)) {
      setMaintenanceAgents(maintenance.agents);
    } else {
      setMaintenanceAgents([]);
    }
    
    setDirty(false);
    setMessage("Reset to saved values");
  }, [config]);

  const addChip = useCallback(
    (value: string) => {
      const trimmed = value.trim();
      if (!trimmed || candidateModels.includes(trimmed)) return;
      setCandidateModels((prev) => [...prev, trimmed]);
      setChipInput("");
      markDirty();
    },
    [candidateModels, markDirty]
  );

  const removeChip = useCallback(
    (model: string) => {
      setCandidateModels((prev) => prev.filter((m) => m !== model));
      markDirty();
    },
    [markDirty]
  );

  const handleChipKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLInputElement>) => {
      if (e.key === "Enter" || e.key === ",") {
        e.preventDefault();
        addChip(chipInput);
      } else if (
        e.key === "Backspace" &&
        chipInput === "" &&
        candidateModels.length > 0
      ) {
        removeChip(candidateModels[candidateModels.length - 1]);
      }
    },
    [chipInput, candidateModels, addChip, removeChip]
  );

  // Maintenance agent handlers
  const updateMaintenanceAgent = useCallback(
    (index: number, updates: Partial<MaintenanceAgent>) => {
      setMaintenanceAgents((prev) =>
        prev.map((agent, i) => 
          i === index ? { ...agent, ...updates } : agent
        )
      );
      markDirty();
    },
    [markDirty]
  );

  // Filter suggestions: known models not already in the candidate list
  const suggestions = KNOWN_MODELS.filter(
    (m) =>
      !candidateModels.includes(m) &&
      m.toLowerCase().includes(chipInput.toLowerCase())
  );

  return (
    <div className="settings-overlay">
      <div className="settings-panel">
        {/* Header */}
        <div className="settings-header">
          <span>⚙ Settings</span>
          <button className="prompt-close-btn" onClick={onClose}>
            ✕
          </button>
        </div>

        {loading ? (
          <div className="settings-loading">Loading configuration…</div>
        ) : !config ? (
          <div className="settings-loading">
            Could not load configuration.
          </div>
        ) : (
          <div className="settings-body">
            {/* Section: Model Configuration */}
            <div className="settings-section">
              <h3 className="settings-section-title">🤖 Model Configuration</h3>

              {/* Default Model */}
              <div className="settings-field">
                <label className="settings-label" htmlFor="default-model">
                  Default Model
                </label>
                <input
                  id="default-model"
                  className="settings-input"
                  list="default-model-suggestions"
                  value={defaultModel}
                  onChange={(e) => {
                    setDefaultModel(e.target.value);
                    markDirty();
                  }}
                  placeholder="e.g. claude-sonnet-4.5"
                />
                <datalist id="default-model-suggestions">
                  {KNOWN_MODELS.map((m) => (
                    <option key={m} value={m} />
                  ))}
                </datalist>
                <span className="settings-hint">
                  Primary model for agent tasks
                </span>
              </div>

              {/* Fallback Model */}
              <div className="settings-field">
                <label className="settings-label" htmlFor="fallback-model">
                  Fallback Model
                </label>
                <input
                  id="fallback-model"
                  className="settings-input"
                  list="fallback-model-suggestions"
                  value={fallbackModel}
                  onChange={(e) => {
                    setFallbackModel(e.target.value);
                    markDirty();
                  }}
                  placeholder="e.g. claude-sonnet-4"
                />
                <datalist id="fallback-model-suggestions">
                  {KNOWN_MODELS.map((m) => (
                    <option key={m} value={m} />
                  ))}
                </datalist>
                <span className="settings-hint">
                  Used when the default model is unavailable
                </span>
              </div>

              {/* Candidate Models (tag chips) */}
              <div className="settings-field">
                <label className="settings-label">
                  A/B Candidate Models
                </label>
                <div className="chip-container">
                  {candidateModels.map((m) => (
                    <span key={m} className="chip">
                      {m}
                      <button
                        className="chip-remove"
                        onClick={() => removeChip(m)}
                        aria-label={`Remove ${m}`}
                      >
                        ✕
                      </button>
                    </span>
                  ))}
                  <input
                    className="chip-input"
                    value={chipInput}
                    onChange={(e) => setChipInput(e.target.value)}
                    onKeyDown={handleChipKeyDown}
                    onBlur={() => {
                      if (chipInput.trim()) addChip(chipInput);
                    }}
                    placeholder={
                      candidateModels.length === 0
                        ? "Type model name and press Enter"
                        : "Add model…"
                    }
                    list="chip-suggestions"
                  />
                  <datalist id="chip-suggestions">
                    {suggestions.map((m) => (
                      <option key={m} value={m} />
                    ))}
                  </datalist>
                </div>
                <span className="settings-hint">
                  Models to rotate through for A/B performance testing
                </span>
              </div>
            </div>

            {/* Section: Maintenance Agents Configuration */}
            <div className="settings-section">
              <h3 className="settings-section-title">🔧 Maintenance Agents</h3>

              {maintenanceAgents.length === 0 ? (
                <div className="settings-no-agents">
                  No maintenance agents configured
                </div>
              ) : (
                <div className="agents-list">
                  {maintenanceAgents.map((agent, index) => (
                    <div key={agent.name} className="agent-config">
                      <div className="agent-header">
                        <span className="agent-name">{agent.name}</span>
                        <label className="agent-toggle">
                          <input
                            type="checkbox"
                            checked={agent.enabled}
                            onChange={(e) =>
                              updateMaintenanceAgent(index, { enabled: e.target.checked })
                            }
                          />
                          <span className="toggle-slider"></span>
                        </label>
                      </div>

                      <div className="agent-details">
                        <div className="agent-field">
                          <label className="settings-label">
                            Run every N work items
                          </label>
                          <input
                            type="number"
                            min="1"
                            max="100"
                            className="settings-input number-input"
                            value={agent.frequency}
                            onChange={(e) =>
                              updateMaintenanceAgent(index, {
                                frequency: parseInt(e.target.value) || 1,
                              })
                            }
                          />
                        </div>

                        <div className="agent-field">
                          <label className="settings-label">
                            Model Override (optional)
                          </label>
                          <input
                            className="settings-input"
                            list="model-override-suggestions"
                            value={agent.model || ""}
                            onChange={(e) =>
                              updateMaintenanceAgent(index, {
                                model: e.target.value || undefined,
                              })
                            }
                            placeholder="Use default model"
                          />
                          <datalist id="model-override-suggestions">
                            {KNOWN_MODELS.map((m) => (
                              <option key={m} value={m} />
                            ))}
                          </datalist>
                        </div>

                        <div className="agent-metadata">
                          <span className="metadata-item">
                            📄 {agent.prompt_file}
                          </span>
                          {agent.needs_worktree && (
                            <span className="metadata-item">
                              🌳 Needs worktree
                            </span>
                          )}
                          {agent.merge_changes && (
                            <span className="metadata-item">
                              🔀 Merges changes
                            </span>
                          )}
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>

            {/* Footer actions */}
            <div className="settings-footer">
              {message && (
                <span
                  className={`settings-message ${
                    message === "Save failed"
                      ? "settings-message-error"
                      : ""
                  }`}
                >
                  {message}
                </span>
              )}
              {dirty && (
                <span className="settings-unsaved">Unsaved changes</span>
              )}
              <div className="settings-actions">
                <button
                  className="prompt-btn reset"
                  onClick={handleReset}
                  disabled={!dirty}
                >
                  ↩ Reset
                </button>
                <button
                  className="prompt-btn save"
                  onClick={handleSave}
                  disabled={!dirty || saving}
                >
                  {saving ? "…" : "💾 Save"}
                </button>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
