import { spawn } from 'child_process';
import type { BeadsWorkItem, CopilotResult } from './types.js';

/**
 * Invoke GitHub Copilot CLI with a work item
 * @param workItem - The beads work item to process
 * @returns Promise resolving to the result of the Copilot CLI invocation
 */
export async function invokeCopilotCLI(workItem: BeadsWorkItem): Promise<CopilotResult> {
  return new Promise((resolve) => {
    const prompt = buildPrompt(workItem);

    console.info(`\n📋 Invoking Copilot CLI for work item: ${workItem.id}`);
    console.info(`   Title: ${workItem.title}\n`);

    // Use 'copilot -p' with --allow-all-tools for non-interactive mode
    const process = spawn(
      'copilot',
      ['-p', prompt, '--allow-all-tools', '--no-color'],
      {
        shell: true,
        stdio: ['ignore', 'pipe', 'pipe'],
      }
    );

    const stdoutChunks: Buffer[] = [];
    const stderrChunks: Buffer[] = [];

    process.stdout.on('data', (data: Buffer) => {
      stdoutChunks.push(data);
      // Echo output in real-time for visibility
      console.info(data.toString());
    });

    process.stderr.on('data', (data: Buffer) => {
      stderrChunks.push(data);
      // Echo errors in real-time
      console.error(data.toString());
    });

    process.on('close', (code) => {
      const stdout = Buffer.concat(stdoutChunks).toString();
      const stderr = Buffer.concat(stderrChunks).toString();

      if (code !== 0) {
        resolve({
          workItemId: workItem.id,
          success: false,
          error: `Copilot CLI exited with code ${code}: ${stderr || 'Unknown error'}`,
        });
        return;
      }

      resolve({
        workItemId: workItem.id,
        success: true,
        output: stdout,
      });
    });

    process.on('error', (error) => {
      resolve({
        workItemId: workItem.id,
        success: false,
        error: `Failed to spawn Copilot CLI: ${String(error)}`,
      });
    });
  });
}

/**
 * Build a prompt for Copilot CLI from a work item
 * @param workItem - The beads work item
 * @returns Formatted prompt string
 */
function buildPrompt(workItem: BeadsWorkItem): string {
  return `You are working on a beads work item. Please complete the following task:

**Work Item ID:** ${workItem.id}
**Title:** ${workItem.title}
**Description:**
${workItem.description}

**Priority:** ${workItem.priority}
**Type:** ${workItem.issue_type}
${workItem.labels && workItem.labels.length > 0 ? `**Labels:** ${workItem.labels.join(', ')}` : ''}

Please implement this task according to the project guidelines and best practices. Make sure to:
1. Follow the coding standards
2. Add appropriate tests
3. Update documentation if needed
4. Commit your changes with a descriptive message

Work independently and let me know when complete.`;
}
