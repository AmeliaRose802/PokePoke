/**
 * pywebview bridge hook — polls the Python orchestrator via direct
 * in-process calls through window.pywebview.api (no network).
 */

import { useCallback, useEffect, useState } from "react";

import {
  AppStateSchema,
  AvailableModelsResponseSchema,
  ConfigResponseSchema,
  LogEntrySchema,
  ModelHistoryEntrySchema,
  PromptDetailSchema,
  PromptInfoSchema,
  safeValidatePayload,
  validatePayload,
} from "./schemas";
import type {
  AgentInfo,
  AvailableModelsResponse,
  ConcurrencyTimeline,
  ConfigResponse,
  ConnectionStatus,
  GateRejectionStats,
  LogEntry,
  ModelHistoryEntry,
  ModelPerformanceSummary,
  ProgressState,
  ProjectConfig,
  PromptDetail,
  PromptInfo,
  SessionStats,
  SetupConfigPayload,
  SetupStatus,
  WorkItem,
} from "./types";
import { useAgentBridge } from "./useAgentBridge";
import type { SetupBridgeMethods } from "./useSetupBridge";
import { useSetupBridge } from "./useSetupBridge";

/** Poll interval in ms — 250ms balances responsiveness with low CPU overhead */
const POLL_INTERVAL_MS = 250;

/** Maximum log entries kept in React state — prevents DOM explosion over long runs */
const MAX_FRONTEND_LOG_ENTRIES = 2000;

/**
 * Shallow-compare two values to avoid unnecessary setState calls.
 * Prevents React re-renders that clear native text selection.
 */
export function shallowEqual(a: unknown, b: unknown): boolean {
  if (Object.is(a, b)) return true;
  if (typeof a !== "object" || typeof b !== "object" || a === null || b === null) return false;
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
    setter((prev) => (shallowEqual(prev, value) ? prev : value));
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
    logs_dir: string | null;
    new_logs: LogEntry[];
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
  add_work_item_label(item_id: string, label: string): Promise<{ item_id: string; label: string; labels: string[] }>;
  remove_work_item_label(item_id: string, label: string): Promise<{ item_id: string; label: string; labels: string[] }>;
  get_available_models(): Promise<AvailableModelsResponse>;
  get_concurrency_timeline(): Promise<ConcurrencyTimeline>;
  get_gate_rejection_stats(): Promise<GateRejectionStats>;

  // First-time setup wizard API
  check_setup_status(): Promise<SetupStatus>;
  git_init(
    default_branch?: string,
  ): Promise<{ success: boolean; error?: string; stdout?: string | null; stderr?: string | null }>;
  bd_init(): Promise<{ success: boolean }>;
  create_default_config(config: SetupConfigPayload): Promise<{ path: string; saved: boolean }>;
  scaffold_prompt_overrides(templates?: string[], force?: boolean): Promise<{ success: boolean; written: string[] }>;
  complete_setup(): Promise<{ success: boolean; error?: string }>;
}

