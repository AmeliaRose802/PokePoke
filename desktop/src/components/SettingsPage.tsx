/**
 * Settings page with model configuration section.
 *
 * Reads from and writes to pokepoke.config.yaml via the DesktopAPI
 * bridge methods (get_config / save_config).
 */

import { useCallback, useEffect, useState } from "react";

import type { ConfigResponse, MaintenanceAgent, McpServerConfig,ModelsConfig, ProjectConfig } from "../types";
import { MaintenanceAgentsSection } from "./MaintenanceAgentsSection";
import { isAbTestingEnabled,KNOWN_MODELS } from "./settingsHelpers";

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
    [markDirty]
  );

  const handleSave = useCallback(async () => {
    if (!config) return;
    setSaving(true);
    const updated: ProjectConfig = {
      ...config,
      models: {
        ...(config.models ?? {}),
        ab_testing_enabled: abTestingEnabled,
        default: defaultModel || undefined,
        fallback: fallbackModel || undefined,
        candidate_models:
          candidateModels.length > 0 ? candidateModels : undefined,
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
  }, [config, defaultModel, fallbackModel, candidateModels, maintenanceAgents, abTestingEnabled, mcpEnabled, mcpName, mcpRestartScript, maxParallelAgents, saveConfig]);

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
    [abTestingEnabled, candidateModels, markDirty]
  );

  const removeChip = useCallback(
    (model: string) => {
      if (!abTestingEnabled) return;
      setCandidateModels((prev) => prev.filter((m) => m !== model));
      markDirty();
    },
    [abTestingEnabled, markDirty]
  );

  const handleChipKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLInputElement>) => {
      if (!abTestingEnabled) return;
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
    [abTestingEnabled, chipInput, candidateModels, addChip, removeChip]
  );

  // Maintenance agent handlers
  const updateMaintenanceAgent = useCallback(
    (index: number, updates: Partial<MaintenanceAgent>) => {
      setMaintenanceAgents((prev) =>
        prev.map((agent, i) => (i === index ? { ...agent, ...updates } : agent))
      );
      markDirty();
    },
    [markDirty]
  );

  const removeMaintenanceAgent = useCallback(
    (index: number) => { setMaintenanceAgents((prev) => prev.filter((_, i) => i !== index)); markDirty(); },
    [markDirty]
  );

  const addMaintenanceAgent = useCallback(
    (agent: MaintenanceAgent) => { setMaintenanceAgents((prev) => [...prev, agent]); markDirty(); },
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
          <span>⚙️ Settings</span>
          <button className="prompt-close-btn" onClick={handleCloseClick}>
            ✕
          </button>
        </div>

        {dirty && (
          <div className="settings-unsaved-banner">
            ⚠️ You have unsaved changes
          </div>
        )}

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
                <span className="settings-hint">
                  Used when the default model is unavailable
                </span>
              </div>

              {/* Candidate Models (tag chips) */}
              <div className="settings-field">
                <label className="settings-label">
                  A/B Candidate Models
                </label>
                <div
                  className={`chip-container ${
                    !abTestingEnabled ? "chip-container-disabled" : ""
                  }`}
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
                      placeholder={
                        candidateModels.length === 0
                          ? "Type model name and press Enter"
                          : "Add model…"
                      }
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
                <label className="settings-label" htmlFor="max-parallel-agents">Max Parallel Agents</label>
                <input
                  id="max-parallel-agents" className="settings-input settings-input-number"
                  type="number" min={1} max={8} value={maxParallelAgents}
                  onChange={(e) => { const v = Math.max(1, Math.min(8, parseInt(e.target.value, 10) || 1)); setMaxParallelAgents(v); markDirty(); }}
                />
                <span className="settings-hint">Controls how many work items are processed concurrently (1–8).</span>
              </div>
            </div>

            {/* Section: MCP Server */}
            <div className="settings-section">
              <h3 className="settings-section-title">🖧 MCP Server</h3>

              <div className="settings-field">
                <label className="settings-label" htmlFor="mcp-enabled">Enable MCP server</label>
                <div className="settings-checkbox-row">
                  <input id="mcp-enabled" type="checkbox" checked={mcpEnabled}
                    onChange={(e) => { setMcpEnabled(e.target.checked); markDirty(); }} />
                  <span className="settings-hint">Controls MCP server integration and restart script usage.</span>
                </div>
              </div>

              <div className="settings-field">
                <label className="settings-label" htmlFor="mcp-name">MCP server name (optional)</label>
                <input id="mcp-name" className="settings-input" value={mcpName}
                  onChange={(e) => { setMcpName(e.target.value); markDirty(); }}
                  placeholder="e.g. My MCP Server" disabled={!mcpEnabled} />
                <span className="settings-hint">Friendly display name for the MCP server.</span>
              </div>

              <div className="settings-field">
                <label className="settings-label" htmlFor="mcp-restart-script">Restart script (optional)</label>
                <input id="mcp-restart-script" className="settings-input" value={mcpRestartScript}
                  onChange={(e) => { setMcpRestartScript(e.target.value); markDirty(); }}
                  placeholder="scripts/Restart-MCPServer.ps1" disabled={!mcpEnabled} />
                <span className="settings-hint">Path to restart the MCP server after configuration changes.</span>
              </div>
            </div>

            <MaintenanceAgentsSection
              agents={maintenanceAgents}
              onUpdate={updateMaintenanceAgent}
              onRemove={removeMaintenanceAgent}
              onAdd={addMaintenanceAgent}
              onOpenPromptEditor={onOpenPromptEditor}
            />

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
