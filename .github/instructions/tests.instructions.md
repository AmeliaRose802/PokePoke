---
applyTo: "mcp_server/test/**"
---

# Testing Instructions

This directory contains unit and integration tests for the MCP server.

## Test Structure

```
test/
├── setup.ts              # Jest configuration and global setup
├── unit/                 # Unit tests (fast, mocked dependencies)
│   ├── config.test.ts
│   ├── services/
│   └── utils/
└── integration/          # Integration tests (slower, real APIs)
    ├── wiql-query.test.ts
    └── work-item.test.ts
```

## Running Tests

```bash
# Run all tests
npm test

# Run specific test file
npm test -- config.test.ts

# Run tests in watch mode
npm test -- --watch

# Run with coverage
npm run test:coverage

# Run only unit tests
npm test -- unit/

# Run only integration tests
npm test -- integration/
```

## Test File Naming Conventions

- Unit tests: `<module-name>.test.ts`
- Integration tests: `<feature>-integration.test.ts`
- Test utilities: `<helper-name>.test-helper.ts`

## Writing Unit Tests

### Standard Test Structure

```typescript
import { describe, it, expect, beforeEach, afterEach, jest } from '@jest/globals';
import { MyService } from '../../src/services/my-service';

describe('MyService', () => {
  let service: MyService;
  let mockDependency: jest.Mocked<Dependency>;

  beforeEach(() => {
    // Setup before each test
    mockDependency = {
      method: jest.fn()
    } as any;
    
    service = new MyService(mockDependency);
  });

  afterEach(() => {
    // Cleanup after each test
    jest.clearAllMocks();
  });

  describe('methodName', () => {
    it('should handle valid input correctly', () => {
      // Arrange
      const input = { value: 'test' };
      mockDependency.method.mockResolvedValue('result');

      // Act
      const result = service.methodName(input);

      // Assert
      expect(result).toBeDefined();
      expect(mockDependency.method).toHaveBeenCalledWith('test');
    });

    it('should throw error for invalid input', () => {
      // Arrange
      const input = { value: null };

      // Act & Assert
      expect(() => service.methodName(input)).toThrow('Invalid input');
    });

    it('should handle async errors gracefully', async () => {
      // Arrange
      mockDependency.method.mockRejectedValue(new Error('API failed'));

      // Act & Assert
      await expect(service.methodName({ value: 'test' }))
        .rejects
        .toThrow('API failed');
    });
  });
});
```

### Mocking External Dependencies

#### Mocking Kusto Client

```typescript
import { Client as KustoClient } from 'azure-kusto-data';

jest.mock('azure-kusto-data', () => ({
  Client: jest.fn().mockImplementation(() => ({
    execute: jest.fn().mockResolvedValue({
      primaryResults: [{
        rows: jest.fn().mockReturnValue([
          { IncidentId: 12345, Title: 'Test Incident', Status: 'Active' }
        ])
      }]
    })
  }))
}));

const mockClient = new KustoClient('mock-connection-string');
```

#### Mocking Azure CLI Authentication

```typescript
import { AzureCliCredential } from '@azure/identity';

jest.mock('@azure/identity', () => ({
  AzureCliCredential: jest.fn().mockImplementation(() => ({
    getToken: jest.fn().mockResolvedValue({
      token: 'mock-token',
      expiresOnTimestamp: Date.now() + 3600000
    })
  }))
}));
```

#### Mocking File System

```typescript
import fs from 'fs/promises';

jest.mock('fs/promises');

const mockFs = fs as jest.Mocked<typeof fs>;

beforeEach(() => {
  mockFs.readFile.mockResolvedValue('mock file content');
});
```

### Test Coverage Goals

- **Statements:** > 80%
- **Branches:** > 75%
- **Functions:** > 80%
- **Lines:** > 80%

### What to Test

✅ **Do Test:**
- Happy path (valid input → expected output)
- Error handling (invalid input → proper error)
- Edge cases (empty arrays, null values, boundaries)
- Business logic validation
- State transitions
- Error message accuracy

