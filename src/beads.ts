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

    let stdout = '';
    let stderr = '';

    process.stdout.on('data', (data: Buffer) => {
      stdout += data.toString();
    });

    process.stderr.on('data', (data: Buffer) => {
      stderr += data.toString();
    });

    process.on('close', (code) => {
      if (code !== 0) {
        reject(new Error(`bd ready failed with code ${code}: ${stderr}`));
        return;
      }

      try {
        // Parse JSON output from bd ready
        const lines = stdout.split('\n').filter((line) => line.trim());
        const jsonLine = lines.find((line) => line.trim().startsWith('['));

        if (!jsonLine) {
          resolve([]);
          return;
        }

        const items = JSON.parse(jsonLine) as BeadsWorkItem[];
        resolve(items);
      } catch (error) {
        reject(new Error(`Failed to parse bd ready output: ${String(error)}`));
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
