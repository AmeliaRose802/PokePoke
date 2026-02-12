/**
 * Connection status indicator.
 *
 * Shows the WebSocket bridge connection state with a colored dot
 * and reconnection info.
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
  connected: { color: "#5cb85c", label: "Connected", pulse: false },
  disconnected: { color: "#d9534f", label: "Disconnected", pulse: true },
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
