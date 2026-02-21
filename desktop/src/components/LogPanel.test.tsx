/**
 * Tests for LogPanel tool-call collapsing.
 */

import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
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

  it('flattens single-tool batch to simple tool accordion (no extra nesting)', () => {
    const logs: LogEntry[] = [
      mk(1, '[Copilot] Calling 1 tool(s)...'),
      mk(2, "[Tool] report_intent({'intent': 'Testing'})"),
      mk(3, '✅ Result: Intent logged'),
    ];

    render(
      <LogPanel
        title="Agent"
        icon="🤖"
        logs={logs}
        accentColor="#7dcfff"
      />
    );

    // Should NOT show batch wrapper or group wrapper for single tool
    expect(screen.queryByText(/Tool batch/)).not.toBeInTheDocument();
    expect(screen.queryByText(/×1/)).not.toBeInTheDocument();

    // Should render as simple tool accordion
    expect(screen.getByText('🔧 report_intent')).toBeInTheDocument();
  });

  it('flattens single-item groups to direct tool accordions', () => {
    const logs: LogEntry[] = [
      mk(1, '[Copilot] Calling 2 tool(s)...'),
      mk(2, "[Tool] view({'path': 'a.txt'})"),
      mk(3, '✅ Result: ok'),
      mk(4, "[Tool] edit({'path': 'b.txt'})"),
      mk(5, '✅ Result: Replaced 1 occurrence'),
    ];

    render(
      <LogPanel
        title="Agent"
        icon="🤖"
        logs={logs}
        accentColor="#7dcfff"
      />
    );

    // Batch wrapper should exist for multiple tools
    expect(screen.getByText(/Tool batch \(2 calls\)/)).toBeInTheDocument();

    // But group wrappers (×1) should NOT exist for single-item groups
    expect(screen.queryByText(/view ×1/)).not.toBeInTheDocument();
    expect(screen.queryByText(/edit ×1/)).not.toBeInTheDocument();

    // Individual tools should be directly visible within the batch
    expect(screen.getByText('🔧 view')).toBeInTheDocument();
    expect(screen.getByText('🔧 edit')).toBeInTheDocument();
  });

  it('renders consecutive markdown lines as formatted HTML', () => {
    const logs: LogEntry[] = [
      mk(1, '## Summary'),
      mk(2, 'I made the following **changes**:'),
      mk(3, '- Updated `config.ts`'),
      mk(4, '- Fixed the bug'),
    ];

    render(
      <LogPanel
        title="Agent"
        icon="🤖"
        logs={logs}
        accentColor="#7dcfff"
      />
    );

    // Markdown should be rendered as HTML elements
    const container = document.querySelector('.log-markdown-content');
    expect(container).not.toBeNull();

    // Check for rendered heading
    const heading = container!.querySelector('h2');
    expect(heading).not.toBeNull();
    expect(heading!.textContent).toBe('Summary');

    // Check for rendered bold text
    const bold = container!.querySelector('strong');
    expect(bold).not.toBeNull();
    expect(bold!.textContent).toBe('changes');

    // Check for rendered list items
    const listItems = container!.querySelectorAll('li');
    expect(listItems.length).toBe(2);

    // Check for rendered inline code
    const code = container!.querySelector('code');
    expect(code).not.toBeNull();
    expect(code!.textContent).toBe('config.ts');
  });

  describe('click-to-focus vs text selection', () => {
    afterEach(() => {
      // Restore any getSelection mocks
      vi.restoreAllMocks();
    });

    it('calls onFocus when clicking with no text selected', () => {
      const onFocus = vi.fn();
      // Ensure getSelection returns empty string
      vi.spyOn(window, 'getSelection').mockReturnValue({
        toString: () => '',
      } as unknown as Selection);

      render(
        <LogPanel
          title="Agent"
          icon="🤖"
          logs={[]}
          accentColor="#7dcfff"
          onFocus={onFocus}
        />
      );

      fireEvent.click(screen.getByText(/Agent/));
      expect(onFocus).toHaveBeenCalledTimes(1);
    });

    it('does NOT call onFocus when text is selected (preserves copy)', () => {
      const onFocus = vi.fn();
      vi.spyOn(window, 'getSelection').mockReturnValue({
        toString: () => 'some selected text',
      } as unknown as Selection);

      render(
        <LogPanel
          title="Agent"
          icon="🤖"
          logs={[]}
          accentColor="#7dcfff"
          onFocus={onFocus}
        />
      );

      fireEvent.click(screen.getByText(/Agent/));
      expect(onFocus).not.toHaveBeenCalled();
    });
  });
});
