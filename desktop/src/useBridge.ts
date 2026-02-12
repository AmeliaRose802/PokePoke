/**
 * pywebview bridge hook for the PokePoke desktop app.
 *
 * Communicates with the Python orchestrator via direct in-process
 * method calls through window.pywebview.api — no WebSocket, no server.
 *
 * The frontend polls for new logs/state on a fast timer. The Python
 * side buffers everything and the poll returns only new entries since
 * the last call (incremental).
 */

import { useEffect, useState, useCallback } from "react";
import type {
  LogEntry,
  WorkItem,
  SessionStats,
  ProgressState,
  ConnectionStatus,
  ModelPerformanceSummary,
} from "./types";

/** Poll interval in ms — 100ms = responsive without hammering */
const POLL_INTERVAL_MS = 100;
const MAX_LOG_ENTRIES = 2000;

/** pywebview injects this on the window object */
interface PyWebViewAPI {
  get_state(): Promise<{
    work_item: WorkItem | null;
    agent_name: string;
    stats: SessionStats | null;
    progress: ProgressState;
    log_count: number;
    model_leaderboard: Record<string, ModelPerformanceSummary>;
  }>;
  get_new_logs(): Promise<LogEntry[]>;
  get_all_logs(): Promise<LogEntry[]>;
  get_work_item(): Promise<WorkItem | null>;
  get_stats(): Promise<SessionStats | null>;
}

declare global {
  interface Window {
    pywebview?: {
      api: PyWebViewAPI;
    };
  }
}

export interface BridgeState {
  connectionStatus: ConnectionStatus;
  orchestratorLogs: LogEntry[];
  agentLogs: LogEntry[];
  workItem: WorkItem | null;
  agentName: string;
  stats: SessionStats | null;
  progress: ProgressState;
  modelLeaderboard: Record<string, ModelPerformanceSummary>;
  clearLogs: (target: "orchestrator" | "agent" | "all") => void;
}

/**
 * React hook that polls the Python DesktopAPI for orchestrator state.
 * Direct in-process calls via pywebview — no network, no server.
 */
export function useBridge(): BridgeState {
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
  const [modelLeaderboard, setModelLeaderboard] = useState<Record<string, ModelPerformanceSummary>>({});

  const clearLogs = useCallback(
    (target: "orchestrator" | "agent" | "all") => {
      if (target === "orchestrator" || target === "all")
        setOrchestratorLogs([]);
      if (target === "agent" || target === "all") setAgentLogs([]);
    },
    []
  );

  const appendLogs = useCallback((entries: LogEntry[]) => {
    if (entries.length === 0) return;

    // Split into orchestrator and agent logs
    const orchLogs: LogEntry[] = [];
    const agLogs: LogEntry[] = [];
    for (const e of entries) {
      if (e.target === "agent") {
        agLogs.push(e);
      } else {
        orchLogs.push(e);
      }
    }

    if (orchLogs.length > 0) {
      setOrchestratorLogs((prev) => {
        const next = [...prev, ...orchLogs];
        return next.length > MAX_LOG_ENTRIES
          ? next.slice(next.length - MAX_LOG_ENTRIES)
          : next;
      });
    }
    if (agLogs.length > 0) {
      setAgentLogs((prev) => {
        const next = [...prev, ...agLogs];
        return next.length > MAX_LOG_ENTRIES
          ? next.slice(next.length - MAX_LOG_ENTRIES)
          : next;
      });
    }
  }, []);

  useEffect(() => {
    let timer: ReturnType<typeof setInterval> | null = null;
    let stopped = false;

    async function waitForApi(): Promise<PyWebViewAPI> {
      // pywebview injects window.pywebview after the page loads
      while (!window.pywebview?.api && !stopped) {
        await new Promise((r) => setTimeout(r, 50));
      }
      return window.pywebview!.api;
    }

    async function start() {
      const api = await waitForApi();
      if (stopped) return;

      // Initial load — get full state + all buffered logs
      try {
        const state = await api.get_state();
        if (state.work_item) setWorkItem(state.work_item);
        if (state.agent_name) setAgentName(state.agent_name);
        if (state.stats) setStats(state.stats);
        if (state.progress) setProgress(state.progress);
        if (state.model_leaderboard) setModelLeaderboard(state.model_leaderboard);

        const allLogs = await api.get_all_logs();
        appendLogs(allLogs);

        setConnectionStatus("connected");
      } catch {
        setConnectionStatus("disconnected");
        return;
      }

      // Poll for incremental updates
      timer = setInterval(async () => {
        if (stopped) return;
        try {
          // Get new logs (incremental — only entries since last poll)
          const newLogs = await api.get_new_logs();
          appendLogs(newLogs);

          // Get current state
          const state = await api.get_state();
          setWorkItem(state.work_item);
          setAgentName(state.agent_name);
          if (state.stats) setStats(state.stats);
          if (state.progress) setProgress(state.progress);
          if (state.model_leaderboard) setModelLeaderboard(state.model_leaderboard);

          setConnectionStatus("connected");
        } catch {
          setConnectionStatus("disconnected");
        }
      }, POLL_INTERVAL_MS);
    }

    start();

    return () => {
      stopped = true;
      if (timer) clearInterval(timer);
    };
  }, [appendLogs]);

  return {
    connectionStatus,
    orchestratorLogs,
    agentLogs,
    workItem,
    agentName,
    stats,
    progress,
    modelLeaderboard,
    clearLogs,
  };
}
