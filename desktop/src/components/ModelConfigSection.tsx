/**
 * Model configuration section extracted from SettingsPage.
 *
 * Handles A/B testing toggle, default/fallback model selectors,
 * and the candidate model chip input with datalist suggestions.
 */

interface Props {
  abTestingEnabled: boolean;
  onAbToggle: (enabled: boolean) => void;
  defaultModel: string;
  onDefaultModelChange: (value: string) => void;
  fallbackModel: string;
  onFallbackModelChange: (value: string) => void;
  candidateModels: string[];
  chipInput: string;
  onChipInputChange: (value: string) => void;
  onAddChip: (value: string) => void;
  onAddAllCandidateModels: () => void;
  onRemoveChip: (model: string) => void;
  onChipKeyDown: (e: React.KeyboardEvent<HTMLInputElement>) => void;
  availableModels: string[];
}

export function ModelConfigSection({
  abTestingEnabled,
  onAbToggle,
  defaultModel,
  onDefaultModelChange,
  fallbackModel,
  onFallbackModelChange,
  candidateModels,
  chipInput,
  onChipInputChange,
  onAddChip,
  onAddAllCandidateModels,
  onRemoveChip,
  onChipKeyDown,
  availableModels,
}: Props) {
  const suggestions = availableModels.filter(
    (m) => !candidateModels.includes(m) && m.toLowerCase().includes(chipInput.toLowerCase()),
  );

  const showAddAll = abTestingEnabled && availableModels.some((m) => !candidateModels.includes(m));

  return (
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
            onChange={(e) => onAbToggle(e.target.checked)}
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
          onChange={(e) => onDefaultModelChange(e.target.value)}
          placeholder="e.g. claude-sonnet-4.5"
        />
        <datalist id="default-model-suggestions">
          {availableModels.map((m) => (
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
          onChange={(e) => onFallbackModelChange(e.target.value)}
          placeholder="e.g. claude-sonnet-4"
        />
        <datalist id="fallback-model-suggestions">
          {availableModels.map((m) => (
            <option key={m} value={m} />
          ))}
        </datalist>
        <span className="settings-hint">Used when the default model is unavailable</span>
      </div>

      {/* Candidate Models (tag chips) */}
      <div className="settings-field">
        <div className="settings-label-row">
          <label className="settings-label">A/B Candidate Models</label>
          {showAddAll && (
            <button type="button" className="add-all-btn" onClick={onAddAllCandidateModels}>
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
                onClick={() => onRemoveChip(m)}
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
              onChange={(e) => onChipInputChange(e.target.value)}
              onKeyDown={onChipKeyDown}
              onBlur={() => {
                if (chipInput.trim()) onAddChip(chipInput);
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
  );
}
