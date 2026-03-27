/**
 * Maintenance agents configuration section for the Settings page.
 */

import { useCallback, useState } from "react";

import type { MaintenanceAgent } from "../types";
import { FALLBACK_KNOWN_MODELS, KNOWN_MAINTENANCE_AGENTS } from "./settingsHelpers";

interface Props {
  agents: MaintenanceAgent[];
  onUpdate: (index: number, updates: Partial<MaintenanceAgent>) => void;
  onRemove: (index: number) => void;
  onAdd: (agent: MaintenanceAgent) => void;
  onOpenPromptEditor?: (promptName: string) => void;
  availableModels?: string[];
}

const EMPTY_CUSTOM: MaintenanceAgent = {
  name: "",
  prompt_file: "",
  frequency: 5,
  enabled: true,
  needs_worktree: false,
  merge_changes: true,
  custom: true,
  description: "",
};

export function MaintenanceAgentsSection({ agents, onUpdate, onRemove, onAdd, onOpenPromptEditor, availableModels }: Props) {
  const modelList = availableModels ?? FALLBACK_KNOWN_MODELS;
  const [selectedToAdd, setSelectedToAdd] = useState("");
  const [showForm, setShowForm] = useState(false);
  const [draft, setDraft] = useState<MaintenanceAgent>({ ...EMPTY_CUSTOM });
  const [formError, setFormError] = useState("");

  const agentNames = new Set(agents.map((a) => a.name));
  const availableToAdd = KNOWN_MAINTENANCE_AGENTS.filter((a) => !agentNames.has(a.name));

  const handleAdd = () => {
    const template = availableToAdd.find((a) => a.name === selectedToAdd);
    if (template) {
      onAdd(template);
      setSelectedToAdd("");
    }
  };

  const resetForm = useCallback(() => {
    setDraft({ ...EMPTY_CUSTOM });
    setFormError("");
    setShowForm(false);
  }, []);

  const handleCreate = useCallback(() => {
    const trimmedName = draft.name.trim();
    if (!trimmedName) {
      setFormError("Name is required");
      return;
    }
    if (agents.some((a) => a.name.toLowerCase() === trimmedName.toLowerCase())) {
      setFormError("An agent with this name already exists");
      return;
    }
    const promptFile = draft.prompt_file.trim() || `${trimmedName.toLowerCase().replace(/\s+/g, "-")}.md`;
    onAdd({
      ...draft,
      name: trimmedName,
      prompt_file: promptFile,
      description: draft.description?.trim() ?? "",
      custom: true,
    });
    resetForm();
  }, [draft, agents, onAdd, resetForm]);

  return (
    <div className="settings-section">
      <h3 className="settings-section-title">🛠️ Maintenance Agents</h3>

      {agents.length === 0 && !showForm ? (
        <div className="settings-no-agents">No maintenance agents configured</div>
      ) : (
        <div className="agents-list">
          {agents.map((agent, index) => (
            <div key={agent.name} className="agent-config">
              <div className="agent-header">
                <span className="agent-name">
                  {agent.name}
                  {agent.custom && <span className="custom-badge">custom</span>}
                </span>
                <div className="agent-header-controls">
                  <label className="agent-toggle">
                    <input
                      type="checkbox"
                      checked={agent.enabled}
                      onChange={(e) => onUpdate(index, { enabled: e.target.checked })}
                    />
                    <span className="toggle-slider"></span>
                  </label>
                  <button
                    className="agent-remove-btn"
                    onClick={() => onRemove(index)}
                    aria-label={`Remove ${agent.name}`}
                    title={`Remove ${agent.name}`}
                  >
                    ✕
                  </button>
                </div>
              </div>
              {agent.description && <div className="agent-description">{agent.description}</div>}
              <div className="agent-details">
                <div className="agent-field">
                  <label className="settings-label">Run every N work items</label>
                  <input
                    type="number"
                    min="1"
                    max="100"
                    className="settings-input number-input"
                    value={agent.frequency}
                    onChange={(e) => onUpdate(index, { frequency: parseInt(e.target.value) || 1 })}
                  />
                </div>
                <div className="agent-field">
                  <label className="settings-label">Model Override (optional)</label>
                  <input
                    className="settings-input"
                    list="model-override-suggestions"
                    value={agent.model || ""}
                    onChange={(e) => onUpdate(index, { model: e.target.value || undefined })}
                    placeholder="Use default model"
                  />
                  <datalist id="model-override-suggestions">
                    {modelList.map((m) => (
                      <option key={m} value={m} />
                    ))}
                  </datalist>
                </div>
                <div className="agent-metadata">
                  <span
                    className="metadata-item prompt-file-link"
                    onClick={() => onOpenPromptEditor?.(agent.prompt_file)}
                    role="button"
                    tabIndex={0}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" || e.key === " ") {
                        e.preventDefault();
                        onOpenPromptEditor?.(agent.prompt_file);
                      }
                    }}
                  >
                    📄 {agent.prompt_file}
                  </span>
                  {agent.needs_worktree && <span className="metadata-item">📂 Needs worktree</span>}
                  {agent.merge_changes && <span className="metadata-item">🔀 Merges changes</span>}
                </div>
              </div>
            </div>
          ))}
        </div>
      )}

      {availableToAdd.length > 0 && (
        <div className="agent-add-row">
          <select
            className="settings-input agent-add-select"
            value={selectedToAdd}
            onChange={(e) => setSelectedToAdd(e.target.value)}
            aria-label="Select agent to add"
          >
            <option value="">Add an agent…</option>
            {availableToAdd.map((a) => (
              <option key={a.name} value={a.name}>
                {a.name}
              </option>
            ))}
          </select>
          <button className="prompt-btn agent-add-btn" onClick={handleAdd} disabled={!selectedToAdd}>
            + Add
          </button>
        </div>
      )}

      {showForm ? (
        <div className="agent-create-form" data-testid="create-agent-form">
          <h4 className="agent-create-title">New Custom Agent</h4>
          <div className="agent-field">
            <label className="settings-label">Name *</label>
            <input
              className="settings-input"
              value={draft.name}
              data-testid="agent-name-input"
              onChange={(e) => {
                setDraft((d) => ({ ...d, name: e.target.value }));
                setFormError("");
              }}
              placeholder="e.g. Security Scanner"
            />
          </div>
          <div className="agent-field">
            <label className="settings-label">Description</label>
            <input
              className="settings-input"
              value={draft.description ?? ""}
              data-testid="agent-description-input"
              onChange={(e) => setDraft((d) => ({ ...d, description: e.target.value }))}
              placeholder="Brief description of what this agent does"
            />
          </div>
          <div className="agent-field">
            <label className="settings-label">Prompt File</label>
            <input
              className="settings-input"
              value={draft.prompt_file}
              data-testid="agent-prompt-input"
              onChange={(e) => setDraft((d) => ({ ...d, prompt_file: e.target.value }))}
              placeholder="Auto-generated from name"
            />
          </div>
          <div className="agent-field">
            <label className="settings-label">Frequency (every N work items)</label>
            <input
              type="number"
              min="1"
              max="100"
              className="settings-input number-input"
              value={draft.frequency}
              data-testid="agent-frequency-input"
              onChange={(e) => setDraft((d) => ({ ...d, frequency: parseInt(e.target.value) || 1 }))}
            />
          </div>
          <div className="agent-field">
            <label className="settings-label">Model Override (optional)</label>
            <input
              className="settings-input"
              list="model-override-suggestions"
              value={draft.model ?? ""}
              data-testid="agent-model-input"
              onChange={(e) => setDraft((d) => ({ ...d, model: e.target.value || undefined }))}
              placeholder="Use default model"
            />
          </div>
          <div className="agent-field">
            <div className="settings-checkbox-row">
              <input
                type="checkbox"
                id="new-agent-worktree"
                checked={draft.needs_worktree}
                onChange={(e) => setDraft((d) => ({ ...d, needs_worktree: e.target.checked }))}
              />
              <label htmlFor="new-agent-worktree" className="settings-label">
                Needs worktree
              </label>
            </div>
          </div>
          <div className="agent-field">
            <div className="settings-checkbox-row">
              <input
                type="checkbox"
                id="new-agent-merge"
                checked={draft.merge_changes ?? true}
                onChange={(e) => setDraft((d) => ({ ...d, merge_changes: e.target.checked }))}
              />
              <label htmlFor="new-agent-merge" className="settings-label">
                Merge changes
              </label>
            </div>
          </div>
          {formError && <div className="agent-form-error">{formError}</div>}
          <div className="agent-form-actions">
            <button className="prompt-btn reset" onClick={resetForm}>
              Cancel
            </button>
            <button className="prompt-btn save" onClick={handleCreate}>
              ➕ Create Agent
            </button>
          </div>
        </div>
      ) : (
        <button className="prompt-btn agent-add-btn" onClick={() => setShowForm(true)}>
          ➕ Add Custom Agent
        </button>
      )}
    </div>
  );
}
