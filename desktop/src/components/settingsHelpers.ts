/**
 * Shared constants and utilities for Settings page.
 */

import type { MaintenanceAgent } from "../types";

/** Default configurations for all known maintenance agent types. */
export const KNOWN_MAINTENANCE_AGENTS: MaintenanceAgent[] = [
  {
    name: "Tech Debt",
    prompt_file: "tech-debt.md",
    frequency: 5,
    needs_worktree: false,
    enabled: true,
  },
  {
    name: "Janitor",
    prompt_file: "janitor.md",
    frequency: 2,
    needs_worktree: true,
    merge_changes: true,
    enabled: true,
  },
  {
    name: "Backlog Cleanup",
    prompt_file: "backlog-cleanup.md",
    frequency: 7,
    needs_worktree: true,
    merge_changes: false,
    enabled: true,
  },
  {
    name: "Beta Tester",
    prompt_file: "beta-tester.md",
    frequency: 7,
    needs_worktree: true,
    merge_changes: false,
    enabled: false,
  },
  {
    name: "Code Review",
    prompt_file: "code-reviewer.md",
    frequency: 5,
    needs_worktree: false,
    enabled: true,
  },
  {
    name: "Worktree Cleanup",
    prompt_file: "worktree-cleanup.md",
    frequency: 2,
    needs_worktree: false,
    enabled: true,
  },
  {
    name: "Model Sync",
    prompt_file: "",
    frequency: 1,
    needs_worktree: false,
    merge_changes: false,
    enabled: true,
  },
];

/** Hardcoded fallback used when the SDK model registry is unavailable. */
export const FALLBACK_KNOWN_MODELS = [
  "claude-opus-4.5",
  "claude-opus-4.6",
  "claude-sonnet-4",
  "claude-sonnet-4.5",
  "gemini-3-pro",
  "gpt-5",
  "gpt-5-codex",
  "gpt-5.1",
  "gpt-5.1-codex",
  "gpt-5.1-codex-max",
  "gpt-5.2",
  "gpt-5.2-codex",
];

/**
 * @deprecated Use `FALLBACK_KNOWN_MODELS` or dynamic models from the SDK registry.
 */
export const KNOWN_MODELS = FALLBACK_KNOWN_MODELS;

/**
 * Merge SDK-discovered models with the hardcoded fallback list.
 * SDK models take priority; fallback fills in when no SDK data is available.
 */
export function mergeModelLists(sdkModels: string[]): string[] {
  if (sdkModels.length === 0) return [...FALLBACK_KNOWN_MODELS];
  const merged = new Set(sdkModels);
  return [...merged].sort();
}

export const isAbTestingEnabled = (models?: { ab_testing_enabled?: boolean; candidate_models?: string[] }): boolean => {
  if (!models) return false;
  if (typeof models.ab_testing_enabled === "boolean") {
    return models.ab_testing_enabled;
  }
  return (models.candidate_models?.length ?? 0) > 0;
};
