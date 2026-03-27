/**
 * Agent management bridge hooks for the PokePoke desktop app.
 *
 * Extracted from useBridge.ts to keep file length under the limit.
 */

import { useCallback } from "react";

import { AgentInfoSchema, validatePayload } from "./schemas";
import type { AgentInfo } from "./types";

export interface AgentBridgeMethods {
  getAgentDetail: (agentId: string) => Promise<AgentInfo | null>;
  pauseAgent: (agentId: string) => Promise<boolean>;
  resumeAgent: (agentId: string) => Promise<boolean>;
  spawnAgent: () => Promise<{ success: boolean; at_limit: boolean; active: number; max: number } | null>;
}

export function useAgentBridge(): AgentBridgeMethods {
  const getAgentDetail = useCallback(async (agentId: string): Promise<AgentInfo | null> => {
    if (!window.pywebview?.api) return null;
    try {
      const raw = await window.pywebview.api.get_agent_detail(agentId);
      return raw === null ? null : validatePayload(AgentInfoSchema, raw, `getAgentDetail(${agentId})`);
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

  return { getAgentDetail, pauseAgent, resumeAgent, spawnAgent };
}
