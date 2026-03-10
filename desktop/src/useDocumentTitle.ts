/**
 * Custom hook to manage the browser tab/window title.
 *
 * Updates document.title based on the current agent and project context.
 * Format: "<AgentName> | <ProjectName> - PokePoke"
 * Fallback: "<ProjectName> - PokePoke" or just "PokePoke"
 */

import { useEffect } from "react";

const BASE_TITLE = "PokePoke";

/**
 * Build the document title based on current context.
 *
 * @param agentName - Currently active agent name (empty if no agent running)
 * @param projectName - Project/repo name from config (empty if not configured)
 * @returns Formatted title string
 */
export function buildTitle(agentName: string, projectName: string): string {
  const parts: string[] = [];

  if (agentName) {
    parts.push(agentName);
  }

  if (projectName) {
    parts.push(projectName);
  }

  if (parts.length === 0) {
    return BASE_TITLE;
  }

  return `${parts.join(" | ")} - ${BASE_TITLE}`;
}

/**
 * Hook that updates document.title when agent or project name changes.
 *
 * @param agentName - Currently active agent name
 * @param projectName - Project/repo name from config
 */
export function useDocumentTitle(agentName: string, projectName: string): void {
  useEffect(() => {
    document.title = buildTitle(agentName, projectName);
  }, [agentName, projectName]);
}
