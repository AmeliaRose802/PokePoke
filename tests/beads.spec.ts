import { describe, it, expect, beforeEach, afterEach, jest } from '@jest/globals';
import { getReadyWorkItems, getFirstReadyWorkItem } from '../src/beads.js';
import type { BeadsWorkItem } from '../src/types.js';
import { ChildProcess } from 'child_process';

// Mock child_process module
const mockSpawn = jest.fn();
jest.unstable_mockModule('child_process', () => ({
  spawn: mockSpawn,
}));

describe('beads integration', () => {
  let mockProcess: {
    stdout: { on: jest.Mock };
    stderr: { on: jest.Mock };
    on: jest.Mock;
  };

  beforeEach(() => {
    // Create mock process
    mockProcess = {
      stdout: { on: jest.fn() },
      stderr: { on: jest.fn() },
      on: jest.fn(),
    };

    // Mock the spawn function to return our mock process
    mockSpawn.mockReturnValue(mockProcess as unknown as ChildProcess);
  });

  afterEach(() => {
    jest.clearAllMocks();
  });

  describe('getReadyWorkItems', () => {
    it('should parse bd ready output and return work items', async () => {
      const mockItems: BeadsWorkItem[] = [
        {
          id: 'test-123',
          title: 'Test task',
          description: 'Test description',
          status: 'open',
          priority: 1,
          issue_type: 'task',
          created_at: '2026-01-16T00:00:00Z',
          created_by: 'Test User',
          updated_at: '2026-01-16T00:00:00Z',
        },
      ];

      const jsonOutput = JSON.stringify(mockItems);

      // Simulate successful command execution
      mockProcess.stdout.on.mockImplementation((...args: unknown[]) => {
        const [event, callback] = args as [string, (data: Buffer) => void];
        if (event === 'data') {
          callback(Buffer.from(jsonOutput));
        }
      });

      mockProcess.on.mockImplementation((...args: unknown[]) => {
        const [event, callback] = args as [string, (code: number) => void];
        if (event === 'close') {
          callback(0);
        }
      });

      const result = await getReadyWorkItems();

      expect(mockSpawn).toHaveBeenCalledWith('bd', ['ready', '--json'], {
        shell: true,
        stdio: ['ignore', 'pipe', 'pipe'],
      });
      expect(result).toEqual(mockItems);
    });

    it('should return empty array when no items are ready', async () => {
      const jsonOutput = '[]';

      mockProcess.stdout.on.mockImplementation((...args: unknown[]) => {
        const [event, callback] = args as [string, (data: Buffer) => void];
        if (event === 'data') {
          callback(Buffer.from(jsonOutput));
        }
      });

      mockProcess.on.mockImplementation((...args: unknown[]) => {
        const [event, callback] = args as [string, (code: number) => void];
        if (event === 'close') {
          callback(0);
        }
      });

      const result = await getReadyWorkItems();

      expect(result).toEqual([]);
    });

    it('should handle bd ready command failure', async () => {
      const errorMessage = 'bd command not found';

      mockProcess.stderr.on.mockImplementation((...args: unknown[]) => {
        const [event, callback] = args as [string, (data: Buffer) => void];
        if (event === 'data') {
          callback(Buffer.from(errorMessage));
        }
      });

      mockProcess.on.mockImplementation((...args: unknown[]) => {
        const [event, callback] = args as [string, (code: number) => void];
        if (event === 'close') {
          callback(1);
        }
      });

      await expect(getReadyWorkItems()).rejects.toThrow('bd ready failed with code 1');
    });

    it('should handle invalid JSON output', async () => {
      const invalidOutput = 'not valid json';

      mockProcess.stdout.on.mockImplementation((...args: unknown[]) => {
        const [event, callback] = args as [string, (data: Buffer) => void];
        if (event === 'data') {
          callback(Buffer.from(invalidOutput));
        }
      });

      mockProcess.on.mockImplementation((...args: unknown[]) => {
        const [event, callback] = args as [string, (code: number) => void];
        if (event === 'close') {
          callback(0);
        }
      });

      await expect(getReadyWorkItems()).rejects.toThrow('Failed to parse bd ready output');
    });
  });

  describe('getFirstReadyWorkItem', () => {
    it('should return the first work item when items are available', async () => {
      const mockItems: BeadsWorkItem[] = [
        {
          id: 'test-123',
          title: 'First task',
          description: 'First description',
          status: 'open',
          priority: 1,
          issue_type: 'task',
          created_at: '2026-01-16T00:00:00Z',
          created_by: 'Test User',
          updated_at: '2026-01-16T00:00:00Z',
        },
        {
          id: 'test-456',
          title: 'Second task',
          description: 'Second description',
          status: 'open',
          priority: 2,
          issue_type: 'task',
          created_at: '2026-01-16T00:00:00Z',
          created_by: 'Test User',
          updated_at: '2026-01-16T00:00:00Z',
        },
      ];

      const jsonOutput = JSON.stringify(mockItems);

      mockProcess.stdout.on.mockImplementation((...args: unknown[]) => {
        const [event, callback] = args as [string, (data: Buffer) => void];
        if (event === 'data') {
          callback(Buffer.from(jsonOutput));
        }
      });

      mockProcess.on.mockImplementation((...args: unknown[]) => {
        const [event, callback] = args as [string, (code: number) => void];
        if (event === 'close') {
          callback(0);
        }
      });

      const result = await getFirstReadyWorkItem();

      expect(result).toEqual(mockItems[0]);
    });

    it('should return null when no items are available', async () => {
      const jsonOutput = '[]';

      mockProcess.stdout.on.mockImplementation((...args: unknown[]) => {
        const [event, callback] = args as [string, (data: Buffer) => void];
        if (event === 'data') {
          callback(Buffer.from(jsonOutput));
        }
      });

      mockProcess.on.mockImplementation((...args: unknown[]) => {
        const [event, callback] = args as [string, (code: number) => void];
        if (event === 'close') {
          callback(0);
        }
      });

      const result = await getFirstReadyWorkItem();

      expect(result).toBeNull();
    });
  });
});
