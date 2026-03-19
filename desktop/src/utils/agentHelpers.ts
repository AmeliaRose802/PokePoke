import type { AgentInfo } from "../types";
import { getAgentSnakeIcon } from "./snakeIcons";

/** Structured JSON verdict produced by a gate agent */
export interface GateVerdict {
  status: "success" | "failure";
  reason?: string;
  message?: string;
  details?: string;
  recommendation?: string;
}

/**
 * Parse a gate agent JSON verdict from log lines.
 * Looks for a JSON block in the format: ```json { ... } ```
 * Falls back to searching for a bare JSON object with a status field.
 * Returns null if no valid verdict is found.
 */
export function parseGateVerdict(logLines: string[]): GateVerdict | null {
  const combinedText = logLines.join("\n");

  // Primary: find ```json ... ``` block
  const jsonBlockMatch = combinedText.match(/```json\s*([\s\S]*?)\s*```/);
  if (jsonBlockMatch) {
    try {
      const parsed = JSON.parse(jsonBlockMatch[1].trim()) as unknown;
      if (
        parsed !== null &&
        typeof parsed === "object" &&
        "status" in parsed &&
        ((parsed as Record<string, unknown>).status === "success" ||
          (parsed as Record<string, unknown>).status === "failure")
      ) {
        return parsed as GateVerdict;
      }
    } catch {
      // Ignore parse errors and fall through
    }
  }

  // Fallback: search for a JSON object containing a status field
  const rawJsonMatch = combinedText.match(/\{\s*"status"\s*:\s*"(?:success|failure)"[\s\S]*?\}/);
  if (rawJsonMatch) {
    try {
      const parsed = JSON.parse(rawJsonMatch[0]) as unknown;
      if (
        parsed !== null &&
        typeof parsed === "object" &&
        "status" in parsed &&
        ((parsed as Record<string, unknown>).status === "success" ||
          (parsed as Record<string, unknown>).status === "failure")
      ) {
        return parsed as GateVerdict;
      }
    } catch {
      // Ignore parse errors
    }
  }

  return null;
}

const GATE_SUFFIX = "-gate";

const AGENT_ICON_MAP: Record<string, string> = {
  beta_test: "/agent_icons/beta_test_agent_icon.png",
  cleanup: "/agent_icons/cleanup_agent_icon.png",
  code_conflict: "/agent_icons/code_conflict_agent_icon.png",
  gate: "/agent_icons/gate_agent_icon.png",
  janitor: "/agent_icons/janitor_agent_icon.png",
  tech_debt: "/agent_icons/tech_debt_agent_icon.png",
  worktree_cleanup: "/agent_icons/worktree_cleanup_agent_icon.png",
};

const AGENT_TYPE_ALIASES: Record<string, string> = {
  beta_tester: "beta_test",
  beta_tester_agent: "beta_test",
  beta_test_agent: "beta_test",
  cleanup_agent: "cleanup",
  merge_conflict_cleanup: "code_conflict",
  merge_conflict: "code_conflict",
  code_conflict_agent: "code_conflict",
  janitor_agent: "janitor",
  maintenance_janitor: "janitor",
  tech_debt_agent: "tech_debt",
  techdebt: "tech_debt",
  maintenance_tech_debt: "tech_debt",
  worktree_cleanup_agent: "worktree_cleanup",
  worktreecleanup: "worktree_cleanup",
};

function normalize(value: string | undefined | null): string {
  return value?.toLowerCase() ?? "";
}

function normalizeAgentTypeCandidate(value: string | null | undefined): string | null {
  if (!value) return null;
  const normalized = value
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "");
  if (!normalized) return null;
  const withoutMaintenancePrefix = normalized.startsWith("maintenance_")
    ? normalized.replace(/^maintenance_/, "")
    : normalized;
  return AGENT_TYPE_ALIASES[withoutMaintenancePrefix] ?? withoutMaintenancePrefix;
}

export function isGateAgent(agent: AgentInfo): boolean {
  const normalizedId = normalize(agent.agent_id);
  const normalizedName = normalize(agent.name);
  return normalizedId.endsWith(GATE_SUFFIX) || normalizedName.includes("gate");
}

/**
 * Returns true when an agent represents a cleanup or maintenance phase
 * (not a work-agent retry and not a gate agent).
 */
export function isCleanupAgent(agent: AgentInfo): boolean {
  if (isGateAgent(agent)) return false;
  const agentType = getAgentType(agent);
  return agentType !== null && agentType !== "gate";
}

const CLEANUP_DISPLAY_LABELS: Record<string, string> = {
  code_conflict: "Merge Conflict Cleanup",
  cleanup: "Cleanup",
  worktree_cleanup: "Worktree Cleanup",
  janitor: "Janitor",
  tech_debt: "Tech Debt",
  beta_test: "Beta Test",
  code_review: "Code Review",
};

