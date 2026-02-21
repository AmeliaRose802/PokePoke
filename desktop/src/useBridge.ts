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

import { useCallback,useEffect, useState } from "react";

import type {
   AgentInfo,
  ConfigResponse,
  ConnectionStatus,
  LogEntry,
   ModelHistoryEntry,
   ModelPerformanceSummary,
  ProgressState,
  ProjectConfig,
  PromptDetail,
  PromptInfo,
  SessionStats,
  WorkItem,
} from "./types";

/** Poll interval in ms — 100ms = responsive without hammering */
const POLL_INTERVAL_MS = 100;

/**
 * Shallow-compare two values to avoid unnecessary setState calls.
 * Prevents React re-renders that clear native text selection.
 */
export function shallowEqual(a: unknown, b: unknown): boolean {
  if (Object.is(a, b)) return true;
  if (typeof a !== 'object' || typeof b !== 'object' || a === null || b === null) return false;
  const keysA = Object.keys(a as Record<string, unknown>);
  const keysB = Object.keys(b as Record<string, unknown>);
  if (keysA.length !== keysB.length) return false;
  for (const key of keysA) {
    if (!Object.is((a as Record<string, unknown>)[key], (b as Record<string, unknown>)[key])) return false;
  }
  return true;
}

/** setState wrapper that skips update when value is shallow-equal to current */
function setIfChanged<T>(setter: React.Dispatch<React.SetStateAction<T>>): (value: T) => void {
  return (value: T) => {
    setter(prev => shallowEqual(prev, value) ? prev : value);
  };
}

/** Retry configuration for initial state load */
const INITIAL_RETRY_CONFIG = {
  MAX_RETRIES: 10,
  BASE_DELAY_MS: 200,
  MAX_DELAY_MS: 2000,
  BACKOFF_MULTIPLIER: 1.5,
};

/** Configuration for polling timer resilience */
const POLL_RESILIENCE_CONFIG = {
  MAX_CONSECUTIVE_FAILURES: 5,
};

/** pywebview injects this on the window object */
interface PyWebViewAPI {
  get_state(): Promise<{
    work_item: WorkItem | null;
    agent_name: string;
    repository_name: string;
    stats: SessionStats | null;
    progress: ProgressState;
    log_count: number;
    model_leaderboard: Record<string, ModelPerformanceSummary>;
    agents: AgentInfo[];
    stop_after_current: boolean;
    project_name: string;
    current_session_id: string | null;
  }>;
  get_new_logs(): Promise<LogEntry[]>;
  get_all_logs(): Promise<LogEntry[]>;
  get_work_item(): Promise<WorkItem | null>;
  get_repository_name(): Promise<string>;
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
  pause_agent(agent_id: string): Promise<{ agent_id: string; paused: boolean }>;
  resume_agent(agent_id: string): Promise<{ agent_id: string; resumed: boolean }>;
  spawn_agent(): Promise<{ success: boolean; at_limit: boolean; active: number; max: number }>;
}

declare global {
  interface Window {
    pywebview?: {
      api: PyWebViewAPI;
    };
  }
}

/**
 * Sleeps for the specified number of milliseconds
 */
function sleep(ms: number): Promise<void> {
  return new Promise(resolve => setTimeout(resolve, ms));
}

/**
 * Retries an async function with exponential backoff
 */
async function retryWithBackoff<T>(
  fn: () => Promise<T>,
  config = INITIAL_RETRY_CONFIG
): Promise<T> {
  let lastError: Error | null = null;
  let delay = config.BASE_DELAY_MS;
  
  for (let attempt = 0; attempt <= config.MAX_RETRIES; attempt++) {
    try {
      return await fn();
    } catch (error) {
      lastError = error instanceof Error ? error : new Error(String(error));
      
      // If this was our last attempt, throw the error
      if (attempt === config.MAX_RETRIES) {
        throw lastError;
      }
      
      // Wait before retrying (exponential backoff with max delay)
      await sleep(Math.min(delay, config.MAX_DELAY_MS));
      delay = Math.floor(delay * config.BACKOFF_MULTIPLIER);
    }
  }
  
  throw lastError || new Error('Retry failed');
}

export interface BridgeState {
  connectionStatus: ConnectionStatus;
  orchestratorLogs: LogEntry[];
  agentLogs: LogEntry[];
  workItem: WorkItem | null;
  agentName: string;
  repositoryName: string;
  projectName: string;
  stats: SessionStats | null;
  progress: ProgressState;
  modelLeaderboard: Record<string, ModelPerformanceSummary>;
  agents: AgentInfo[];
  stopAfterCurrent: boolean;
  currentSessionId: string | null;
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
  pauseAgent: (agentId: string) => Promise<boolean>;
  resumeAgent: (agentId: string) => Promise<boolean>;
  spawnAgent: () => Promise<{ success: boolean; at_limit: boolean; active: number; max: number } | null>;
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
  const [repositoryName, setRepositoryName] = useState("");
  const [projectName, setProjectName] = useState("");
  const [stats, setStats] = useState<SessionStats | null>(null);
  const [progress, setProgress] = useState<ProgressState>({
    active: false,
    status: "",
  });
  const [modelLeaderboard, setModelLeaderboard] = useState<Record<string, ModelPerformanceSummary>>({});
  const [agents, setAgents] = useState<AgentInfo[]>([]);
  const [stopAfterCurrent, setStopAfterCurrent] = useState(false);
  const [currentSessionId, setCurrentSessionId] = useState<string | null>(null);

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