declare global {
  interface Window {
    pywebview?: {
      api: PyWebViewAPI;
    };
  }
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/** Retries an async function with exponential backoff */
async function retryWithBackoff<T>(fn: () => Promise<T>, config = INITIAL_RETRY_CONFIG): Promise<T> {
  let lastError: Error | null = null;
  let delay = config.BASE_DELAY_MS;
  for (let attempt = 0; attempt <= config.MAX_RETRIES; attempt++) {
    try {
      return await fn();
    } catch (error) {
      lastError = error instanceof Error ? error : new Error(String(error));
      if (attempt === config.MAX_RETRIES) throw lastError;
      await sleep(Math.min(delay, config.MAX_DELAY_MS));
      delay = Math.floor(delay * config.BACKOFF_MULTIPLIER);
    }
  }
  throw lastError || new Error("Retry failed");
}

export interface BridgeStateBase {
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
  logsDir: string | null;
  clearLogs: (target: "orchestrator" | "agent" | "all") => void;
  listPrompts: () => Promise<PromptInfo[]>;
  getPrompt: (name: string) => Promise<PromptDetail | null>;
  savePrompt: (name: string, content: string) => Promise<boolean>;
  resetPrompt: (name: string) => Promise<boolean>;
  getConfig: () => Promise<ConfigResponse | null>;
  saveConfig: (config: ProjectConfig) => Promise<boolean>;
  getAvailableModels: () => Promise<AvailableModelsResponse | null>;
  getModelHistory: (limit?: number) => Promise<ModelHistoryEntry[]>;
  getConcurrencyTimeline: () => Promise<ConcurrencyTimeline | null>;
  getGateRejectionStats: () => Promise<GateRejectionStats | null>;
  requestStopAfterCurrent: () => Promise<void>;
  cancelStopAfterCurrent: () => Promise<void>;
  addWorkItemLabel: (label: string) => Promise<void>;
  removeWorkItemLabel: (label: string) => Promise<void>;
  getAgentDetail: (agentId: string) => Promise<AgentInfo | null>;
  pauseAgent: (agentId: string) => Promise<boolean>;
  resumeAgent: (agentId: string) => Promise<boolean>;
  spawnAgent: () => Promise<{ success: boolean; at_limit: boolean; active: number; max: number } | null>;
}

export type BridgeState = BridgeStateBase & SetupBridgeMethods;

/**
 * React hook that polls the Python DesktopAPI for orchestrator state.
 * Direct in-process calls via pywebview — no network, no server.
 */
export function useBridge(): BridgeState {
  const [connectionStatus, setConnectionStatus] = useState<ConnectionStatus>("connecting");
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
  const [logsDir, setLogsDir] = useState<string | null>(null);

  const clearLogs = useCallback((target: "orchestrator" | "agent" | "all") => {
    if (target === "orchestrator" || target === "all") setOrchestratorLogs([]);
    if (target === "agent" || target === "all") setAgentLogs([]);
  }, []);

  const listPrompts = useCallback(async (): Promise<PromptInfo[]> => {
    if (!window.pywebview?.api) return [];
    const raw = await window.pywebview.api.list_prompts();
    return raw.map((p, idx) => validatePayload(PromptInfoSchema, p, `listPrompts[${idx}]`));
  }, []);

  const getPrompt = useCallback(async (name: string): Promise<PromptDetail | null> => {
    if (!window.pywebview?.api) return null;
    return validatePayload(PromptDetailSchema, await window.pywebview.api.get_prompt(name), `getPrompt(${name})`);
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
    return validatePayload(ConfigResponseSchema, await window.pywebview.api.get_config(), "getConfig");
  }, []);

  const saveConfig = useCallback(async (config: ProjectConfig): Promise<boolean> => {
    if (!window.pywebview?.api) return false;
    const result = await window.pywebview.api.save_config(config);
    return result.saved;
  }, []);

  const getAvailableModels = useCallback(async (): Promise<AvailableModelsResponse | null> => {
    if (!window.pywebview?.api) return null;
    try {
      return validatePayload(
        AvailableModelsResponseSchema,
        await window.pywebview.api.get_available_models(),
        "getAvailableModels",
      );
    } catch {
      return null;
    }
  }, []);

  const getModelHistory = useCallback(async (limit = 200): Promise<ModelHistoryEntry[]> => {
    if (!window.pywebview?.api) return [];
    try {
      const raw = await window.pywebview.api.get_model_history(limit);
      return raw.map((e, i) => validatePayload(ModelHistoryEntrySchema, e, `getModelHistory[${i}]`));
    } catch {
      return [];
    }
  }, []);

  const getConcurrencyTimeline = useCallback(async (): Promise<ConcurrencyTimeline | null> => {
    if (!window.pywebview?.api) return null;
    try {
      return await window.pywebview.api.get_concurrency_timeline();
    } catch {
      return null;
    }
  }, []);

  const getGateRejectionStats = useCallback(async (): Promise<GateRejectionStats | null> => {
    if (!window.pywebview?.api) return null;
    try {
      return await window.pywebview.api.get_gate_rejection_stats();
    } catch {
      return null;
    }
  }, []);

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

  const addWorkItemLabel = useCallback(
    async (label: string): Promise<void> => {
      if (!window.pywebview?.api || !workItem) return;
      try {
        const result = await window.pywebview.api.add_work_item_label(workItem.item_id, label);
        if (result?.labels) {
          setWorkItem((prev) => (prev ? { ...prev, labels: result.labels } : prev));
        }
      } catch (error) {
        console.error("Failed to add work item label:", error);
      }
    },
    [workItem],
  );

  const removeWorkItemLabel = useCallback(
    async (label: string): Promise<void> => {
      if (!window.pywebview?.api || !workItem) return;
      try {
        const result = await window.pywebview.api.remove_work_item_label(workItem.item_id, label);
        if (result?.labels) {
          setWorkItem((prev) => (prev ? { ...prev, labels: result.labels } : prev));
        }
      } catch (error) {
        console.error("Failed to remove work item label:", error);
      }
    },
    [workItem],
  );

  // Agent management bridge (extracted to useAgentBridge.ts)
  const agentBridge = useAgentBridge();

  // Setup wizard bridge (extracted to useSetupBridge.ts)
  const setupBridge = useSetupBridge();

  const appendLogs = useCallback((entries: LogEntry[]) => {
    if (entries.length === 0) return;
    const orchLogs: LogEntry[] = [];
    const agLogs: LogEntry[] = [];
    for (const e of entries) {
      if (e.target === "agent") agLogs.push(e);
      else orchLogs.push(e);
    }
    const cap = (prev: LogEntry[], added: LogEntry[]): LogEntry[] => {
      const next = [...prev, ...added];
      return next.length > MAX_FRONTEND_LOG_ENTRIES ? next.slice(-MAX_FRONTEND_LOG_ENTRIES) : next;
    };
    if (orchLogs.length > 0) setOrchestratorLogs((p) => cap(p, orchLogs));
    if (agLogs.length > 0) setAgentLogs((p) => cap(p, agLogs));
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
      const rawState = await retryWithBackoff(async () => await api.get_state());
      const state = validatePayload(AppStateSchema, rawState, "loadInitialState");

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
      setLogsDir(state.logs_dir ?? null);

      const rawLogs = await retryWithBackoff(async () => await api.get_all_logs());
      appendLogs(rawLogs.map((log, i) => validatePayload(LogEntrySchema, log, `initialLogs[${i}]`)));
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

      // Poll for incremental updates with resilience to transient failures
      timer = setInterval(async () => {
        if (stopped) return;
        try {
          const rawState = await api.get_state();
          const state = safeValidatePayload(AppStateSchema, rawState, "pollState");
          
          if (!state) {
            consecutiveFailures++;
            if (consecutiveFailures >= POLL_RESILIENCE_CONFIG.MAX_CONSECUTIVE_FAILURES) {
              setConnectionStatus("disconnected");
            }
            return;
          }

          // Validate new logs, fallback to raw if validation fails (better than losing logs)
          const validatedLogs = (state.new_logs ?? []).map((log, i) => 
            safeValidatePayload(LogEntrySchema, log, `newLogs[${i}]`) ?? log
          );
          appendLogs(validatedLogs);
          
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
          setIfChanged(setLogsDir)(state.logs_dir ?? null);

          consecutiveFailures = 0;
          setConnectionStatus("connected");
        } catch {
          consecutiveFailures++;
          if (consecutiveFailures >= POLL_RESILIENCE_CONFIG.MAX_CONSECUTIVE_FAILURES) {
            setConnectionStatus("disconnected");
          }
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
    logsDir,
    clearLogs,
    listPrompts,
    getPrompt,
    savePrompt,
    resetPrompt,
    getConfig,
    saveConfig,
    getAvailableModels,
    getModelHistory,
    getConcurrencyTimeline,
    getGateRejectionStats,
    requestStopAfterCurrent,
    cancelStopAfterCurrent,
    addWorkItemLabel,
    removeWorkItemLabel,
    ...agentBridge,
    ...setupBridge,
  };
}
