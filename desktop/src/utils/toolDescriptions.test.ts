/**
 * Tests for toolDescriptions utility functions.
 */

import { describe, expect, it } from 'vitest';

import { extractDescriptionFromArgs } from './toolDescriptions';

describe('extractDescriptionFromArgs', () => {
  describe('JSON format (single quotes)', () => {
    it('extracts path for view tool', () => {
      expect(extractDescriptionFromArgs('view', "{'path': 'README.md'}")).toBe('README.md');
    });

    it('extracts command for powershell tool', () => {
      expect(extractDescriptionFromArgs('powershell', "{'command': 'npm run build'}")).toBe('npm run build');
    });

    it('extracts pattern for grep tool', () => {
      expect(extractDescriptionFromArgs('grep', "{'pattern': 'TODO', 'path': 'src/'}")).toBe('TODO');
    });

    it('extracts path for edit tool', () => {
      expect(extractDescriptionFromArgs('edit', "{'path': 'src/app.ts'}")).toBe('src/app.ts');
    });

    it('extracts path for create tool', () => {
      expect(extractDescriptionFromArgs('create', "{'path': 'src/new.ts'}")).toBe('src/new.ts');
    });

    it('extracts pattern for glob tool', () => {
      expect(extractDescriptionFromArgs('glob', "{'pattern': '**/*.ts'}")).toBe('**/*.ts');
    });

    it('prefers description field over command', () => {
      expect(extractDescriptionFromArgs('powershell', "{'description': 'Install deps', 'command': 'npm install'}")).toBe('Install deps');
    });
  });

  describe('JSON format (double quotes)', () => {
    it('extracts path for view tool', () => {
      expect(extractDescriptionFromArgs('view', '{"path": "README.md"}')).toBe('README.md');
    });

    it('extracts command for powershell tool', () => {
      expect(extractDescriptionFromArgs('powershell', '{"command": "npm test"}')).toBe('npm test');
    });
  });

  describe('regex fallback for non-JSON formats', () => {
    it('extracts path with equals sign syntax', () => {
      expect(extractDescriptionFromArgs('view', 'path="src/file.ts"')).toBe('src/file.ts');
    });

    it('extracts path with colon syntax', () => {
      expect(extractDescriptionFromArgs('view', 'path: "src/file.ts"')).toBe('src/file.ts');
    });

    it('extracts command for powershell with equals', () => {
      expect(extractDescriptionFromArgs('powershell', 'command="npm run build"')).toBe('npm run build');
    });

    it('extracts pattern for grep with single quotes', () => {
      expect(extractDescriptionFromArgs('grep', "pattern='TODO'")).toBe('TODO');
    });

    it('prefers description field in non-JSON', () => {
      expect(extractDescriptionFromArgs('powershell', 'description="Build project", command="npm run build"')).toBe('Build project');
    });

    it('extracts path for apply_patch', () => {
      expect(extractDescriptionFromArgs('apply_patch', 'path="src/index.ts"')).toBe('src/index.ts');
    });

    it('extracts query first line for run_kusto_query', () => {
      expect(extractDescriptionFromArgs('run_kusto_query', 'query="Incidents | where Id > 0"')).toBe('Incidents | where Id > 0');
    });
  });

  describe('edge cases', () => {
    it('returns undefined for empty args', () => {
      expect(extractDescriptionFromArgs('view', '')).toBeUndefined();
    });

    it('returns undefined for undefined args', () => {
      expect(extractDescriptionFromArgs('view', undefined)).toBeUndefined();
    });

    it('returns undefined for unknown tool with no description', () => {
      expect(extractDescriptionFromArgs('unknown_tool', 'foo=bar')).toBeUndefined();
    });

    it('returns undefined when no recognizable pattern', () => {
      expect(extractDescriptionFromArgs('view', 'just some random text')).toBeUndefined();
    });
  });
});