  const pauseAgent = useCallback(async (agentId: string): Promise<boolean> => {
    if (!window.pywebview?.api) return false;
    try {
      const result = await window.pywebview.api.pause_agent(agentId);
      return result.paused;
    } catch {
      return false;
    }
  }, []);

  const resumeAgent = useCallback(async (agentId: string): Promise<boolean> => {
    if (!window.pywebview?.api) return false;
    try {
      const result = await window.pywebview.api.resume_agent(agentId);
      return result.resumed;
    } catch {
      return false;
    }
  }, []);

  const spawnAgent = useCallback(async () => {
    if (!window.pywebview?.api) return null;
    try {
      return await window.pywebview.api.spawn_agent();
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
      setOrchestratorLogs((prev) => [...prev, ...orchLogs]);
    }
    if (agLogs.length > 0) {
      setAgentLogs((prev) => [...prev, ...agLogs]);
    }
  }, []);

  useEffect(() => {
    let timer: ReturnType<typeof setInterval> | null = null;
    let stopped = false;
    let consecutiveFailures = 0;

    async function waitForApi(): Promise<PyWebViewAPI> {
      // pywebview injects window.pywebview after the page loads
      while (!window.pywebview?.api && !stopped) {
        await new Promise((r) => setTimeout(r, 50));
      }
      return window.pywebview!.api;
    }

    async function loadInitialState(api: PyWebViewAPI): Promise<void> {
      // Use retry with backoff for the initial state load
      const state = await retryWithBackoff(async () => {
        return await api.get_state();
      });
      
      if (state.work_item) setWorkItem(state.work_item);
      if (state.agent_name) setAgentName(state.agent_name);
      if (state.repository_name) setRepositoryName(state.repository_name);
      if (state.project_name) setProjectName(state.project_name);
      if (state.stats) setStats(state.stats);
      if (state.progress) setProgress(state.progress);
      if (state.model_leaderboard) setModelLeaderboard(state.model_leaderboard);
      if (state.agents) setAgents(state.agents);
      setStopAfterCurrent(!!state.stop_after_current);
      setCurrentSessionId(state.current_session_id ?? null);

      // Load initial logs with retry
      const allLogs = await retryWithBackoff(async () => {
        return await api.get_all_logs();
      });
      appendLogs(allLogs);
    }

    async function start() {
      const api = await waitForApi();
      if (stopped) return;

      // Initial load with retry logic
      try {
        await loadInitialState(api);
        setConnectionStatus("connected");
        consecutiveFailures = 0;
      } catch (error) {
        console.error("Failed to load initial state after retries:", error);
        setConnectionStatus("disconnected");
        // Don't return here - still start the polling timer for potential recovery
      }

      // Poll for incremental updates - now with resilience to transient failures
      timer = setInterval(async () => {
        if (stopped) return;
        try {
          // Get new logs (incremental — only entries since last poll)
          const newLogs = await api.get_new_logs();
          appendLogs(newLogs);

          // Get current state — use shallow-equal guards to avoid
          // unnecessary re-renders that clear native text selection.
          const state = await api.get_state();
          setIfChanged(setWorkItem)(state.work_item);
          setIfChanged(setAgentName)(state.agent_name);
          setIfChanged(setRepositoryName)(state.repository_name);
          if (state.project_name !== undefined) setIfChanged(setProjectName)(state.project_name);
          if (state.stats) setIfChanged(setStats)(state.stats);
          if (state.progress) setIfChanged(setProgress)(state.progress);
          if (state.model_leaderboard) setIfChanged(setModelLeaderboard)(state.model_leaderboard);
          if (state.agents) setIfChanged(setAgents)(state.agents);
          setStopAfterCurrent(!!state.stop_after_current);
          setCurrentSessionId(state.current_session_id ?? null);

          // Reset consecutive failures on success
          consecutiveFailures = 0;
          setConnectionStatus("connected");
        } catch {
          consecutiveFailures++;
          
          // Only set disconnected after multiple consecutive failures
          if (consecutiveFailures >= POLL_RESILIENCE_CONFIG.MAX_CONSECUTIVE_FAILURES) {
            setConnectionStatus("disconnected");
          }
          // If we haven't hit the threshold yet, maintain current connection status
          // This prevents flapping between connected/disconnected on transient issues
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
    repositoryName,
    projectName,
    stats,
    progress,
    modelLeaderboard,
    agents,
    stopAfterCurrent,
    currentSessionId,
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
    pauseAgent,
    resumeAgent,
    spawnAgent,
  };
}
