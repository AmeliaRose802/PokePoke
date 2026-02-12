/**
 * Work item header component.
 *
 * Displays the current work item ID, title, status badge,
 * and active agent name with an animated spinner.
 */

import { useEffect, useState } from "react";
import type { WorkItem } from "../types";

const SPINNER_FRAMES = ["◐", "◓", "◑", "◒"];

interface Props {
  workItem: WorkItem | null;
  agentName: string;
}

export function WorkItemHeader({ workItem, agentName }: Props) {
  const [frame, setFrame] = useState(0);

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

  return (
    <header className="work-item-header">
      <div className="work-item-id-line">
        <span className="ticket-icon">🎫</span>
        <span className="item-id">{workItem?.item_id ?? "PokePoke"}</span>
        <span className="separator">│</span>
        <span className="item-title">
          {workItem?.title ?? "Waiting for orchestrator..."}
        </span>
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
    </header>
  );
}
