/** Settings page — reads/writes pokepoke.config.yaml via DesktopAPI bridge. */

import { useCallback, useEffect, useState } from "react";

import type { ConfigResponse, MaintenanceAgent, McpServerConfig, ModelsConfig, ProjectConfig } from "../types";
import { MaintenanceAgentsSection } from "./MaintenanceAgentsSection";
import { McpServerSection } from "./McpServerSection";
import { isAbTestingEnabled, KNOWN_MODELS } from "./settingsHelpers";
import { SpecialEffectTagsSection } from "./SpecialEffectTagsSection";

interface Props {
  getConfig: () => Promise<ConfigResponse | null>;
  saveConfig: (config: ProjectConfig) => Promise<boolean>;
  onClose: () => void;
  onOpenPromptEditor?: (promptName: string) => void;
}

export function SettingsPage({ getConfig, saveConfig, onClose, onOpenPromptEditor }: Props) {
  const [config, setConfig] = useState<ProjectConfig | null>(null);
  const [defaultModel, setDefaultModel] = useState("");
  const [fallbackModel, setFallbackModel] = useState("");
  const [candidateModels, setCandidateModels] = useState<string[]>([]);
  const [chipInput, setChipInput] = useState("");
  const [maintenanceAgents, setMaintenanceAgents] = useState<MaintenanceAgent[]>([]);
  const [abTestingEnabled, setAbTestingEnabled] = useState(false);
  const [mcpEnabled, setMcpEnabled] = useState(false);
  const [mcpName, setMcpName] = useState("");
  const [mcpRestartScript, setMcpRestartScript] = useState("");
  const [maxParallelAgents, setMaxParallelAgents] = useState(1);
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
      const abTesting = isAbTestingEnabled(models);
      setAbTestingEnabled(abTesting);
      setDefaultModel(models.default ?? "");
      setFallbackModel(models.fallback ?? "");
      setCandidateModels(models.candidate_models ?? []);
      const mcpServer = resp.config.mcp_server ?? {};
      setMcpEnabled(mcpServer.enabled ?? false);
      setMcpName(mcpServer.name ?? "");
      setMcpRestartScript(mcpServer.restart_script ?? "");
      setMaxParallelAgents(Math.max(1, resp.config.max_parallel_agents ?? 1));

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

  const handleAbToggle = useCallback(
    (enabled: boolean) => {
      setAbTestingEnabled(enabled);
      markDirty();
    },
    [markDirty],
  );

  const handleSave = useCallback(async (): Promise<boolean> => {
    if (!config) return false;
    setSaving(true);
    const updated: ProjectConfig = {
      ...config,
      models: {
        ...(config.models ?? {}),
        ab_testing_enabled: abTestingEnabled,
        default: defaultModel || undefined,
        fallback: fallbackModel || undefined,
        candidate_models: candidateModels.length > 0 ? candidateModels : undefined,
      } as ModelsConfig,
      mcp_server: {
        ...(config.mcp_server ?? {}),
        enabled: mcpEnabled,
        name: mcpName || undefined,
        restart_script: mcpRestartScript || undefined,
      } as McpServerConfig,
      maintenance: {
        ...config.maintenance,
        agents: maintenanceAgents,
      },
      max_parallel_agents: maxParallelAgents,
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
    return ok;
  }, [
    config,
    defaultModel,
    fallbackModel,
    candidateModels,
    maintenanceAgents,
    abTestingEnabled,
    mcpEnabled,
    mcpName,
    mcpRestartScript,
    maxParallelAgents,
    saveConfig,
  ]);

  const handleReset = useCallback(() => {
    if (!config) return;
    const models = config.models ?? {};
    const abTesting = isAbTestingEnabled(models);
    setAbTestingEnabled(abTesting);
    setDefaultModel(models.default ?? "");
    setFallbackModel(models.fallback ?? "");
    setCandidateModels(models.candidate_models ?? []);
    setChipInput("");
    const mcpServer = config.mcp_server ?? {};
    setMcpEnabled(mcpServer.enabled ?? false);
    setMcpName(mcpServer.name ?? "");
    setMcpRestartScript(mcpServer.restart_script ?? "");
    setMaxParallelAgents(Math.max(1, config.max_parallel_agents ?? 1));

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

  const handleCloseClick = useCallback(() => {
    if (dirty) {
      const shouldClose = window.confirm("Close without saving?");
      if (shouldClose) {
        onClose();
      }
    } else {
      onClose();
    }
  }, [dirty, onClose]);

  const addChip = useCallback(
    (value: string) => {
      if (!abTestingEnabled) return;
      const trimmed = value.trim();
      if (!trimmed || candidateModels.includes(trimmed)) return;
      setCandidateModels((prev) => [...prev, trimmed]);
      setChipInput("");
      markDirty();
    },
    [abTestingEnabled, candidateModels, markDirty],
  );

  const removeChip = useCallback(
    (model: string) => {
      if (!abTestingEnabled) return;
      setCandidateModels((prev) => prev.filter((m) => m !== model));
      markDirty();
    },
    [abTestingEnabled, markDirty],
  );

  const addAllCandidates = useCallback(() => {
    if (!abTestingEnabled) return;
    setCandidateModels((prev) => {
      const existing = new Set(prev);
      const toAdd = KNOWN_MODELS.filter((m) => !existing.has(m));
      return toAdd.length > 0 ? [...prev, ...toAdd] : prev;
    });
    markDirty();
  }, [abTestingEnabled, markDirty]);

  const handleChipKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLInputElement>) => {
      if (!abTestingEnabled) return;
      if (e.key === "Enter" || e.key === ",") {
        e.preventDefault();
        addChip(chipInput);
      } else if (e.key === "Backspace" && chipInput === "" && candidateModels.length > 0) {
        removeChip(candidateModels[candidateModels.length - 1]);
      }
    },
    [abTestingEnabled, chipInput, candidateModels, addChip, removeChip],
  );

  // Maintenance agent handlers
  const updateMaintenanceAgent = useCallback(
    (index: number, updates: Partial<MaintenanceAgent>) => {
      setMaintenanceAgents((prev) => prev.map((agent, i) => (i === index ? { ...agent, ...updates } : agent)));
      markDirty();
    },
    [markDirty],
  );

  const removeMaintenanceAgent = useCallback(
    (index: number) => {
      setMaintenanceAgents((prev) => prev.filter((_, i) => i !== index));
      markDirty();
    },
    [markDirty],
  );

  const addMaintenanceAgent = useCallback(
    (agent: MaintenanceAgent) => {
      setMaintenanceAgents((prev) => [...prev, agent]);
      markDirty();
    },
    [markDirty],
  );

  const handlePromptFileClick = useCallback(
    async (promptName: string) => {
      if (!onOpenPromptEditor) return;
      if (dirty) {
        const ok = await handleSave();
        if (!ok) {
          const shouldDiscard = window.confirm("Save failed. Discard changes and open prompt editor?");
          if (!shouldDiscard) return;
        }
      }
      onOpenPromptEditor(promptName);
    },
    [dirty, handleSave, onOpenPromptEditor],
  );

  // Filter suggestions: known models not already in the candidate list
  const suggestions = KNOWN_MODELS.filter(
    (m) => !candidateModels.includes(m) && m.toLowerCase().includes(chipInput.toLowerCase()),
  );

  return (
    <div className="settings-overlay">
      <div className="settings-panel">
        {/* Header */}
        <div className="settings-header">
          <span>⚙️ Settings</span>
          <button className="prompt-close-btn" onClick={handleCloseClick}>
            ✕
          </button>
        </div>

        {dirty && <div className="settings-unsaved-banner">⚠️ You have unsaved changes</div>}

        {loading ? (
          <div className="settings-loading">Loading configuration…</div>
        ) : !config ? (
          <div className="settings-loading">Could not load configuration.</div>
        ) : (
          <div className="settings-body">
            {/* Section: Model Configuration */}
            <div className="settings-section">
              <h3 className="settings-section-title">🐍 Model Configuration</h3>

              {/* A/B Testing toggle */}
              <div className="settings-field">
                <label className="settings-label" htmlFor="ab-testing-mode">
                  Enable A/B testing mode
                </label>
                <div className="settings-checkbox-row">
                  <input
                    id="ab-testing-mode"
                    type="checkbox"
                    checked={abTestingEnabled}
                    onChange={(e) => handleAbToggle(e.target.checked)}
                  />
                  <span className="settings-hint">
                    Switch between single-model (Default/Fallback) and rotating candidate models.
                  </span>
                </div>
              </div>

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
                  disabled={abTestingEnabled}
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
                  {abTestingEnabled ? "Ignored while A/B testing is active" : "Primary model for agent tasks"}
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
                  disabled={abTestingEnabled}
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
                <span className="settings-hint">Used when the default model is unavailable</span>
              </div>

              {/* Candidate Models (tag chips) */}
              <div className="settings-field">
                <div className="settings-label-row">
                  <label className="settings-label">A/B Candidate Models</label>
                  {abTestingEnabled && candidateModels.length < KNOWN_MODELS.length && (
                    <button type="button" className="add-all-btn" onClick={addAllCandidates}>
                      Add All
                    </button>
                  )}
                </div>
                <div
                  className={`chip-container ${!abTestingEnabled ? "chip-container-disabled" : ""}`}
                  aria-disabled={!abTestingEnabled}
                >
                  {candidateModels.map((m) => (
                    <span key={m} className="chip">
                      {m}
                      <button
                        className="chip-remove"
                        onClick={() => removeChip(m)}
                        disabled={!abTestingEnabled}
                        aria-label={`Remove ${m}`}
                      >
                        ✕
                      </button>
                    </span>
                  ))}
                  {abTestingEnabled && (
                    <input
                      className="chip-input"
                      value={chipInput}
                      onChange={(e) => setChipInput(e.target.value)}
                      onKeyDown={handleChipKeyDown}
                      onBlur={() => {
                        if (chipInput.trim()) addChip(chipInput);
                      }}
                      placeholder={candidateModels.length === 0 ? "Type model name and press Enter" : "Add model…"}
                      list="chip-suggestions"
                    />
                  )}
                  <datalist id="chip-suggestions">
                    {suggestions.map((m) => (
                      <option key={m} value={m} />
                    ))}
                  </datalist>
                </div>
                <span className="settings-hint">
                  {abTestingEnabled
                    ? "Models to rotate through for A/B performance testing"
                    : "Enable A/B testing to configure candidate models"}
                </span>
              </div>
            </div>

            {/* Section: Orchestrator */}
            <div className="settings-section">
              <h3 className="settings-section-title">⚡ Orchestrator</h3>
              <div className="settings-field">
                <label className="settings-label" htmlFor="max-parallel-agents">
                  Max Parallel Agents
                </label>
                <input
                  id="max-parallel-agents"
                  className="settings-input settings-input-number"
                  type="number"
                  min={1}
                  max={8}
                  value={maxParallelAgents}
                  onChange={(e) => {
                    const v = Math.max(1, Math.min(8, parseInt(e.target.value, 10) || 1));
                    setMaxParallelAgents(v);
                    markDirty();
                  }}
                />
                <span className="settings-hint">Controls how many work items are processed concurrently (1–8).</span>
                {maxParallelAgents > 1 && <span className="settings-hint">⚠️ Parallel mode is experimental.</span>}
              </div>
            </div>

            <McpServerSection
              mcpConfig={{ enabled: mcpEnabled, name: mcpName, restart_script: mcpRestartScript }}
              onChange={(updates) => {
                if (updates.enabled !== undefined) setMcpEnabled(updates.enabled);
                if (updates.name !== undefined) setMcpName(updates.name);
                if (updates.restart_script !== undefined) setMcpRestartScript(updates.restart_script);
                markDirty();
              }}
            />

            <MaintenanceAgentsSection
              agents={maintenanceAgents}
              onUpdate={updateMaintenanceAgent}
              onRemove={removeMaintenanceAgent}
              onAdd={addMaintenanceAgent}
              onOpenPromptEditor={handlePromptFileClick}
            />

            <SpecialEffectTagsSection />

            {/* Footer actions */}
            <div className="settings-footer">
              {message && (
                <span className={`settings-message ${message === "Save failed" ? "settings-message-error" : ""}`}>
                  {message}
                </span>
              )}
              {dirty && <span className="settings-unsaved">Unsaved changes</span>}
              <div className="settings-actions">
                <button className="prompt-btn reset" onClick={handleReset} disabled={!dirty}>
                  ↩ Reset
                </button>
                <button className="prompt-btn save" onClick={handleSave} disabled={!dirty || saving}>
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
