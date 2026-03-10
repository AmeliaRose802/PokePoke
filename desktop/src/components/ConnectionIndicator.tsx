/**
 * Connection status indicator.
 *
 * Shows the orchestrator process state with a colored dot.
 */

import type { ConnectionStatus } from "../types";

interface Props {
  status: ConnectionStatus;
}

const STATUS_CONFIG: Record<ConnectionStatus, { label: string; pulse: boolean }> = {
  connecting: { label: "Connecting...", pulse: true },
  connected: { label: "Running", pulse: false },
  disconnected: { label: "Stopped", pulse: true },
};

export function ConnectionIndicator({ status }: Props) {
  const config = STATUS_CONFIG[status];

  return (
    <div className="connection-indicator">
      <span className={`connection-dot connection-dot-${status} ${config.pulse ? "pulse" : ""}`} />
      <span className="connection-label">{config.label}</span>
    </div>
  );
}
