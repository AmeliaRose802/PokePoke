import { spawn } from 'child_process';
import type { BeadsWorkItem, IssueWithDependencies } from './types.js';

/**
 * Query beads database for ready work items
 * @returns Promise resolving to array of ready work items
 */
export async function getReadyWorkItems(): Promise<BeadsWorkItem[]> {
  return new Promise((resolve, reject) => {
    const process = spawn('bd ready --json', {
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
 * Get detailed issue information including dependencies
 * @param issueId - The issue ID to query
 * @returns Promise resolving to issue with dependencies
 */
async function getIssueDependencies(issueId: string): Promise<IssueWithDependencies | null> {
  return new Promise((resolve, reject) => {
    const process = spawn(`bd show ${issueId} --json`, {
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
        reject(new Error(`bd show failed with code ${code}: ${stderr}`));
        return;
      }

      try {
        const filteredLines = stdout.split('\n').filter((line) => {
          const trimmed = line.trim();
          return (
            trimmed &&
            !trimmed.startsWith('Note:') &&
            !trimmed.startsWith('Warning:') &&
            !trimmed.startsWith('Hint:')
          );
        });

        const jsonStartIndex = filteredLines.findIndex((line) => line.trim().startsWith('['));
        
        if (jsonStartIndex === -1) {
          resolve(null);
          return;
        }

        const jsonText = filteredLines.slice(jsonStartIndex).join('\n');
        const issues = JSON.parse(jsonText) as IssueWithDependencies[];
        resolve(issues.length > 0 ? issues[0] : null);
      } catch (error) {
        reject(new Error(`Failed to parse bd show output: ${String(error)}\nOutput: ${stdout}`));
      }
    });

    process.on('error', (error) => {
      reject(new Error(`Failed to spawn bd process: ${String(error)}`));
    });
  });
}

/**
 * Check if an issue has a parent that is a feature
 * @param issueId - The issue ID to check
 * @returns Promise resolving to true if has feature parent, false otherwise
 */
async function hasFeatureParent(issueId: string): Promise<boolean> {
  try {
    const issue = await getIssueDependencies(issueId);
    if (!issue || !issue.dependencies) {
      return false;
    }

    // Check if any dependency is a parent relationship with type 'feature'
    return issue.dependencies.some(
      (dep) => dep.dependency_type === 'parent' && dep.issue_type === 'feature'
    );
  } catch (error) {
    console.warn(`Warning: Failed to check dependencies for ${issueId}: ${String(error)}`);
    return false;
  }
}

/**
 * Filter work items based on selection criteria:
 * - Exclude epics (too broad)
 * - Include features
 * - Include tasks/bugs/chores only if NOT parented to a feature
 * @param items - Array of work items to filter
 * @returns Promise resolving to filtered array
 */
async function filterWorkItems(items: BeadsWorkItem[]): Promise<BeadsWorkItem[]> {
  const filtered: BeadsWorkItem[] = [];

  for (const item of items) {
    // Skip epics - too broad
    if (item.issue_type === 'epic') {
      console.info(`   ⏭️  Skipping epic: ${item.id} - ${item.title}`);
      continue;
    }

    // Always include features
    if (item.issue_type === 'feature') {
      filtered.push(item);
      continue;
    }

    // For tasks, bugs, chores - only include if NOT parented to a feature
    if (['task', 'bug', 'chore'].includes(item.issue_type)) {
      const hasFeature = await hasFeatureParent(item.id);
      if (hasFeature) {
        console.info(`   ⏭️  Skipping ${item.issue_type} with feature parent: ${item.id} - ${item.title}`);
        continue;
      }
      filtered.push(item);
      continue;
    }

    // Include any other types by default
    filtered.push(item);
  }

  return filtered;
}

/**
 * Get the first ready work item that meets selection criteria
 * @returns Promise resolving to the first ready work item, or null if none available
 */
export async function getFirstReadyWorkItem(): Promise<BeadsWorkItem | null> {
  const items = await getReadyWorkItems();
  const filtered = await filterWorkItems(items);
  return filtered.length > 0 ? filtered[0] : null;
}
