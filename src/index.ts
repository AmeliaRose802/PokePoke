#!/usr/bin/env node
/**
 * PokePoke - Autonomous Beads + Copilot CLI Orchestrator
 * Entry point for the orchestrator
 */

import * as readline from 'readline';
import { getFirstReadyWorkItem } from './beads.js';
import { invokeCopilotCLI, buildPrompt } from './copilot.js';

/**
 * Prompt user for approval
 */
function promptForApproval(question: string): Promise<boolean> {
  const rl = readline.createInterface({
    input: process.stdin,
    output: process.stdout,
  });

  return new Promise((resolve) => {
    rl.question(question, (answer) => {
      rl.close();
      const normalized = answer.trim().toLowerCase();
      resolve(normalized === 'y' || normalized === 'yes');
    });
  });
}

/**
 * Display work item details for review
 */
function displayWorkItem(workItem: any): void {
  console.info('\n' + '='.repeat(80));
  console.info('📋 WORK ITEM SELECTED');
  console.info('='.repeat(80));
  console.info(`ID:          ${workItem.id}`);
  console.info(`Title:       ${workItem.title}`);
  console.info(`Type:        ${workItem.issue_type}`);
  console.info(`Priority:    ${workItem.priority}`);
  console.info(`Status:      ${workItem.status}`);
  if (workItem.labels && workItem.labels.length > 0) {
    console.info(`Labels:      ${workItem.labels.join(', ')}`);
  }
  console.info(`\nDescription:\n${workItem.description || '(no description)'}`);
  console.info('='.repeat(80) + '\n');
}

/**
 * Display the prompt that will be sent to Copilot
 */
function displayPrompt(prompt: string): void {
  console.info('\n' + '='.repeat(80));
  console.info('💬 PROMPT TO BE SENT TO COPILOT CLI');
  console.info('='.repeat(80));
  console.info(prompt);
  console.info('='.repeat(80) + '\n');
}

async function main(): Promise<void> {
  console.info('🤖 PokePoke orchestrator starting (interactive mode)...\n');

  try {
    // Step 1: Query beads for ready work
    console.info('1️⃣ Querying beads for ready work items...');
    const workItem = await getFirstReadyWorkItem();

    if (!workItem) {
      console.info('   ℹ️ No ready work items found. Exiting.\n');
      return;
    }

    console.info(`   ✓ Found work item: ${workItem.id} - ${workItem.title}\n`);

    // Step 1.5: Display work item and get approval
    displayWorkItem(workItem);
    const approveWorkItem = await promptForApproval('❓ Proceed with this work item? (y/n): ');
    
    if (!approveWorkItem) {
      console.info('   ❌ Work item rejected. Exiting.\n');
      return;
    }

    // Step 1.75: Show prompt and get approval
    const prompt = buildPrompt(workItem);
    displayPrompt(prompt);
    const approvePrompt = await promptForApproval('❓ Send this prompt to Copilot CLI? (y/n): ');
    
    if (!approvePrompt) {
      console.info('   ❌ Prompt rejected. Exiting.\n');
      return;
    }

    // Step 2: Invoke Copilot CLI with work item
    console.info('\n2️⃣ Invoking GitHub Copilot CLI...');
    const result = await invokeCopilotCLI(workItem, prompt);

    // Step 3: Report completion status
    console.info('\n3️⃣ Reporting completion status...');
    if (result.success) {
      console.info(`   ✓ Work item ${result.workItemId} completed successfully!`);
      if (result.output) {
        console.info(`\n📄 Output:\n${result.output}`);
      }
    } else {
      console.error(`   ✗ Work item ${result.workItemId} failed:`);
      console.error(`     ${result.error}`);
      process.exit(1);
    }

    console.info('\n✨ PokePoke orchestrator finished successfully!\n');
  } catch (error) {
    console.error('\n❌ Orchestrator error:', error);
    process.exit(1);
  }
}

main().catch((error) => {
  console.error('Unexpected error:', error);
  process.exit(1);
});
