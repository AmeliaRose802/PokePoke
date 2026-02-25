/**
 * Tests for AgentsPanel pause/resume buttons and session grouping.
 */

import { fireEvent,render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import type { AgentInfo } from '../types';
import { AgentsPanel } from './AgentsPanel';

function mkAgent(overrides: Partial<AgentInfo> = {}): AgentInfo {
  const iteration = overrides.iteration ?? 1;
  const agentId = overrides.agent_id ?? 'agent-1';
  return {
    agent_id: agentId,
    base_agent_id: overrides.base_agent_id ?? agentId,
    card_id: overrides.card_id ?? `${agentId}::v${iteration}`,
    parent_card_id: overrides.parent_card_id,
    name: 'Worker',
    iteration,
    status: 'running',
    recent_logs: [],
    paused: false,
    is_history_entry: overrides.is_history_entry ?? false,
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

  describe('retry attempt cards', () => {
    it('renders distinct cards for each attempt of the same agent', () => {
      const first = mkAgent({
        agent_id: 'agent-1',
        iteration: 1,
        card_id: 'agent-1::v1',
        is_history_entry: true,
        status: 'failed',
      });
      const second = mkAgent({
        agent_id: 'agent-1',
        iteration: 2,
        card_id: 'agent-1::v2',
      });
      const { container } = render(
        <AgentsPanel agents={[first, second]} onPauseAgent={vi.fn()} onResumeAgent={vi.fn()} />
      );
      const cards = container.querySelectorAll('.agent-card');
      expect(cards.length).toBe(2);
      expect(screen.getByText('v1')).toBeInTheDocument();
      expect(screen.getByText('v2')).toBeInTheDocument();
    });

    it('omits pause/resume controls for historical attempts', () => {
      const history = mkAgent({
        agent_id: 'agent-1',
        iteration: 1,
        card_id: 'agent-1::v1',
        is_history_entry: true,
        status: 'failed',
      });
      render(
        <AgentsPanel agents={[history]} onPauseAgent={vi.fn()} onResumeAgent={vi.fn()} />
      );
      expect(screen.queryByTitle('Pause agent')).not.toBeInTheDocument();
      expect(screen.queryByTitle('Resume agent')).not.toBeInTheDocument();
    });

    it('calls onSelectAgent with the card identifier', () => {
      const agent = mkAgent({
        agent_id: 'agent-1',
        card_id: 'agent-1::v5',
      });
      const onSelect = vi.fn();
      render(
        <AgentsPanel
          agents={[agent]}
          onSelectAgent={onSelect}
          onPauseAgent={vi.fn()}
          onResumeAgent={vi.fn()}
        />
      );
      screen.getByText('Worker').click();
      expect(onSelect).toHaveBeenCalledWith('agent-1::v5');
    });
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

  it('collapses active agents on click and expands again', () => {
    const running = mkAgent({ agent_id: 'running-1', name: 'RunningWorker' });

    render(
      <AgentsPanel agents={[running]} onPauseAgent={vi.fn()} onResumeAgent={vi.fn()} />
    );

    expect(screen.getByText('RunningWorker')).toBeInTheDocument();

    const activeHeader = screen.getByRole('button', { name: /active/i });
    fireEvent.click(activeHeader);
    expect(screen.queryByText('RunningWorker')).not.toBeInTheDocument();

    fireEvent.click(activeHeader);
    expect(screen.getByText('RunningWorker')).toBeInTheDocument();
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

    it('shows "Previous Session" instead of "Session __unknown__" for agents without session_id', () => {
      const oldAgent = mkAgent({ agent_id: 'old-1', name: 'OldWorker' }); // no session_id
      const newAgent = mkAgent({ agent_id: 'new-1', name: 'NewWorker', session_id: '2000.0' });
      render(
        <AgentsPanel
          agents={[oldAgent, newAgent]}
          currentSessionId="2000.0"
          onPauseAgent={vi.fn()}
          onResumeAgent={vi.fn()}
        />
      );
      expect(screen.getByText(/Previous Session/)).toBeInTheDocument();
      expect(screen.queryByText(/__unknown__/)).not.toBeInTheDocument();
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

  describe('spawn agent button', () => {
    it('shows spawn button when orchestratorRunning is true', () => {
      const agent = mkAgent();
      render(
        <AgentsPanel
          agents={[agent]}
          orchestratorRunning={true}
          onSpawnAgent={vi.fn()}
          onPauseAgent={vi.fn()}
          onResumeAgent={vi.fn()}
        />
      );
      expect(screen.getByTitle('Spawn additional agent')).toBeInTheDocument();
    });

    it('does not show spawn button when orchestratorRunning is false', () => {
      const agent = mkAgent();
      render(
        <AgentsPanel
          agents={[agent]}
          orchestratorRunning={false}
          onSpawnAgent={vi.fn()}
          onPauseAgent={vi.fn()}
          onResumeAgent={vi.fn()}
        />
      );
      expect(screen.queryByTitle('Spawn additional agent')).not.toBeInTheDocument();
    });

    it('calls onSpawnAgent when spawn button is clicked', () => {
      const onSpawn = vi.fn();
      const agent = mkAgent();
      render(
        <AgentsPanel
          agents={[agent]}
          orchestratorRunning={true}
          onSpawnAgent={onSpawn}
          onPauseAgent={vi.fn()}
          onResumeAgent={vi.fn()}
        />
      );
      fireEvent.click(screen.getByTitle('Spawn additional agent'));
      expect(onSpawn).toHaveBeenCalledTimes(1);
    });

    it('disables spawn button and shows limit title when spawnAtLimit is true', () => {
      const agent = mkAgent();
      render(
        <AgentsPanel
          agents={[agent]}
          orchestratorRunning={true}
          onSpawnAgent={vi.fn()}
          spawnAtLimit={true}
          onPauseAgent={vi.fn()}
          onResumeAgent={vi.fn()}
        />
      );
      const btn = screen.getByTitle(/At max agent limit/);
      expect(btn).toBeDisabled();
    });

    it('shows spawn button in empty state when orchestratorRunning', () => {
      render(
        <AgentsPanel
          agents={[]}
          orchestratorRunning={true}
          onSpawnAgent={vi.fn()}
          onPauseAgent={vi.fn()}
          onResumeAgent={vi.fn()}
        />
      );
      expect(screen.getByTitle('Spawn additional agent')).toBeInTheDocument();
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

  describe('gate agent verdict preview', () => {
    const successVerdictJson = JSON.stringify({
      status: 'success',
      reason: 'new_work_verified',
      message: 'All tests pass and implementation looks correct.',
      recommendation: 'Close the issue.',
    });

    const failureVerdictJson = JSON.stringify({
      status: 'failure',
      reason: 'tests_failing',
      details: 'Two unit tests are still failing in test_foo.py.',
    });

    function mkGateAgent(logs: string[]): AgentInfo {
      return mkAgent({
        agent_id: 'work-item-gate',
        name: 'Gate',
        status: 'success',
        recent_logs: logs,
      });
    }

    it('shows verdict status for gate agent with success JSON in logs', () => {
      const agent = mkGateAgent([`\`\`\`json\n${successVerdictJson}\n\`\`\``]);
      render(<AgentsPanel agents={[agent]} onPauseAgent={vi.fn()} onResumeAgent={vi.fn()} />);
      fireEvent.click(screen.getByRole('button', { name: /completed/i }));
      expect(screen.getByText('✓ Passed')).toBeInTheDocument();
    });

    it('shows verdict status for gate agent with failure JSON in logs', () => {
      const agent = mkGateAgent([`\`\`\`json\n${failureVerdictJson}\n\`\`\``]);
      render(<AgentsPanel agents={[agent]} onPauseAgent={vi.fn()} onResumeAgent={vi.fn()} />);
      fireEvent.click(screen.getByRole('button', { name: /completed/i }));
      expect(screen.getByText('✗ Failed')).toBeInTheDocument();
    });

    it('shows reason from success verdict', () => {
      const agent = mkGateAgent([`\`\`\`json\n${successVerdictJson}\n\`\`\``]);
      render(<AgentsPanel agents={[agent]} onPauseAgent={vi.fn()} onResumeAgent={vi.fn()} />);
      fireEvent.click(screen.getByRole('button', { name: /completed/i }));
      expect(screen.getByText('new_work_verified')).toBeInTheDocument();
    });

    it('shows message from success verdict', () => {
      const agent = mkGateAgent([`\`\`\`json\n${successVerdictJson}\n\`\`\``]);
      render(<AgentsPanel agents={[agent]} onPauseAgent={vi.fn()} onResumeAgent={vi.fn()} />);
      fireEvent.click(screen.getByRole('button', { name: /completed/i }));
      expect(screen.getByText('All tests pass and implementation looks correct.')).toBeInTheDocument();
    });

    it('shows details from failure verdict', () => {
      const agent = mkGateAgent([`\`\`\`json\n${failureVerdictJson}\n\`\`\``]);
      render(<AgentsPanel agents={[agent]} onPauseAgent={vi.fn()} onResumeAgent={vi.fn()} />);
      fireEvent.click(screen.getByRole('button', { name: /completed/i }));
      expect(screen.getByText('Two unit tests are still failing in test_foo.py.')).toBeInTheDocument();
    });

    it('shows recommendation when present in verdict', () => {
      const agent = mkGateAgent([`\`\`\`json\n${successVerdictJson}\n\`\`\``]);
      render(<AgentsPanel agents={[agent]} onPauseAgent={vi.fn()} onResumeAgent={vi.fn()} />);
      fireEvent.click(screen.getByRole('button', { name: /completed/i }));
      expect(screen.getByText('Close the issue.')).toBeInTheDocument();
    });

    it('shows raw logs for gate agent without verdict', () => {
      const agent = mkGateAgent(['Running tests...', 'Coverage: 85%']);
      render(<AgentsPanel agents={[agent]} onPauseAgent={vi.fn()} onResumeAgent={vi.fn()} />);
      fireEvent.click(screen.getByRole('button', { name: /completed/i }));
      expect(screen.getByText('Running tests...')).toBeInTheDocument();
      expect(screen.queryByText('✓ Passed')).not.toBeInTheDocument();
      expect(screen.queryByText('✗ Failed')).not.toBeInTheDocument();
    });

    it('shows running gate check message for gate agent with no logs', () => {
      const agent = mkAgent({ agent_id: 'work-item-gate', name: 'Gate', recent_logs: [] });
      render(<AgentsPanel agents={[agent]} onPauseAgent={vi.fn()} onResumeAgent={vi.fn()} />);
      expect(screen.getByText('Running gate check\u2026')).toBeInTheDocument();
    });

    it('does not render verdict card for non-gate agents', () => {
      const nonGateLog = `\`\`\`json\n${successVerdictJson}\n\`\`\``;
      const agent = mkAgent({ recent_logs: [nonGateLog] });
      render(<AgentsPanel agents={[agent]} onPauseAgent={vi.fn()} onResumeAgent={vi.fn()} />);
      expect(screen.queryByText('✓ Passed')).not.toBeInTheDocument();
    });
  });

  describe('maintenance sub-agent nesting', () => {
    it('renders maintenance sub-agent nested under parent agent', () => {
      const janitorAgent = mkAgent({
        agent_id: 'janitor-123',
        name: 'Janitor',
        agent_type: 'janitor',
      });
      const mergeConflictAgent = mkAgent({
        agent_id: 'merge-conflict-456',
        name: 'Merge Conflict Cleanup',
        agent_type: 'merge_conflict_cleanup',
        parent_agent_id: 'janitor-123',
      });
      const { container } = render(
        <AgentsPanel
          agents={[janitorAgent, mergeConflictAgent]}
          onPauseAgent={vi.fn()}
          onResumeAgent={vi.fn()}
        />
      );
      // Sub-agent should have child class (indented under parent)
      const childCard = container.querySelector('.agent-card-child');
      expect(childCard).not.toBeNull();
      // Parent should not have child class
      const allCards = container.querySelectorAll('.agent-card');
      expect(allCards).toHaveLength(2);
      // First card (parent) should not have child class
      expect(allCards[0].classList.contains('agent-card-child')).toBe(false);
      // Second card (child) should have child class
      expect(allCards[1].classList.contains('agent-card-child')).toBe(true);
    });

    it('renders multiple maintenance sub-agents under same parent', () => {
      const janitorAgent = mkAgent({
        agent_id: 'janitor-123',
        name: 'Janitor',
        agent_type: 'janitor',
      });
      const subAgent1 = mkAgent({
        agent_id: 'sub-1',
        name: 'Sub Agent 1',
        parent_agent_id: 'janitor-123',
      });
      const subAgent2 = mkAgent({
        agent_id: 'sub-2',
        name: 'Sub Agent 2',
        parent_agent_id: 'janitor-123',
      });
      const { container } = render(
        <AgentsPanel
          agents={[janitorAgent, subAgent1, subAgent2]}
          onPauseAgent={vi.fn()}
          onResumeAgent={vi.fn()}
        />
      );
      const childCards = container.querySelectorAll('.agent-card-child');
      expect(childCards).toHaveLength(2);
    });

    it('does not nest agent when parent is not in agent list', () => {
      // Sub-agent with parent_agent_id pointing to non-existent agent
      const orphanAgent = mkAgent({
        agent_id: 'orphan-123',
        name: 'Orphan Agent',
        parent_agent_id: 'missing-parent',
      });
      const { container } = render(
        <AgentsPanel
          agents={[orphanAgent]}
          onPauseAgent={vi.fn()}
          onResumeAgent={vi.fn()}
        />
      );
      // Should render as root (no child class) since parent doesn't exist
      const childCard = container.querySelector('.agent-card-child');
      expect(childCard).toBeNull();
    });
  });

  describe('cross-session gate isolation', () => {
    it('does not show gate chip from a different session with same card_id', () => {
      // Old session has a parent + gate child with same card_id as new session
      const oldParent = mkAgent({
        agent_id: 'worker-1',
        card_id: 'worker-1::v1',
        name: 'Worker',
        status: 'failed',
        session_id: '1000.0',
        is_history_entry: true,
      });
      const oldGate = mkAgent({
        agent_id: 'worker-1-gate',
        card_id: 'worker-1-gate::v1',
        name: 'Gate',
        status: 'failed',
        session_id: '1000.0',
        parent_card_id: 'worker-1::v1',
        is_history_entry: true,
      });
      // New session reuses the same card_id (card IDs collide across sessions)
      const newParent = mkAgent({
        agent_id: 'worker-1',
        card_id: 'worker-1::v1',
        name: 'Worker',
        status: 'running',
        session_id: '2000.0',
      });
      const { container } = render(
        <AgentsPanel
          agents={[oldParent, oldGate, newParent]}
          currentSessionId="2000.0"
          onPauseAgent={vi.fn()}
          onResumeAgent={vi.fn()}
        />
      );
      // Current session's parent card should NOT show "Gate failed" from old session
      const currentCards = container.querySelectorAll('.agent-card-running');
      const gateChips = Array.from(currentCards).flatMap((card) =>
        Array.from(card.querySelectorAll('.agent-gate-chip'))
      );
      expect(gateChips).toHaveLength(0);
    });
  });
});
