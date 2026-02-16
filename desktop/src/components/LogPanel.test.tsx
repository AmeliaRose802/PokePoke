/**
 * Tests for LogPanel tool-call collapsing.
 */

import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { LogPanel } from './LogPanel';
import type { LogEntry } from '../types';

function mk(ts: number, message: string): LogEntry {
  return { timestamp: ts, message, target: 'agent', style: null };
}

describe('LogPanel', () => {
  it('collapses copilot tool batch header + sequential tools into a batch accordion', () => {
    const logs: LogEntry[] = [
      mk(1, 'Now I need to search for a pattern.'),
      mk(2, '[Copilot] Calling 2 tool(s)...'),
      mk(3, "[Tool] grep({'pattern': 'foo'})"),
      mk(4, "[Result] found"),
      mk(5, "[Tool] grep({'pattern': 'bar'})"),
      mk(6, "[Result] found2"),
      mk(7, 'Done.'),
    ];

    render(
      <LogPanel
        title="Agent"
        icon="🤖"
        logs={logs}
        accentColor="#7dcfff"
      />
    );

    // Header should be collapsed away (not rendered as a raw log line)
    expect(screen.queryByText('[Copilot] Calling 2 tool(s)...')).not.toBeInTheDocument();

    // Narration gets collapsed when followed by tool calls
    expect(screen.getByText(/Narration \(1 lines\)/)).toBeInTheDocument();

    // Batch summary present with progress indicator
    expect(screen.getByText(/Tool batch \(2 calls\)/)).toBeInTheDocument();
    expect(screen.getByText('2/2')).toBeInTheDocument();

    // Grouped tool summary present
    expect(screen.getByText('🔧 grep ×2')).toBeInTheDocument();
  });

  it('renders a single tool call as a normal tool accordion', () => {
    const logs: LogEntry[] = [
      mk(1, "[Tool] view({'path': 'README.md'})"),
      mk(2, '[Result] ok'),
    ];

    render(
      <LogPanel
        title="Agent"
        icon="🤖"
        logs={logs}
        accentColor="#7dcfff"
      />
    );

    expect(screen.getByText('🔧 view')).toBeInTheDocument();
    expect(screen.queryByText(/Tool batch/)).not.toBeInTheDocument();
  });
});