/** Human-readable label for a cleanup agent's separator. */
export function getCleanupDisplayLabel(agent: AgentInfo): string {
  const agentType = getAgentType(agent);
  if (agentType && CLEANUP_DISPLAY_LABELS[agentType]) {
    return CLEANUP_DISPLAY_LABELS[agentType];
  }
  return agent.name || "Cleanup";
}

export function getAgentPrimaryLabel(agent: AgentInfo): string {
  if (agent.work_item_id) {
    return agent.work_item_title ? `${agent.work_item_id}: ${agent.work_item_title}` : agent.work_item_id;
  }
  return agent.name;
}

export function getAgentType(agent: AgentInfo): string | null {
  if (isGateAgent(agent)) {
    return "gate";
  }

  const candidates = [agent.agent_type, agent.agent_id, agent.name];
  for (const candidate of candidates) {
    const normalized = normalizeAgentTypeCandidate(candidate);
    if (normalized && AGENT_ICON_MAP[normalized]) {
      return normalized;
    }
  }
  return null;
}

/**
 * Get the snake icon path for an agent, or null if the agent doesn't have a work item ID
 */
export function getAgentAvatar(agent: AgentInfo): string | null {
  // Prioritize snake icons for work agents
  if (agent.work_item_id) {
    return getAgentSnakeIcon(agent.work_item_id, isGateAgent(agent));
  }

  // Fall back to agent-type icons for system agents
  const agentType = getAgentType(agent);
  if (agentType) {
    return AGENT_ICON_MAP[agentType];
  }

  return null;
}

/**
 * Format a model name into a user-friendly display name.
 * Converts technical model names into readable labels while preserving version information.
 */
export function formatModelName(model: string | null | undefined): string {
  if (!model) {
    return "Unknown Model";
  }

  const modelStr = model.toLowerCase();

  // Claude models - preserve version numbers
  if (modelStr.includes("claude")) {
    let result = "Claude";

    // Extract variant (Sonnet, Opus, Haiku)
    if (modelStr.includes("sonnet")) {
      result += " Sonnet";
    } else if (modelStr.includes("opus")) {
      result += " Opus";
    } else if (modelStr.includes("haiku")) {
      result += " Haiku";
    }

    // Extract version number - handle multiple patterns:
    // - "claude-3-5-sonnet" -> "3.5"
    // - "claude-3-haiku" -> "3"
    // - "claude-opus-4.6" -> "4.6"
    // - "claude-4-5" -> "4.5"
    const versionMatch = modelStr.match(/(\d+)[-.](\d+)(?:[-.](\d+))?/);
    if (versionMatch) {
      // Build version from captured groups
      const major = versionMatch[1];
      const minor = versionMatch[2];
      const patch = versionMatch[3];

      // For patterns like "3-5-sonnet" or "3-haiku", use major.minor format
      let version = `${major}.${minor}`;

      // If the second number looks like a date (e.g., "20241022"), just use major
      if (parseInt(minor) > 100) {
        version = major;
      } else if (patch && parseInt(patch) <= 100) {
        // If there's a third number that's not a date, include it
        version += `.${patch}`;
      }

      result += ` ${version}`;
    } else {
      // Fallback: try to match single digit version (e.g., "claude-3")
      const singleVersionMatch = modelStr.match(/claude-(\d+)(?:[^\d]|$)/);
      if (singleVersionMatch) {
        result += ` ${singleVersionMatch[1]}`;
      }
    }

    return result;
  }

  // GPT models - preserve version numbers
  if (modelStr.includes("gpt")) {
    let result = "GPT";

    // Extract base version (e.g., "4", "5.3", "3.5")
    const versionMatch = modelStr.match(/gpt-?(\d+(?:\.\d+)?(?:\.\d+)?)/);
    if (versionMatch) {
      result += `-${versionMatch[1]}`;
    }

    // Add variant suffix (Turbo, Codex, etc.)
    if (modelStr.includes("turbo")) {
      result += " Turbo";
    } else if (modelStr.includes("codex")) {
      result += " Codex";
    } else if (modelStr.includes("4o")) {
      result = "GPT-4o";
    }

    return result;
  }

  // Gemini models - preserve version numbers
  if (modelStr.includes("gemini")) {
    let result = "Gemini";

    // Extract version (e.g., "1.5", "2.0")
    const versionMatch = modelStr.match(/(\d+\.\d+)/);
    if (versionMatch) {
      result += ` ${versionMatch[1]}`;
    }

    // Add variant (Pro, Flash, etc.)
    if (modelStr.includes("pro")) {
      result += " Pro";
    } else if (modelStr.includes("flash")) {
      result += " Flash";
    }

    return result;
  }

  // For any other model, capitalize the first letter and return as-is
  return model.charAt(0).toUpperCase() + model.slice(1);
}
