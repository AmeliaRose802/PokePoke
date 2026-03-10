/** Special-effect tag reference cards for the Settings page. */

const SPECIAL_EFFECT_TAGS = [
  { id: "human-required", label: "Human required", description: "Skip this item until a human can handle it." },
  { id: "high-conflict-risk", label: "High conflict risk", description: "Runs serially to avoid merge conflicts." },
];

export function SpecialEffectTagsSection() {
  return (
    <div className="settings-section">
      <h3 className="settings-section-title">🏷️ Special-Effect Tags</h3>
      <p className="settings-hint">
        These tags modify how the orchestrator handles individual beads work items. They represent global orchestrator
        behaviors, not per-agent settings.
      </p>
      <div className="special-tags-grid">
        {SPECIAL_EFFECT_TAGS.map((tag) => (
          <div key={tag.id} className="special-tag-card">
            <div className="special-tag-header">
              <span className="special-tag-name">{tag.label}</span>
              <code
                className="special-tag-id copyable"
                title="Click to copy tag ID"
                onClick={() => navigator.clipboard.writeText(tag.id)}
              >
                {tag.id} 📋
              </code>
            </div>
            <div className="special-tag-description">{tag.description}</div>
          </div>
        ))}
      </div>
    </div>
  );
}
