/**
 * Shared constants and utilities for Settings page.
 */

export const KNOWN_MODELS = [
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

export const isAbTestingEnabled = (models?: { ab_testing_enabled?: boolean; candidate_models?: string[] }): boolean => {
  if (!models) return false;
  if (typeof models.ab_testing_enabled === "boolean") {
    return models.ab_testing_enabled;
  }
  return (models.candidate_models?.length ?? 0) > 0;
};
