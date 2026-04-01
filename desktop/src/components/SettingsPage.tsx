/** Settings page — reads/writes pokepoke.config.yaml via DesktopAPI bridge. */

import { useCallback, useEffect, useState } from "react";

import type {
  AvailableModelsResponse,
  ConfigResponse,
  MaintenanceAgent,
  McpServerConfig,
  ModelsConfig,
  ProjectConfig,
} from "../types";
import { MaintenanceAgentsSection } from "./MaintenanceAgentsSection";
import { McpServerSection } from "./McpServerSection";
import { ModelConfigSection } from "./ModelConfigSection";
import { FALLBACK_KNOWN_MODELS, isAbTestingEnabled, mergeModelLists } from "./settingsHelpers";
import { SpecialEffectTagsSection } from "./SpecialEffectTagsSection";

interface Props {
  getConfig: () => Promise<ConfigResponse | null>;
  saveConfig: (config: ProjectConfig) => Promise<boolean>;
  getAvailableModels?: () => Promise<AvailableModelsResponse | null>;
  onClose: () => void;
  onOpenPromptEditor?: (promptName: string) => void;
}

export function SettingsPage({ getConfig, saveConfig, getAvailableModels, onClose, onOpenPromptEditor }: Props) {
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
  const [availableModels, setAvailableModels] = useState<string[]>(FALLBACK_KNOWN_MODELS);
  const [removedFromConfig, setRemovedFromConfig] = useState<string[]>([]);

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
    // Fetch available models from SDK registry
    if (getAvailableModels) {
      getAvailableModels().then((resp) => {
        if (!active || !resp) return;
        setAvailableModels(mergeModelLists(resp.models));
        if (resp.removed_from_config.length > 0) {
          setRemovedFromConfig(resp.removed_from_config);
        }
      });
    }
    return () => {
      active = false;
    };
  }, [getConfig, getAvailableModels]);

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

  const addAllCandidateModels = useCallback(() => {
    if (!abTestingEnabled) return;

    setCandidateModels((prev) => {
      const existing = new Set(prev);
      const merged = [...prev];
      for (const model of availableModels) {
        if (!existing.has(model)) {
          merged.push(model);
        }
      }
      return merged;
    });

    setChipInput("");
    markDirty();
  }, [abTestingEnabled, availableModels, markDirty]);

  const removeChip = useCallback(
    (model: string) => {
      if (!abTestingEnabled) return;
      setCandidateModels((prev) => prev.filter((m) => m !== model));
      markDirty();
    },
    [abTestingEnabled, markDirty],
  );

  const handleChipKeyDown= useCallback(
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

        {removedFromConfig.length > 0 && (
          <div className="settings-unsaved-banner" role="alert">
            ⚠️ The following models were removed from your config because they are no longer available:{" "}
            <strong>{removedFromConfig.join(", ")}</strong>
            <button
              className="chip-remove dismiss-btn"
              onClick={() => setRemovedFromConfig([])}
              aria-label="Dismiss notification"
            >
              ✕
            </button>
          </div>
        )}

        {loading ? (
          <div className="settings-loading">Loading configuration…</div>
        ) : !config ? (
          <div className="settings-loading">Could not load configuration.</div>
        ) : (
          <div className="settings-body">
            <ModelConfigSection
              abTestingEnabled={abTestingEnabled}
              onAbToggle={handleAbToggle}
              defaultModel={defaultModel}
              onDefaultModelChange={(v) => {
                setDefaultModel(v);
                markDirty();
              }}
              fallbackModel={fallbackModel}
              onFallbackModelChange={(v) => {
                setFallbackModel(v);
                markDirty();
              }}
              candidateModels={candidateModels}
              chipInput={chipInput}
              onChipInputChange={setChipInput}
              onAddChip={addChip}
              onAddAllCandidateModels={addAllCandidateModels}
              onRemoveChip={removeChip}
              onChipKeyDown={handleChipKeyDown}
              availableModels={availableModels}
            />

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
              availableModels={availableModels}
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
