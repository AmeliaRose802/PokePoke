/**
 * Tests for snake icon utilities
 */

import { describe, expect, test } from 'vitest';
import { 
  getSnakeForWorkItem, 
  getWorkAgentIconPath, 
  getGateAgentIconPath,
  getAgentSnakeIcon,
  SNAKE_TYPES 
} from './snakeIcons';

describe('Snake Icon Utilities', () => {
  test('getSnakeForWorkItem returns consistent results', () => {
    const workItemId = 'TEST-123';
    const snake1 = getSnakeForWorkItem(workItemId);
    const snake2 = getSnakeForWorkItem(workItemId);
    
    expect(snake1).toBe(snake2);
    expect(SNAKE_TYPES).toContain(snake1);
  });

  test('different work items get different snakes (usually)', () => {
    const snakes = new Set();
    for (let i = 0; i < 20; i++) {
      snakes.add(getSnakeForWorkItem(`TEST-${i}`));
    }
    // With 5 snake types and 20 items, we should get good distribution
    expect(snakes.size).toBeGreaterThan(2);
  });

  test('getWorkAgentIconPath returns correct path', () => {
    const path = getWorkAgentIconPath('cobra');
    expect(path).toBe('/work_agent_icons/cobra/work_agent_icon.png');
  });

  test('getGateAgentIconPath returns correct path', () => {
    const path = getGateAgentIconPath('rattlesnake');
    expect(path).toBe('/work_agent_icons/rattlesnake/gate_agent_icon.png');
  });

  test('getAgentSnakeIcon returns correct paths for work and gate agents', () => {
    const workItemId = 'TEST-456';
    const snake = getSnakeForWorkItem(workItemId);
    
    const workPath = getAgentSnakeIcon(workItemId, false);
    const gatePath = getAgentSnakeIcon(workItemId, true);
    
    expect(workPath).toBe(`/work_agent_icons/${snake}/work_agent_icon.png`);
    expect(gatePath).toBe(`/work_agent_icons/${snake}/gate_agent_icon.png`);
  });
});