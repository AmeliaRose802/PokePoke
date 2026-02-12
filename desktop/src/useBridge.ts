/**
 * WebSocket hook for connecting to the PokePoke orchestrator bridge.
 *
 * Manages connection lifecycle, auto-reconnection, and message parsing.
 * Provides a clean React interface to the live orchestrator state.
 */

import { useEffect, useRef, useState, useCallback } from "react";
import type {
  LogEntry,
  WorkItem,
  SessionStats,
  ProgressState,
  ConnectionStatus,
  BridgeMessage,
} from "./types";

const DEFAULT_WS_URL = "ws://127.0.0.1:9160";
const RECONNECT_DELAY_MS = 2000;
const MAX_LOG_ENTRIES = 2000;

export interface BridgeState {
  /** WebSocket connection status */
  connectionStatus: ConnectionStatus;
  /** Orchestrator log entries */
  orchestratorLogs: LogEntry[];
  /** Agent log entries */
  agentLogs: LogEntry[];
  /** Current work item being processed */
  workItem: WorkItem | null;
  /** Current agent name */
  agentName: string;
  /** Live session statistics */
  stats: SessionStats | null;
  /** Progress indicator state */
  progress: ProgressState;
  /** Clear logs for a specific panel */
  clearLogs: (target: "orchestrator" | "agent" | "all") => void;
}

/**
 * React hook that connects to the PokePoke WebSocket bridge and
 * provides live orchestrator state.
 *
 * @param wsUrl - WebSocket URL (default: ws://127.0.0.1:9160)
 * @returns BridgeState with live data and helper methods
 */
export function useBridge(wsUrl: string = DEFAULT_WS_URL): BridgeState {
  const [connectionStatus, setConnectionStatus] =
    useState<ConnectionStatus>("connecting");
  const [orchestratorLogs, setOrchestratorLogs] = useState<LogEntry[]>([]);
  const [agentLogs, setAgentLogs] = useState<LogEntry[]>([]);
  const [workItem, setWorkItem] = useState<WorkItem | null>(null);
  const [agentName, setAgentName] = useState("");
  const [stats, setStats] = useState<SessionStats | null>(null);
  const [progress, setProgress] = useState<ProgressState>({
    active: false,
    status: "",
  });

  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const clearLogs = useCallback(
    (target: "orchestrator" | "agent" | "all") => {
      if (target === "orchestrator" || target === "all") {
        setOrchestratorLogs([]);
      }
      if (target === "agent" || target === "all") {
        setAgentLogs([]);
      }
    },
    []
  );

  const appendLog = useCallback((entry: LogEntry) => {
    const setter =
      entry.target === "agent" ? setAgentLogs : setOrchestratorLogs;
    setter((prev) => {
      const next = [...prev, entry];
      // Trim to max buffer size
      return next.length > MAX_LOG_ENTRIES
        ? next.slice(next.length - MAX_LOG_ENTRIES)
        : next;
    });
  }, []);

  const handleMessage = useCallback(
    (event: MessageEvent) => {
      try {
        const msg: BridgeMessage = JSON.parse(event.data);

        switch (msg.type) {
          case "connected":
            setConnectionStatus("connected");
            break;

          case "log":
            appendLog(msg.data as LogEntry);
            break;

          case "work_item":
            setWorkItem(msg.data as WorkItem);
            break;

          case "stats":
            setStats(msg.data as SessionStats);
            break;

          case "agent_name":
            setAgentName((msg.data as { name: string }).name);
            break;

          case "progress":
            setProgress(msg.data as ProgressState);
            break;
        }
      } catch {
        // Ignore malformed messages
      }
    },
    [appendLog]
  );

  const connect = useCallback(() => {
    // Clean up any existing connection
    if (wsRef.current) {
      wsRef.current.close();
    }

    setConnectionStatus("connecting");
    const ws = new WebSocket(wsUrl);

    ws.onopen = () => {
      setConnectionStatus("connected");
    };

    ws.onmessage = handleMessage;

    ws.onclose = () => {
      setConnectionStatus("disconnected");
      // Auto-reconnect after delay
      reconnectTimerRef.current = setTimeout(() => {
        connect();
      }, RECONNECT_DELAY_MS);
    };

    ws.onerror = () => {
      // onclose will fire after this, triggering reconnect
    };

    wsRef.current = ws;
  }, [wsUrl, handleMessage]);

  useEffect(() => {
    connect();

    return () => {
      // Cleanup on unmount
      if (reconnectTimerRef.current) {
        clearTimeout(reconnectTimerRef.current);
      }
      if (wsRef.current) {
        wsRef.current.close();
      }
    };
  }, [connect]);

  return {
    connectionStatus,
    orchestratorLogs,
    agentLogs,
    workItem,
    agentName,
    stats,
    progress,
    clearLogs,
  };
}
