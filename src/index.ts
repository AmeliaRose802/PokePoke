#!/usr/bin/env node
/**
 * PokePoke - Autonomous Beads + Copilot CLI Orchestrator
 * Entry point for the orchestrator
 */

import { getFirstReadyWorkItem } from './beads.js';
import { invokeCopilotCLI } from './copilot.js';

async function main(): Promise<void> {
  console.info('🤖 PokePoke orchestrator starting...\n');

  try {
    // Step 1: Query beads for ready work
    console.info('1️⃣ Querying beads for ready work items...');
    const workItem = await getFirstReadyWorkItem();

    if (!workItem) {
      console.info('   ℹ️ No ready work items found. Exiting.\n');
      return;
    }

    console.info(`   ✓ Found work item: ${workItem.id} - ${workItem.title}\n`);

    // Step 2: Invoke Copilot CLI with work item
    console.info('2️⃣ Invoking GitHub Copilot CLI...');
    const result = await invokeCopilotCLI(workItem);

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
