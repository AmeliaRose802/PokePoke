import { spawn } from 'child_process';
import type { BeadsWorkItem } from './types.js';

/**
 * Query beads database for ready work items
 * @returns Promise resolving to array of ready work items
 */
export async function getReadyWorkItems(): Promise<BeadsWorkItem[]> {
  return new Promise((resolve, reject) => {
    const process = spawn('bd', ['ready', '--json'], {
      shell: true,
      stdio: ['ignore', 'pipe', 'pipe'],
    });

    const stdoutChunks: Buffer[] = [];
    const stderrChunks: Buffer[] = [];

    process.stdout.on('data', (data: Buffer) => {
      stdoutChunks.push(data);
    });

    process.stderr.on('data', (data: Buffer) => {
      stderrChunks.push(data);
    });

    process.on('close', (code) => {
      const stdout = Buffer.concat(stdoutChunks).toString();
      const stderr = Buffer.concat(stderrChunks).toString();

      if (code !== 0) {
        reject(new Error(`bd ready failed with code ${code}: ${stderr}`));
        return;
      }

      try {
        // Parse JSON output from bd ready
        // Filter out warning/note lines
        const filteredLines = stdout.split('\n').filter((line) => {
          const trimmed = line.trim();
          return (
            trimmed &&
            !trimmed.startsWith('Note:') &&
            !trimmed.startsWith('Warning:') &&
            !trimmed.startsWith('Hint:')
          );
        });

        // Find the start of JSON array and collect all JSON lines
        const jsonStartIndex = filteredLines.findIndex((line) => line.trim().startsWith('['));
        
        if (jsonStartIndex === -1) {
          resolve([]);
          return;
        }

        // Join all lines from JSON start onwards
        const jsonText = filteredLines.slice(jsonStartIndex).join('\n');

        if (jsonText.trim() === '[]') {
          resolve([]);
          return;
        }

        const items = JSON.parse(jsonText) as BeadsWorkItem[];
        resolve(items);
      } catch (error) {
        reject(new Error(`Failed to parse bd ready output: ${String(error)}\nOutput: ${stdout}`));
      }
    });

    process.on('error', (error) => {
      reject(new Error(`Failed to spawn bd process: ${String(error)}`));
    });
  });
}

/**
 * Get the first ready work item
 * @returns Promise resolving to the first ready work item, or null if none available
 */
export async function getFirstReadyWorkItem(): Promise<BeadsWorkItem | null> {
  const items = await getReadyWorkItems();
  return items.length > 0 ? items[0] : null;
}
