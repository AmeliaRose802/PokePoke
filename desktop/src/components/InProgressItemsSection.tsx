import type { InProgressItem } from "../utils/inProgressItems";

export function InProgressItemsSection({ items }: { items: InProgressItem[] }) {
  if (items.length === 0) return null;
  return (
    <div className="stats-panel-card">
      <h3>In progress <span className="stats-panel-subtitle">Active work items</span></h3>
      <ul className="in-progress-items-list">
        {items.map((item) => (
          <InProgressItemCard key={item.id} item={item} />
        ))}
      </ul>
    </div>
  );
}

function InProgressItemCard({ item }: { item: InProgressItem }) {
  const agentLabels = item.agents.map((agent) => {
    const base = `${agent.name} v${agent.iteration}`;
    return agent.paused ? `${base} (paused)` : base;
  });

  return (
    <li className="in-progress-item-card">
      <div className="in-progress-item-header">
        <strong>{item.id}</strong>
        {item.title && <span className="in-progress-item-title">{item.title}</span>}
      </div>
      {agentLabels.length > 0 && (
        <div className="completed-item-stats">
          <span className="item-stat">
            <span className="item-stat-label">Agents:</span>
            <span className="item-stat-value">{agentLabels.join(", ")}</span>
          </span>
        </div>
      )}
    </li>
  );
}
