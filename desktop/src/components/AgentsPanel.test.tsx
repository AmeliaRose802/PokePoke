/**
 * Tests for AgentsPanel pause/resume buttons and session grouping.
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

  it('renders agent type icon when provided', () => {
    const agent = mkAgent({ agent_type: 'janitor' });
    render(
      <AgentsPanel agents={[agent]} onPauseAgent={vi.fn()} onResumeAgent={vi.fn()} />
    );
    const icon = screen.getByAltText('janitor icon') as HTMLImageElement;
    expect(icon).toBeInTheDocument();
    expect(icon.getAttribute('src')).toBe('/agent_icons/janitor_agent_icon.png');
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

    // Completed section is collapsed by default; expand to ensure card renders
    fireEvent.click(screen.getByRole('button', { name: /completed/i }));

    expect(screen.queryByTitle('Pause agent')).not.toBeInTheDocument();
    expect(screen.queryByTitle('Resume agent')).not.toBeInTheDocument();
  });

  it('collapses completed agents by default and expands on click', () => {
    const running = mkAgent({ agent_id: 'running-1', name: 'RunningWorker' });
    const done = mkAgent({ agent_id: 'done-1', name: 'DoneWorker', status: 'success' });

    render(
      <AgentsPanel agents={[running, done]} onPauseAgent={vi.fn()} onResumeAgent={vi.fn()} />
    );

    expect(screen.getByText('RunningWorker')).toBeInTheDocument();
    expect(screen.queryByText('DoneWorker')).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: /completed/i }));
    expect(screen.getByText('DoneWorker')).toBeInTheDocument();
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

  it('allows collapsing and expanding the run log snippet per agent card', () => {
    const agent = mkAgent({ recent_logs: ['line 1', 'line 2'] });
    render(
      <AgentsPanel agents={[agent]} onPauseAgent={vi.fn()} onResumeAgent={vi.fn()} />
    );

    expect(screen.getByText('line 1')).toBeInTheDocument();

    const hideBtn = screen.getByRole('button', { name: /hide log/i });
    fireEvent.click(hideBtn);
    expect(screen.queryByText('line 1')).not.toBeInTheDocument();

    const showBtn = screen.getByRole('button', { name: /show log/i });
    fireEvent.click(showBtn);
    expect(screen.getByText('line 1')).toBeInTheDocument();
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

  describe('session grouping', () => {
    it('collapses previous session agents by default', () => {
      const oldAgent = mkAgent({ agent_id: 'old-1', name: 'OldWorker', session_id: '1000.0' });
      const newAgent = mkAgent({ agent_id: 'new-1', name: 'NewWorker', session_id: '2000.0' });
      render(
        <AgentsPanel
          agents={[oldAgent, newAgent]}
          currentSessionId="2000.0"
          onPauseAgent={vi.fn()}
          onResumeAgent={vi.fn()}
        />
      );
      // Current session agent should be visible
      expect(screen.getByText('NewWorker')).toBeInTheDocument();
      // Previous session agent should be collapsed (not visible)
      expect(screen.queryByText('OldWorker')).not.toBeInTheDocument();
    });

    it('expands previous session when header is clicked', () => {
      const oldAgent = mkAgent({ agent_id: 'old-1', name: 'OldWorker', session_id: '1000.0' });
      const newAgent = mkAgent({ agent_id: 'new-1', name: 'NewWorker', session_id: '2000.0' });
      render(
        <AgentsPanel
          agents={[oldAgent, newAgent]}
          currentSessionId="2000.0"
          onPauseAgent={vi.fn()}
          onResumeAgent={vi.fn()}
        />
      );
      // Click the collapsed (non-current) session header
      const headers = screen.getAllByRole('button', { name: /session/i });
      const collapsedHeader = headers.find(h => h.getAttribute('aria-expanded') === 'false')!;
      fireEvent.click(collapsedHeader);
      // Now old agent should be visible
      expect(screen.getByText('OldWorker')).toBeInTheDocument();
    });

    it('does not show session headers for single session', () => {
      const agent = mkAgent({ session_id: '1000.0' });
      const { container } = render(
        <AgentsPanel
          agents={[agent]}
          currentSessionId="1000.0"
          onPauseAgent={vi.fn()}
          onResumeAgent={vi.fn()}
        />
      );
      expect(container.querySelector('.session-group-header')).toBeNull();
    });

    it('shows agent count in collapsed session header', () => {
      const agents = [
        mkAgent({ agent_id: 'old-1', name: 'W1', session_id: '1000.0', status: 'success' }),
        mkAgent({ agent_id: 'old-2', name: 'W2', session_id: '1000.0', status: 'success' }),
        mkAgent({ agent_id: 'new-1', name: 'W3', session_id: '2000.0' }),
      ];
      const { container } = render(
        <AgentsPanel
          agents={agents}
          currentSessionId="2000.0"
          onPauseAgent={vi.fn()}
          onResumeAgent={vi.fn()}
        />
      );

      const collapsedHeader = container.querySelector(
        '.session-group-header[aria-expanded="false"]'
      );
      const count = collapsedHeader?.querySelector('.session-group-count');
      expect(count?.textContent).toBe('2');
    });

    it('re-collapses session when header is clicked twice', () => {
      const oldAgent = mkAgent({ agent_id: 'old-1', name: 'OldWorker', session_id: '1000.0' });
      const newAgent = mkAgent({ agent_id: 'new-1', name: 'NewWorker', session_id: '2000.0' });
      render(
        <AgentsPanel
          agents={[oldAgent, newAgent]}
          currentSessionId="2000.0"
          onPauseAgent={vi.fn()}
          onResumeAgent={vi.fn()}
        />
      );
      const headers = screen.getAllByRole('button', { name: /session/i });
      const collapsedHeader = headers.find(h => h.getAttribute('aria-expanded') === 'false')!;
      // Expand
      fireEvent.click(collapsedHeader);
      expect(screen.getByText('OldWorker')).toBeInTheDocument();
      // Collapse again
      fireEvent.click(collapsedHeader);
      expect(screen.queryByText('OldWorker')).not.toBeInTheDocument();
    });
  });

  describe('modified files display', () => {
    it('shows file count and list for agents with modified_files', () => {
      const agent = mkAgent({
        modified_files: ['src/main.py', 'tests/test_main.py'],
      });
      render(
        <AgentsPanel agents={[agent]} onPauseAgent={vi.fn()} onResumeAgent={vi.fn()} />
      );
      expect(screen.getByText('📁 2 files')).toBeInTheDocument();
      expect(screen.getByText('src/main.py, tests/test_main.py')).toBeInTheDocument();
    });

    it('does not show files section when no modified_files', () => {
      const agent = mkAgent();
      const { container } = render(
        <AgentsPanel agents={[agent]} onPauseAgent={vi.fn()} onResumeAgent={vi.fn()} />
      );
      expect(container.querySelector('.agent-card-files')).toBeNull();
    });

    it('truncates file list beyond 3 files', () => {
      const agent = mkAgent({
        modified_files: ['a.py', 'b.py', 'c.py', 'd.py', 'e.py'],
      });
      render(
        <AgentsPanel agents={[agent]} onPauseAgent={vi.fn()} onResumeAgent={vi.fn()} />
      );
      expect(screen.getByText('📁 5 files')).toBeInTheDocument();
      expect(screen.getByText('a.py, b.py, c.py +2 more')).toBeInTheDocument();
    });

    it('shows singular "file" for single file', () => {
      const agent = mkAgent({ modified_files: ['only.py'] });
      render(
        <AgentsPanel agents={[agent]} onPauseAgent={vi.fn()} onResumeAgent={vi.fn()} />
      );
      expect(screen.getByText('📁 1 file')).toBeInTheDocument();
    });
  });
});
