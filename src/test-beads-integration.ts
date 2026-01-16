/**
 * Integration test - manual verification script
 * Run with: node dist/test-beads-integration.js
 */

import { getReadyWorkItems, getFirstReadyWorkItem } from './beads.js';

async function main(): Promise<void> {
  console.info('Testing beads integration...\n');

  try {
    // Test getReadyWorkItems
    console.info('1. Testing getReadyWorkItems()...');
    const items = await getReadyWorkItems();
    console.info(`   Found ${items.length} ready work items`);
    if (items.length > 0) {
      console.info(`   First item: ${items[0].id} - ${items[0].title}`);
    }

    // Test getFirstReadyWorkItem
    console.info('\n2. Testing getFirstReadyWorkItem()...');
    const firstItem = await getFirstReadyWorkItem();
    if (firstItem) {
      console.info(`   ID: ${firstItem.id}`);
      console.info(`   Title: ${firstItem.title}`);
      console.info(`   Status: ${firstItem.status}`);
      console.info(`   Priority: ${firstItem.priority}`);
    } else {
      console.info('   No items available');
    }

    console.info('\n✓ Integration test passed!');
  } catch (error) {
    console.error('\n✗ Integration test failed:', error);
    process.exit(1);
  }
}

main().catch((error) => {
  console.error('Unexpected error:', error);
  process.exit(1);
});
