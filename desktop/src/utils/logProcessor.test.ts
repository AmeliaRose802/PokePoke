/**
 * Tests for logProcessor utility functions.
 */

import { describe, expect, it } from 'vitest';

import { buildToolSummary,parseToolLabel } from './logProcessor';

describe('parseToolLabel', () => {
  it('extracts tool name and path for view tool', () => {
    const message = "[Tool] view({'path': 'README.md'})";
    const label = parseToolLabel(message);
    expect(label).toBe('🔧 view - README.md');
  });

  it('extracts tool name and command for powershell tool', () => {
    const message = "[Tool] powershell({'command': 'npm run build', 'shellId': 'shell-1'})";
    const label = parseToolLabel(message);
    expect(label).toContain('🔧 powershell - npm run build');
  });

  it('extracts tool name and pattern for grep tool', () => {
    const message = "[Tool] grep({'pattern': 'TODO', 'path': 'src/'})";
    const label = parseToolLabel(message);
    expect(label).toBe('🔧 grep - TODO');
  });

  it('extracts tool name and path for edit tool', () => {
    const message = "[Tool] edit({'path': 'src/app.ts'})";
    const label = parseToolLabel(message);
    expect(label).toBe('🔧 edit - src/app.ts');
  });

  it('extracts tool name and path for create tool', () => {
    const message = "[Tool] create({'path': 'src/components/NewComponent.tsx'})";
    const label = parseToolLabel(message);
    expect(label).toBe('🔧 create - src/components/NewComponent.tsx');
  });

  it('extracts tool name and pattern for glob tool', () => {
    const message = "[Tool] glob({'pattern': '**/*.ts'})";
    const label = parseToolLabel(message);
    expect(label).toBe('🔧 glob - **/*.ts');
  });

  it('returns just tool name if no description available', () => {
    const message = "[Tool] report_intent({'intent': 'Testing'})";
    const label = parseToolLabel(message);
    expect(label).toBe('🔧 report_intent');
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
});

describe('buildToolSummary', () => {
  it('includes description from tool call message', () => {
    const callMessage = "[Tool] view({'path': 'README.md'})";
    const summary = buildToolSummary(callMessage);
    expect(summary.toolLabel).toBe('🔧 view - README.md');
  });

  it('includes both description and result summary', () => {
    const callMessage = "[Tool] grep({'pattern': 'TODO'})";
    const resultMessage = "✅ Result: Found 5 matches";
    const summary = buildToolSummary(callMessage, resultMessage);
    expect(summary.toolLabel).toBe('🔧 grep - TODO');
    expect(summary.resultSummary).toBe('✅ Found 5 matches');
  });
});