❌ **Don't Test:**
- External library internals
- Simple getters/setters
- TypeScript type system
- Configuration constant values

## Writing Integration Tests

### Integration Test Structure

```typescript
import { describe, it, expect, beforeAll, afterAll } from '@jest/globals';
import { KustoService } from '../../src/kusto-client';

describe('Kusto Incident Query Integration', () => {
  let kustoService: KustoService;
  const testIncidentId = 698227509; // Known test incident

  beforeAll(async () => {
    // One-time setup
    kustoService = new KustoService();
  });

  afterAll(async () => {
    // Cleanup if needed
  });

  it('should fetch incident by ID', async () => {
    const query = `
      Incidents
      | where IncidentId == ${testIncidentId}
      | take 1
    `;
    
    const result = await kustoService.executeQuery(
      'icmcluster',
      'IcMDataWarehouse',
      query
    );
    
    expect(result).toBeDefined();
    expect(result.length).toBeGreaterThan(0);
    expect(result[0].IncidentId).toBe(testIncidentId);
  });

  it('should retrieve incident history', async () => {
    const query = `
      IncidentHistory
      | where IncidentId == ${testIncidentId}
      | order by ModifiedDate asc
      | take 10
    `;

    const result = await kustoService.executeQuery(
      'icmcluster',
      'IcMDataWarehouse',
      query
    );

    expect(result).toBeDefined();
    expect(Array.isArray(result)).toBe(true);
  });
});
```

### Integration Test Best Practices

