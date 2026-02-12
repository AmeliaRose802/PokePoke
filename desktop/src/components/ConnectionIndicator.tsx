/**
 * Connection status indicator.
 *
 * Shows the orchestrator process state with a colored dot.
 */

import type { ConnectionStatus } from "../types";

interface Props {
  status: ConnectionStatus;
}

const STATUS_CONFIG: Record<
  ConnectionStatus,
  { color: string; label: string; pulse: boolean }
> = {
  connecting: { color: "#f0ad4e", label: "Connecting...", pulse: true },
  connected: { color: "#5cb85c", label: "Running", pulse: false },
  disconnected: { color: "#d9534f", label: "Stopped", pulse: true },
};

export function ConnectionIndicator({ status }: Props) {
  const config = STATUS_CONFIG[status];

  return (
    <div className="connection-indicator">
      <span
        className={`connection-dot ${config.pulse ? "pulse" : ""}`}
        style={{ backgroundColor: config.color }}
      />
      <span className="connection-label">{config.label}</span>
    </div>
  );
}
