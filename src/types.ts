/**
 * Types and interfaces for PokePoke orchestrator
 */

/**
 * Represents a beads work item from `bd ready --json`
 */
export interface BeadsWorkItem {
  id: string;
  title: string;
  description: string;
  status: string;
  priority: number;
  issue_type: string;
  owner?: string;
  created_at: string;
  created_by: string;
  updated_at: string;
  labels?: string[];
  dependency_count?: number;
  dependent_count?: number;
}

/**
 * Represents a dependency relationship
 */
export interface Dependency {
  id: string;
  title: string;
  description: string;
  status: string;
  priority: number;
  issue_type: string;
  owner?: string;
  created_at: string;
  created_by: string;
  updated_at: string;
  labels?: string[];
  dependency_type: 'parent' | 'blocks' | 'related' | 'discovered-from';
}

/**
 * Represents an issue with full dependency information from `bd show --json`
 */
export interface IssueWithDependencies extends BeadsWorkItem {
  dependencies?: Dependency[];
  dependents?: Dependency[];
}

/**
 * Result from invoking Copilot CLI
 */
export interface CopilotResult {
  workItemId: string;
  success: boolean;
  output?: string;
  error?: string;
}
