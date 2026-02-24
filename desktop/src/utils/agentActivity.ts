import type { SessionStats } from '../types';

export interface AgentSegment { 
  label: string; 
  value: number; 
  color: string; 
}

export interface AgentActivity { 
  total: number; 
  segments: AgentSegment[]; 
}

export interface NormalizedAgentSegment extends AgentSegment { 
  start: number; 
  width: number; 
}

export function buildAgentActivity(stats: SessionStats | null): AgentActivity {
  const elapsed = stats?.agent_type_elapsed_seconds ?? {};

  // Map from internal key → display label and color
  const definitions: { key: string; label: string; color: string }[] = [
    { key: "work",             label: "Work",      color: "#7aa2f7" },
    { key: "gate",             label: "Gate",      color: "#f7768e" },
    { key: "tech_debt",        label: "Tech Debt", color: "#e0af68" },
    { key: "janitor",          label: "Janitor",   color: "#9ece6a" },
    { key: "backlog_cleanup",  label: "Backlog",   color: "#ff9e64" },
    { key: "cleanup",          label: "Cleanup",   color: "#bb9af7" },
    { key: "beta_tester",      label: "Beta",      color: "#2ac3de" },
    { key: "code_review",      label: "Review",    color: "#c0caf5" },
  ];

  const segments: AgentSegment[] = definitions
    .map(({ key, label, color }) => ({ label, value: elapsed[key] ?? 0, color }))
    .filter((segment) => segment.value > 0);

  // Fall back to counts when no elapsed time is recorded (e.g. legacy data)
  if (segments.length === 0) {
    return buildAgentActivityFromCounts(stats);
  }

  const total = segments.reduce((sum, seg) => sum + seg.value, 0);
  return { total, segments };
}

function buildAgentActivityFromCounts(stats: SessionStats | null): AgentActivity {
  const segments: AgentSegment[] = [
    { label: "Work",      value: stats?.work_agent_runs ?? 0,           color: "#7aa2f7" },
    { label: "Gate",      value: stats?.gate_agent_runs ?? 0,           color: "#f7768e" },
    { label: "Tech Debt", value: stats?.tech_debt_agent_runs ?? 0,      color: "#e0af68" },
    { label: "Janitor",   value: stats?.janitor_agent_runs ?? 0,        color: "#9ece6a" },
    { label: "Backlog",   value: stats?.backlog_cleanup_agent_runs ?? 0, color: "#ff9e64" },
    { label: "Cleanup",   value: stats?.cleanup_agent_runs ?? 0,        color: "#bb9af7" },
    { label: "Beta",      value: stats?.beta_tester_agent_runs ?? 0,    color: "#2ac3de" },
    { label: "Review",    value: stats?.code_review_agent_runs ?? 0,    color: "#c0caf5" },
  ].filter((segment) => segment.value > 0);

  const total = segments.reduce((sum, seg) => sum + seg.value, 0);
  return { total, segments };
}

export function normalizeAgentSegments(agentActivity: AgentActivity): NormalizedAgentSegment[] {
  if (!agentActivity.total) return [];
  let cursor = 0;
  return agentActivity.segments.map((segment) => {
    const width = agentActivity.total ? (segment.value / agentActivity.total) * 100 : 0;
    const normalized = { ...segment, width, start: cursor };
    cursor += width;
    return normalized;
  });
}