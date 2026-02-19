/**
 * Tests for AgentsPanel pause/resume buttons.
 */

import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { AgentsPanel } from './AgentsPanel';
import type { AgentInfo } from '../types';

function mkAgent(overrides: Partial<AgentInfo> = {}): AgentInfo {
  return {
    agent_id: 'agent-1',
    name: 'Worker',
    iteration: 1,
    status: 'running',
    recent_logs: [],
    paused: false,
    ...overrides,
  };
}

describe('AgentsPanel', () => {
  it('renders pause button for running agents', () => {
    const agent = mkAgent();
    render(
      <AgentsPanel agents={[agent]} onPauseAgent={vi.fn()} onResumeAgent={vi.fn()} />
    );
    const pauseBtn = screen.getByTitle('Pause agent');
    expect(pauseBtn).toBeInTheDocument();
    expect(pauseBtn.textContent).toBe('⏸');
  });

  it('renders resume button for paused agents', () => {
    const agent = mkAgent({ paused: true });
    render(
      <AgentsPanel agents={[agent]} onPauseAgent={vi.fn()} onResumeAgent={vi.fn()} />
    );
    const resumeBtn = screen.getByTitle('Resume agent');
    expect(resumeBtn).toBeInTheDocument();
    expect(resumeBtn.textContent).toBe('▶');
  });

  it('does not render pause button for completed agents', () => {
    const agent = mkAgent({ status: 'success' });
    render(
      <AgentsPanel agents={[agent]} onPauseAgent={vi.fn()} onResumeAgent={vi.fn()} />
    );
    expect(screen.queryByTitle('Pause agent')).not.toBeInTheDocument();
    expect(screen.queryByTitle('Resume agent')).not.toBeInTheDocument();
  });

  it('calls onPauseAgent when pause button is clicked', () => {
    const onPause = vi.fn();
    const agent = mkAgent();
    render(
      <AgentsPanel agents={[agent]} onPauseAgent={onPause} onResumeAgent={vi.fn()} />
    );
    fireEvent.click(screen.getByTitle('Pause agent'));
    expect(onPause).toHaveBeenCalledWith('agent-1');
  });

  it('calls onResumeAgent when resume button is clicked', () => {
    const onResume = vi.fn();
    const agent = mkAgent({ paused: true });
    render(
      <AgentsPanel agents={[agent]} onPauseAgent={vi.fn()} onResumeAgent={onResume} />
    );
    fireEvent.click(screen.getByTitle('Resume agent'));
    expect(onResume).toHaveBeenCalledWith('agent-1');
  });

  it('shows paused badge for paused agents', () => {
    const agent = mkAgent({ paused: true });
    render(
      <AgentsPanel agents={[agent]} onPauseAgent={vi.fn()} onResumeAgent={vi.fn()} />
    );
    expect(screen.getByTitle('Paused')).toBeInTheDocument();
  });

  it('applies paused CSS class to paused agent card', () => {
    const agent = mkAgent({ paused: true });
    const { container } = render(
      <AgentsPanel agents={[agent]} onPauseAgent={vi.fn()} onResumeAgent={vi.fn()} />
    );
    const card = container.querySelector('.agent-card-paused');
    expect(card).not.toBeNull();
  });

  it('shows "Paused" text when paused agent has no logs', () => {
    const agent = mkAgent({ paused: true, recent_logs: [] });
    render(
      <AgentsPanel agents={[agent]} onPauseAgent={vi.fn()} onResumeAgent={vi.fn()} />
    );
    expect(screen.getByText('Paused')).toBeInTheDocument();
  });

  it('pause click does not trigger card selection', () => {
    const onSelect = vi.fn();
    const onPause = vi.fn();
    const agent = mkAgent();
    render(
      <AgentsPanel
        agents={[agent]}
        onSelectAgent={onSelect}
        onPauseAgent={onPause}
        onResumeAgent={vi.fn()}
      />
    );
    fireEvent.click(screen.getByTitle('Pause agent'));
    expect(onPause).toHaveBeenCalled();
    expect(onSelect).not.toHaveBeenCalled();
  });
});
