import type { CompletedItem, ModelHistoryEntry } from "../types";
import { formatCost,formatDurationShort, formatTokens } from "../utils/stats";

interface CompletedItemCardProps {
  item: CompletedItem;
  modelHistory: ModelHistoryEntry[];
}

interface ItemStats {
  model: string;
  duration_seconds: number;
  gate_passed: boolean | null;
  attempts: number;
  input_tokens?: number;
  output_tokens?: number;
  agent_turns?: number;
  cost?: number;
}

function getItemStats(itemId: string, history: ModelHistoryEntry[]): ItemStats | null {
  // Find all entries for this item
  const itemEntries = history.filter(entry => entry.item_id === itemId);
  if (itemEntries.length === 0) return null;

  // Get the most recent entry (last in the array)
  const latest = itemEntries[itemEntries.length - 1] as ModelHistoryEntry & {
    input_tokens?: number;
    output_tokens?: number;
    agent_turns?: number;
    cost?: number;
  };

  return {
    model: latest.model,
    duration_seconds: latest.duration_seconds,
    gate_passed: latest.gate_passed,
    attempts: itemEntries.length,
    input_tokens: latest.input_tokens,
    output_tokens: latest.output_tokens,
    agent_turns: latest.agent_turns,
    cost: latest.cost,
  };
}

const gateStatusText = (v: boolean | null) =>
  v === true ? "Passed gate" : v === false ? "Failed gate" : "Pending";

const statusClass = (v: boolean | null) =>
  v === true ? "status-pass" : v === false ? "status-fail" : "status-neutral";

export function CompletedItemCard({ item, modelHistory }: CompletedItemCardProps) {
  const itemStats = getItemStats(item.id, modelHistory);

  return (
    <li className="completed-item-card">
      <div className="completed-item-header">
        <strong>{item.id}</strong>
        {item.title && <span className="completed-item-title">{item.title}</span>}
      </div>
      {itemStats && (
        <div className="completed-item-stats">
          <span className="item-stat">
            <span className="item-stat-label">Model:</span>
            <span className="item-stat-value">{itemStats.model}</span>
          </span>
          <span className="item-stat">
            <span className="item-stat-label">Duration:</span>
            <span className="item-stat-value">{formatDurationShort(itemStats.duration_seconds)}</span>
          </span>
          <span className="item-stat">
            <span className="item-stat-label">Status:</span>
            <span className={`item-stat-value ${statusClass(itemStats.gate_passed)}`}>
              {gateStatusText(itemStats.gate_passed)}
            </span>
          </span>
          {itemStats.attempts > 1 && (
            <span className="item-stat">
              <span className="item-stat-label">Attempts:</span>
              <span className="item-stat-value">{itemStats.attempts}</span>
            </span>
          )}
          {typeof itemStats.agent_turns === 'number' && itemStats.agent_turns > 0 && (
            <span className="item-stat">
              <span className="item-stat-label">Agent Turns:</span>
              <span className="item-stat-value">{itemStats.agent_turns}</span>
            </span>
          )}
          {typeof itemStats.input_tokens === 'number' && typeof itemStats.output_tokens === 'number' && (
            <span className="item-stat">
              <span className="item-stat-label">Tokens:</span>
              <span className="item-stat-value">
                {formatTokens(itemStats.input_tokens + itemStats.output_tokens)}
                <span className="item-stat-detail"> ({formatTokens(itemStats.input_tokens)} in / {formatTokens(itemStats.output_tokens)} out)</span>
              </span>
            </span>
          )}
          {typeof itemStats.cost === 'number' && itemStats.cost > 0 && (
            <span className="item-stat">
              <span className="item-stat-label">Cost:</span>
              <span className="item-stat-value">{formatCost(itemStats.cost)}</span>
            </span>
          )}
        </div>
      )}
    </li>
  );
}
