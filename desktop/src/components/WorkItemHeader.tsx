/**
 * Work item header component.
 *
 * Displays the current work item ID, title, status badge,
 * repository name, and active agent name with an animated spinner.
 */

import { useEffect, useState } from "react";

import type { WorkItem } from "../types";

const SPINNER_FRAMES = ["◐", "◓", "◑", "◒"];

const SPECIAL_EFFECT_TAGS = [
  {
    id: "human-required",
    label: "Human required",
    description: "Skip this item until a human can handle it.",
  },
  {
    id: "high-conflict-risk",
    label: "High conflict risk",
    description: "Runs serially to avoid merge conflicts.",
  },
];

const SPECIAL_TAG_IDS = new Set(SPECIAL_EFFECT_TAGS.map((tag) => tag.id));

interface Props {
  workItem: WorkItem | null;
  agentName: string;
  repositoryName: string;
  onAddLabel?: (label: string) => Promise<void>;
  onRemoveLabel?: (label: string) => Promise<void>;
}

export function WorkItemHeader({
  workItem,
  agentName,
  repositoryName,
  onAddLabel,
  onRemoveLabel,
}: Props) {
  const [frame, setFrame] = useState(0);
  const [pendingTag, setPendingTag] = useState<string | null>(null);

  useEffect(() => {
    if (!agentName) return;
    const id = setInterval(() => {
      setFrame((f) => (f + 1) % SPINNER_FRAMES.length);
    }, 250);
    return () => clearInterval(id);
  }, [agentName]);

  const statusClass = workItem?.status
    ? `status-${workItem.status.toLowerCase().replace(/\s+/g, "-")}`
    : "";
  const labels = workItem?.labels ?? [];
  const isBeadsItem = !!workItem?.item_id?.startsWith("PokePoke-");
  const canEditTags = !!workItem && isBeadsItem && onAddLabel && onRemoveLabel;
  const specialTagsApplied = labels.filter((label) => SPECIAL_TAG_IDS.has(label));

  const handleToggleTag = async (tagId: string, isActive: boolean) => {
    if (!canEditTags || !workItem) return;
    setPendingTag(tagId);
    try {
      if (isActive) {
        await onRemoveLabel?.(tagId);
      } else {
        await onAddLabel?.(tagId);
      }
    } catch (error) {
      console.error("Failed to update work item tag:", error);
    } finally {
      setPendingTag(null);
    }
  };

  const tagHint = !workItem
    ? "Waiting for a work item..."
    : !isBeadsItem
      ? "Special-effect tags are only editable for beads items."
      : "Toggle these to adjust how the orchestrator handles this item.";

  return (
    <header className="work-item-header">
      <div className="work-item-id-line">
        <span className="ticket-icon">🎫</span>
        <span className="item-id">{workItem?.item_id ?? "PokePoke"}</span>
        <span className="separator">│</span>
        <span className="item-title">
          {workItem?.title ?? "Waiting for orchestrator..."}
        </span>
        {repositoryName && (
          <>
            <span className="separator">│</span>
            <span className="repository-name">📁 {repositoryName}</span>
          </>
        )}
      </div>
      <div className="work-item-meta-line">
        {workItem?.status && (
          <span className={`status-badge ${statusClass}`}>
            [{workItem.status.toUpperCase()}]
          </span>
        )}
        {agentName && (
          <span className="agent-name">
            <span className="agent-spinner">{SPINNER_FRAMES[frame]}</span>{" "}
            {agentName}
          </span>
        )}
      </div>
      {labels.length > 0 && (
        <div className="work-item-labels">
          <span className="labels-title">Tags</span>
          <div className="label-chips">
            {labels.map((label) => (
              <span
                key={label}
                className={`label-chip${SPECIAL_TAG_IDS.has(label) ? " label-chip-special" : ""}`}
              >
                {label}
              </span>
            ))}
          </div>
        </div>
      )}
      <div className="special-tags-section">
        <div className="special-tags-header">
          <span className="special-tags-title">Special-effect tags</span>
          {specialTagsApplied.length > 0 && (
            <span className="special-tags-active">
              Applied: {specialTagsApplied.join(", ")}
            </span>
          )}
        </div>
        <div className="special-tags-note">{tagHint}</div>
        <div className="special-tags-grid">
          {SPECIAL_EFFECT_TAGS.map((tag) => {
            const isActive = labels.includes(tag.id);
            const isPending = pendingTag === tag.id;
            return (
              <div
                key={tag.id}
                className={`special-tag-card${isActive ? " active" : ""}`}
              >
                <div className="special-tag-header">
                  <span className="special-tag-name">{tag.label}</span>
                  {isActive && <span className="special-tag-badge">Applied</span>}
                </div>
                <div className="special-tag-description">{tag.description}</div>
                <div className="special-tag-actions">
                  <button
                    className={`special-tag-toggle${isActive ? " active" : ""}`}
                    type="button"
                    onClick={() => handleToggleTag(tag.id, isActive)}
                    disabled={!canEditTags || isPending}
                  >
                    {isPending
                      ? "Updating..."
                      : isActive
                        ? "Remove tag"
                        : "Add tag"}
                  </button>
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </header>
  );
}