- **Use real environment** - Test against actual Kusto clusters (dev/test cluster)
- **Use known test data** - Query known incidents (don't create test data)
- **Skip if no auth** - Check for Azure CLI authentication
- **Run less frequently** - Slow, can hit query limits
- **Isolate tests** - Each test should be independent
- **Limit query scope** - Use `take` to limit result size

### Skipping Integration Tests

```typescript
describe.skip('Kusto Integration (requires authentication)', () => {
  // Tests skipped by default
});

// Or conditionally skip
const hasAuth = process.env.AZURE_TENANT_ID || checkAzureCliAuth();

(hasAuth ? describe : describe.skip)('Kusto Integration', () => {
  // Tests run only if authenticated
});
```

## Test Utilities and Helpers

### Creating Test Helpers

```typescript
// test/helpers/work-item-factory.ts
export function createMockWorkItem(overrides?: Partial<WorkItem>): WorkItem {
  return {
    id: 12345,
    fields: {
      'System.Title': 'Test Item',
      'System.State': 'Active',
      'System.WorkItemType': 'Task',
      ...overrides?.fields
    },
    ...overrides
  };
}
```

### Using Test Helpers

```typescript
import { createMockWorkItem } from '../helpers/work-item-factory';

it('should analyze work item', () => {
  const workItem = createMockWorkItem({
    fields: {
      'System.State': 'In Progress'
    }
  });

  const result = analyzer.analyze(workItem);
  expect(result.state).toBe('In Progress');
});
```

## Testing Async Code

### Promises

```typescript
it('should resolve with result', async () => {
  const promise = service.fetchData();
  await expect(promise).resolves.toBe('data');
});

it('should reject with error', async () => {
  const promise = service.fetchInvalidData();
  await expect(promise).rejects.toThrow('Not found');
});
```

### Callbacks

```typescript
it('should call callback with result', (done) => {
  service.fetchData((error, result) => {
    expect(error).toBeNull();
    expect(result).toBe('data');
    done();
  });
});
```

### Timeouts

```typescript
it('should timeout long operations', async () => {
  const promise = service.slowOperation();
  await expect(promise).rejects.toThrow('Timeout');
}, 10000); // 10 second timeout
```

## Testing Error Handling

### Testing Expected Errors

```typescript
it('should throw error for invalid ID', () => {
  expect(() => service.getWorkItem(-1)).toThrow('Invalid ID');
  expect(() => service.getWorkItem(-1)).toThrow(/Invalid/);
});

it('should return error in result', async () => {
  const result = await handler.execute({ invalidParam: true });
  
  expect(result.success).toBe(false);
  expect(result.errors).toContain('Invalid parameter');
  expect(result.data).toBeNull();
});
```

### Testing Error Recovery

```typescript
it('should retry on transient failure', async () => {
  mockFetch
    .mockRejectedValueOnce(new Error('Network error'))
    .mockResolvedValueOnce({ ok: true, json: async () => 'success' } as Response);

  const result = await service.fetchWithRetry();
  
  expect(result).toBe('success');
  expect(mockFetch).toHaveBeenCalledTimes(2);
});
```

## Snapshot Testing

### When to Use Snapshots

- Complex JSON output that should remain stable
- Formatted text output
- Error message structures

### Creating Snapshots

```typescript
it('should match snapshot', () => {
  const result = formatter.format(data);
  expect(result).toMatchSnapshot();
});
```

### Updating Snapshots

```bash
# Update all snapshots
npm test -- -u

# Update specific snapshot
npm test -- config.test.ts -u
```

## Performance Testing

### Timing Assertions

```typescript
it('should complete within time limit', async () => {
  const start = Date.now();
  await service.performOperation();
  const duration = Date.now() - start;
  
  expect(duration).toBeLessThan(1000); // 1 second max
});
```

### Memory Leak Detection

```typescript
it('should not leak memory', () => {
  const initialMemory = process.memoryUsage().heapUsed;
  
  for (let i = 0; i < 1000; i++) {
    service.createCache();
    service.clearCache();
  }
  
  const finalMemory = process.memoryUsage().heapUsed;
  const increase = finalMemory - initialMemory;
  
  expect(increase).toBeLessThan(10 * 1024 * 1024); // Less than 10MB increase
});
```

## Testing Patterns for MCP Tools

### Testing Tool Handlers

```typescript
describe('handleMyTool', () => {
  let mockServices: Services;
  let mockConfig: ServerConfig;

  beforeEach(() => {
    mockServices = {
      workItemService: {
        getWorkItem: jest.fn()
      }
    } as any;

    mockConfig = {
      organization: 'test-org',
      project: 'test-project',
      defaults: {
        myTool: { defaultValue: 'default' }
      }
    } as any;
  });

  it('should return success result', async () => {
    mockServices.workItemService.getWorkItem.mockResolvedValue({
      id: 123,
      title: 'Test'
    });

    const result = await handleMyTool(
      { workItemId: 123 },
      mockServices,
      mockConfig
    );

    expect(result.success).toBe(true);
    expect(result.data).toBeDefined();
    expect(result.errors).toHaveLength(0);
  });

  it('should apply configuration defaults', async () => {
    mockServices.workItemService.getWorkItem.mockResolvedValue({});

    await handleMyTool({}, mockServices, mockConfig);

    expect(mockServices.workItemService.getWorkItem).toHaveBeenCalledWith(
      expect.objectContaining({ defaultValue: 'default' })
    );
  });

  it('should handle service errors', async () => {
    mockServices.workItemService.getWorkItem.mockRejectedValue(
      new Error('Service failed')
    );

    const result = await handleMyTool(
      { workItemId: 123 },
      mockServices,
      mockConfig
    );

    expect(result.success).toBe(false);
    expect(result.errors).toContain('Service failed');
  });
});
```

## Debugging Tests

### Running Single Test

```bash
npm test -- --testNamePattern="should handle valid input"
```

### Debugging in VS Code

Add to `.vscode/launch.json`:
```json
{
  "type": "node",
  "request": "launch",
  "name": "Jest Current File",
  "program": "${workspaceFolder}/mcp_server/node_modules/.bin/jest",
  "args": [
    "${relativeFile}",
    "--config=${workspaceFolder}/mcp_server/jest.config.js"
  ],
  "console": "integratedTerminal",
  "internalConsoleOptions": "neverOpen"
}
```

### Verbose Output

```bash
npm test -- --verbose
```

## Pre-Commit Coverage Requirements

This project enforces **80%+ code coverage** on all modified files through pre-commit hooks.

### How It Works

1. **Automatic Trigger**: When you run `git commit`, a pre-commit hook automatically runs
2. **Staged File Detection**: Identifies all TypeScript files in `src/` that are staged for commit
3. **Test Execution**: Runs full test suite with coverage analysis using c8
4. **Coverage Check**: Verifies each modified file has ≥80% line coverage
5. **Commit Decision**: 
   - ✅ Allows commit if all files meet threshold
   - ❌ Blocks commit if any file is below 80%

### Coverage Metrics Checked

- **Lines**: Primary metric (must be ≥80%)
- **Branches**: Reported for awareness
- **Functions**: Reported for awareness
- **Statements**: Reported for awareness

### Example Output

```
🚀 Pre-commit coverage check

Staged TypeScript files:
  - src/tools/new-tool.ts

📦 Building project...
🧪 Running tests with coverage...

✅ src/tools/new-tool.ts: Lines: 85.0% | Branches: 80.0% | Functions: 90.0% | Statements: 85.0%

✅ All modified files meet coverage requirements (80%+)
```

### Bypassing Coverage Check (Emergency Only)

**Option 1: Environment Variable**
```bash
SKIP_COVERAGE_CHECK=1 git commit -m "Emergency fix"
```

**Option 2: Git No-Verify Flag**
```bash
git commit --no-verify -m "Emergency fix"
```

**⚠️ Warning:** Only use bypass mechanisms for:
- Emergency production fixes
- Non-code commits (documentation only)
- Work-in-progress commits on feature branches (still requires coverage before merge)

### Improving Coverage

If your commit is blocked:

1. **Review Coverage Report**: Open `coverage/index.html` in browser
2. **Identify Uncovered Lines**: Look for red/yellow highlighting
3. **Add Tests**: Write tests for uncovered code paths
4. **Run Locally**: `npm run test:coverage` to verify
5. **Commit Again**: Re-run `git commit`

### Writing Tests for Coverage

Focus on:
- **Happy paths**: Normal execution flow
- **Error handling**: Exceptions and edge cases
- **Boundary conditions**: Empty inputs, max values, null/undefined
- **Branch coverage**: All if/else and switch branches

**Example:**
```typescript
describe('validateIncidentId', () => {
  it('should accept valid incident ID', () => {
    expect(validateIncidentId(12345)).toBe(true);
  });

  it('should reject negative numbers', () => {
    expect(validateIncidentId(-1)).toBe(false);
  });

  it('should reject zero', () => {
    expect(validateIncidentId(0)).toBe(false);
  });

  it('should reject non-numbers', () => {
    expect(validateIncidentId('abc' as any)).toBe(false);
  });
});
```

### Configuration

**Coverage Tool**: c8 (Istanbul-based coverage for Node.js)

**Scripts** (in `package.json`):
- `npm run test:coverage`: Run tests with coverage report
- `npm run precommit`: Pre-commit hook script (called automatically)

**Coverage Output**:
- `coverage/index.html`: HTML report (detailed view)
- `coverage/coverage-summary.json`: JSON summary (used by pre-commit)
- Terminal: Text summary during test run

## Documentation Requirements

### When Adding/Modifying Tests

**REQUIRED:**
1. Update feature spec in `docs/feature_specs/` if testing new behavior
2. Add comments explaining complex test setup
3. Document any special test environment requirements
4. **Ensure 80%+ coverage** on all new/modified code

**Test Comments:**
```typescript
/**
 * Tests the work item creation flow with parent linking.
 * 
 * This test verifies:
 * 1. Child is created with correct type
 * 2. Parent link is established
 * 3. Parent's child count is updated
 * 
 * Requires: Mock ADO API responses for both work items
 */
it('should create child with parent link', async () => {
  // Test implementation
});
```

### Test Environment Setup

Document in feature spec or README:
- Required environment variables
- Test data requirements
- External dependencies
- Cleanup procedures

---

**Last Updated:** 2026-01-07
