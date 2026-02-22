/**
 * Snake icon utilities for work and gate agent avatars.
 * 
 * Each work item gets a randomly assigned snake pair (work_agent_icon.png + gate_agent_icon.png)
 * The assignment is stable based on work_item_id hash to ensure consistency across renders.
 */

export const SNAKE_TYPES = [
  'cobra',
  'corn', 
  'rainbow_boa',
  'rattlesnake',
  'sea_snake'
] as const;

export type SnakeType = typeof SNAKE_TYPES[number];

/**
 * Hash a string to a stable number for deterministic selection
 */
function hashString(str: string): number {
  let hash = 0;
  for (let i = 0; i < str.length; i++) {
    hash = ((hash << 5) - hash + str.charCodeAt(i)) | 0;
  }
  return Math.abs(hash);
}

/**
 * Get a stable snake type assignment for a work item ID
 */
export function getSnakeForWorkItem(workItemId: string): SnakeType {
  const hash = hashString(workItemId);
  const index = hash % SNAKE_TYPES.length;
  return SNAKE_TYPES[index];
}

/**
 * Get the path to the work agent icon for a given snake type
 */
export function getWorkAgentIconPath(snakeType: SnakeType): string {
  return `/work_agent_icons/${snakeType}/work_agent_icon.png`;
}

/**
 * Get the path to the gate agent icon for a given snake type
 */
export function getGateAgentIconPath(snakeType: SnakeType): string {
  return `/work_agent_icons/${snakeType}/gate_agent_icon.png`;
}

/**
 * Get the appropriate snake icon path for an agent based on its type and work item
 */
export function getAgentSnakeIcon(workItemId: string, isGateAgent: boolean): string {
  const snakeType = getSnakeForWorkItem(workItemId);
  return isGateAgent 
    ? getGateAgentIconPath(snakeType)
    : getWorkAgentIconPath(snakeType);
}