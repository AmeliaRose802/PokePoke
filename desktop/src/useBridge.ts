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
   ModelHistoryEntry,
   AgentInfo,
  PromptInfo,
  PromptDetail,
  ConfigResponse,
  ProjectConfig,
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
    agents: AgentInfo[];
    stop_after_current: boolean;
    project_name: string;
  }>;
  get_new_logs(): Promise<LogEntry[]>;
  get_all_logs(): Promise<LogEntry[]>;
  get_work_item(): Promise<WorkItem | null>;
  get_stats(): Promise<SessionStats | null>;
  get_model_history(limit?: number): Promise<ModelHistoryEntry[]>;
  list_prompts(): Promise<PromptInfo[]>;
  get_prompt(name: string): Promise<PromptDetail>;
  save_prompt(name: string, content: string): Promise<{ path: string; saved: boolean }>;
  reset_prompt(name: string): Promise<{ reset: boolean; had_override: boolean }>;
  get_config(): Promise<ConfigResponse>;
  save_config(config: ProjectConfig): Promise<{ path: string; saved: boolean }>;
  request_stop_after_current(): Promise<{ stop_after_current: boolean }>;
  cancel_stop_after_current(): Promise<{ stop_after_current: boolean }>;
  get_agent_detail(agent_id: string): Promise<AgentInfo | null>;
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
  projectName: string;
  stats: SessionStats | null;
  progress: ProgressState;
  modelLeaderboard: Record<string, ModelPerformanceSummary>;
  agents: AgentInfo[];
  stopAfterCurrent: boolean;
  clearLogs: (target: "orchestrator" | "agent" | "all") => void;
  listPrompts: () => Promise<PromptInfo[]>;
  getPrompt: (name: string) => Promise<PromptDetail | null>;
  savePrompt: (name: string, content: string) => Promise<boolean>;
  resetPrompt: (name: string) => Promise<boolean>;
  getConfig: () => Promise<ConfigResponse | null>;
  saveConfig: (config: ProjectConfig) => Promise<boolean>;
  getModelHistory: (limit?: number) => Promise<ModelHistoryEntry[]>;
  requestStopAfterCurrent: () => Promise<void>;
  cancelStopAfterCurrent: () => Promise<void>;
  getAgentDetail: (agentId: string) => Promise<AgentInfo | null>;
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
  const [projectName, setProjectName] = useState("");
  const [stats, setStats] = useState<SessionStats | null>(null);
  const [progress, setProgress] = useState<ProgressState>({
    active: false,
    status: "",
  });
  const [modelLeaderboard, setModelLeaderboard] = useState<Record<string, ModelPerformanceSummary>>({});
  const [agents, setAgents] = useState<AgentInfo[]>([]);
  const [stopAfterCurrent, setStopAfterCurrent] = useState(false);

  const clearLogs = useCallback(
    (target: "orchestrator" | "agent" | "all") => {
      if (target === "orchestrator" || target === "all")
        setOrchestratorLogs([]);
      if (target === "agent" || target === "all") setAgentLogs([]);
    },
    []
  );

  const listPrompts = useCallback(async (): Promise<PromptInfo[]> => {
    if (!window.pywebview?.api) return [];
    return window.pywebview.api.list_prompts();
  }, []);

  const getPrompt = useCallback(async (name: string): Promise<PromptDetail | null> => {
    if (!window.pywebview?.api) return null;
    return window.pywebview.api.get_prompt(name);
  }, []);

  const savePrompt = useCallback(async (name: string, content: string): Promise<boolean> => {
    if (!window.pywebview?.api) return false;
    const result = await window.pywebview.api.save_prompt(name, content);
    return result.saved;
  }, []);

  const resetPrompt = useCallback(async (name: string): Promise<boolean> => {
    if (!window.pywebview?.api) return false;
    const result = await window.pywebview.api.reset_prompt(name);
    return result.reset;
  }, []);

  const getConfig = useCallback(async (): Promise<ConfigResponse | null> => {
    if (!window.pywebview?.api) return null;
    return window.pywebview.api.get_config();
  }, []);

  const saveConfig = useCallback(async (config: ProjectConfig): Promise<boolean> => {
    if (!window.pywebview?.api) return false;
    const result = await window.pywebview.api.save_config(config);
    return result.saved;
  }, []);

  const getModelHistory = useCallback(
    async (limit = 200): Promise<ModelHistoryEntry[]> => {
      if (!window.pywebview?.api) return [];
      try {
        return await window.pywebview.api.get_model_history(limit);
      } catch {
        return [];
      }
    },
    []
  );

  const requestStopAfterCurrent = useCallback(async (): Promise<void> => {
    if (!window.pywebview?.api) return;
    await window.pywebview.api.request_stop_after_current();
    setStopAfterCurrent(true);
  }, []);

  const cancelStopAfterCurrent = useCallback(async (): Promise<void> => {
    if (!window.pywebview?.api) return;
    await window.pywebview.api.cancel_stop_after_current();
    setStopAfterCurrent(false);
  }, []);

  const getAgentDetail = useCallback(async (agentId: string): Promise<AgentInfo | null> => {
    if (!window.pywebview?.api) return null;
    try {
      return await window.pywebview.api.get_agent_detail(agentId);
    } catch {
      return null;
    }
  }, []);

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
        if (state.project_name) setProjectName(state.project_name);
        if (state.stats) setStats(state.stats);
        if (state.progress) setProgress(state.progress);
        if (state.model_leaderboard) setModelLeaderboard(state.model_leaderboard);
        if (state.agents) setAgents(state.agents);
        setStopAfterCurrent(!!state.stop_after_current);

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
          if (state.project_name !== undefined) setProjectName(state.project_name);
          if (state.stats) setStats(state.stats);
          if (state.progress) setProgress(state.progress);
          if (state.model_leaderboard) setModelLeaderboard(state.model_leaderboard);
          if (state.agents) setAgents(state.agents);
          setStopAfterCurrent(!!state.stop_after_current);

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
    projectName,
    stats,
    progress,
    modelLeaderboard,
    agents,
    stopAfterCurrent,
    clearLogs,
    listPrompts,
    getPrompt,
    savePrompt,
    resetPrompt,
    getConfig,
    saveConfig,
    getModelHistory,
    requestStopAfterCurrent,
    cancelStopAfterCurrent,
    getAgentDetail,
  };
}
