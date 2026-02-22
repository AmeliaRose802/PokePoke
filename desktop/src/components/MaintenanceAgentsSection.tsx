/**
 * Maintenance agents configuration section for the Settings page.
 */

import type { MaintenanceAgent } from "../types";
import { KNOWN_MODELS } from "./settingsHelpers";

interface Props {
  agents: MaintenanceAgent[];
  onUpdate: (index: number, updates: Partial<MaintenanceAgent>) => void;
  onOpenPromptEditor?: (promptName: string) => void;
}

export function MaintenanceAgentsSection({ agents, onUpdate, onOpenPromptEditor }: Props) {
  return (
    <div className="settings-section">
      <h3 className="settings-section-title">🌳 Maintenance Agents</h3>

      {agents.length === 0 ? (
        <div className="settings-no-agents">
          No maintenance agents configured
        </div>
      ) : (
        <div className="agents-list">
          {agents.map((agent, index) => (
            <div key={agent.name} className="agent-config">
              <div className="agent-header">
                <span className="agent-name">{agent.name}</span>
                <label className="agent-toggle">
                  <input
                    type="checkbox"
                    checked={agent.enabled}
                    onChange={(e) =>
                      onUpdate(index, { enabled: e.target.checked })
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
                      onUpdate(index, {
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
                      onUpdate(index, {
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
                  <span 
                    className="metadata-item prompt-file-link"
                    onClick={() => onOpenPromptEditor?.(agent.prompt_file)}
                    role="button"
                    tabIndex={0}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter' || e.key === ' ') {
                        e.preventDefault();
                        onOpenPromptEditor?.(agent.prompt_file);
                      }
                    }}
                  >
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
  );
}
