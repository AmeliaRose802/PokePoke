/**
 * Tests for logProcessor utility functions.
 */

import { describe, expect, it } from 'vitest';

import type { LogEntry } from '../types';
import { buildToolSummary, isToolCallMessage, parseToolLabel, processLogsToRenderItems } from './logProcessor';

function makeEntry(message: string, timestamp = 1000): LogEntry {
  return { message, target: 'agent', style: null, timestamp };
}

describe('parseToolLabel', () => {
  it('extracts tool name and path for view tool', () => {
    const message = "[Tool] view({'path': 'README.md'})";
    const label = parseToolLabel(message);
    expect(label).toBe('🌿 view - README.md');
  });

  it('extracts tool name and command for powershell tool', () => {
    const message = "[Tool] powershell({'command': 'npm run build', 'shellId': 'shell-1'})";
    const label = parseToolLabel(message);
    expect(label).toContain('🌿 powershell - npm run build');
  });

  it('extracts tool name and pattern for grep tool', () => {
    const message = "[Tool] grep({'pattern': 'TODO', 'path': 'src/'})";
    const label = parseToolLabel(message);
    expect(label).toBe('🌿 grep - TODO');
  });

  it('extracts tool name and path for edit tool', () => {
    const message = "[Tool] edit({'path': 'src/app.ts'})";
    const label = parseToolLabel(message);
    expect(label).toBe('🌿 edit - src/app.ts');
  });

  it('extracts tool name and path for create tool', () => {
    const message = "[Tool] create({'path': 'src/components/NewComponent.tsx'})";
    const label = parseToolLabel(message);
    expect(label).toBe('🌿 create - src/components/NewComponent.tsx');
  });

  it('extracts tool name and pattern for glob tool', () => {
    const message = "[Tool] glob({'pattern': '**/*.ts'})";
    const label = parseToolLabel(message);
    expect(label).toBe('🌿 glob - **/*.ts');
  });

  it('returns just tool name if no description available', () => {
    const message = "[Tool] report_intent({'intent': 'Testing'})";
    const label = parseToolLabel(message);
    expect(label).toBe('🌿 report_intent');
  });

  it('truncates long descriptions', () => {
    const longPath = 'a'.repeat(100);
    const message = `[Tool] view({'path': '${longPath}'})`;
    const label = parseToolLabel(message);
    expect(label.length).toBeLessThan(message.length);
    expect(label).toContain('…');
  });

  it('handles messages without Tool prefix', () => {
    const message = "Some other message";
    const label = parseToolLabel(message);
    expect(label).toBe('Some other message');
  });

  it('parses 🔧 prefixed tool calls', () => {
    const message = "🔧 grep({'pattern': 'TODO', 'path': 'src/'})";
    const label = parseToolLabel(message);
    expect(label).toBe('🌿 grep - TODO');
  });

  it('parses 🔧 prefixed powershell with leading spaces', () => {
    const message = "  🔧 powershell({'command': 'npm install'})";
    const label = parseToolLabel(message);
    expect(label).toContain('🌿 powershell - npm install');
  });
});

describe('isToolCallMessage', () => {
  it('matches [Tool] prefix', () => {
    expect(isToolCallMessage("[Tool] grep({'pattern': 'foo'})")).toBe(true);
  });

  it('matches 🌿 prefix', () => {
    expect(isToolCallMessage("🌿 view({'path': 'README.md'})")).toBe(true);
  });

  it('matches 🔧 prefix', () => {
    expect(isToolCallMessage("🔧 powershell({'command': 'npm test'})")).toBe(true);
  });

  it('matches 🔧 with leading whitespace', () => {
    expect(isToolCallMessage("  🔧 grep({'pattern': 'TODO'})")).toBe(true);
  });

  it('does not match regular text', () => {
    expect(isToolCallMessage("Installing dependencies...")).toBe(false);
  });
});

describe('buildToolSummary', () => {
  it('includes description from tool call message', () => {
    const callMessage = "[Tool] view({'path': 'README.md'})";
    const summary = buildToolSummary(callMessage);
    expect(summary.toolLabel).toBe('🌿 view - README.md');
  });

  it('includes both description and result summary', () => {
    const callMessage = "[Tool] grep({'pattern': 'TODO'})";
    const resultMessage = "✅ Result: Found 5 matches";
    const summary = buildToolSummary(callMessage, resultMessage);
    expect(summary.toolLabel).toBe('🌿 grep - TODO');
    expect(summary.resultSummary).toBe('✅ Found 5 matches');
  });

  it('handles 🔧 prefixed tool call', () => {
    const callMessage = "🔧 powershell({'command': 'npm run build'})";
    const resultMessage = "✅ Result: Build succeeded";
    const summary = buildToolSummary(callMessage, resultMessage);
    expect(summary.toolLabel).toContain('🌿 powershell');
    expect(summary.resultSummary).toBe('✅ Build succeeded');
    expect(summary.statusClass).toBe('log-success');
  });
});

describe('processLogsToRenderItems', () => {
  it('collapses a 🔧 tool call with immediate result', () => {
    const logs: LogEntry[] = [
      makeEntry("🔧 grep({'pattern': 'TODO'})", 1000),
      makeEntry("✅ Result: Found 5 matches", 1001),
    ];
    const items = processLogsToRenderItems(logs);
    expect(items).toHaveLength(1);
    expect(items[0].type).toBe('tool');
    if (items[0].type === 'tool') {
      expect(items[0].tool.toolName).toBe('grep');
      expect(items[0].tool.result).toBeDefined();
      expect(items[0].tool.summary.resultSummary).toContain('Found 5 matches');
    }
  });

  it('collapses a 🔧 tool call with streaming output before result', () => {
    const logs: LogEntry[] = [
      makeEntry("🔧 powershell({'command': 'npm install'})", 1000),
      makeEntry("Installing dependencies...", 1001),
      makeEntry("added 100 packages", 1002),
      makeEntry("✅ Result: Packages installed", 1003),
    ];
    const items = processLogsToRenderItems(logs);
    expect(items).toHaveLength(1);
    expect(items[0].type).toBe('tool');
    if (items[0].type === 'tool') {
      expect(items[0].tool.toolName).toBe('powershell');
      expect(items[0].tool.result).toBeDefined();
      expect(items[0].tool.additionalEntries).toHaveLength(2);
    }
  });

  it('does not consume intermediate lines when no result follows', () => {
    const logs: LogEntry[] = [
      makeEntry("🔧 powershell({'command': 'npm install'})", 1000),
      makeEntry("Installing dependencies...", 1001),
      makeEntry("Some other output", 1002),
    ];
    const items = processLogsToRenderItems(logs);
    // Tool call without result + 2 regular log entries (merged into markdown block or plain)
    expect(items.length).toBeGreaterThanOrEqual(2);
    expect(items[0].type).toBe('tool');
    if (items[0].type === 'tool') {
      expect(items[0].tool.result).toBeUndefined();
      expect(items[0].tool.additionalEntries).toBeUndefined();
    }
  });

  it('handles multiple 🔧 tool calls in sequence', () => {
    const logs: LogEntry[] = [
      makeEntry("🔧 grep({'pattern': 'TODO'})", 1000),
      makeEntry("✅ Result: Found 5 matches", 1001),
      makeEntry("🔧 view({'path': 'README.md'})", 1002),
      makeEntry("✅ Result: File contents shown", 1003),
    ];
    const items = processLogsToRenderItems(logs);
    expect(items).toHaveLength(1);
    // Two tool calls should be batched
    expect(items[0].type).toBe('tool-batch');
  });
});
