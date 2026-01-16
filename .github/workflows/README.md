# GitHub Actions Workflows

This directory contains CI/CD workflows for the ICM MCP Server project.

## Workflows

### 🏗️ build.yml - Main CI Pipeline

**Triggers:**
- Push to `main`, `master`, or `develop` branches
- Pull requests to `main`, `master`, or `develop` branches
- Manual workflow dispatch

**What it does:**
1. Checks out code
2. Sets up .NET 8
3. Restores dependencies
4. Builds solution in Release configuration
5. Runs unit tests (excludes integration/live tests)
6. Generates code coverage reports using ReportGenerator
7. **Enforces 80% minimum coverage threshold** (fails if below)
8. Uploads coverage artifacts
9. Comments coverage report on PRs

**Coverage Enforcement:**
- Line coverage must be ≥80%
- Branch coverage is reported but not enforced
- Uses OpenCover format for detailed coverage
- Generates HTML, Cobertura, and text summary reports

**Test Filters:**
```bash
--filter "Category!=Integration&Category!=Live"
```

### 🧪 test.yml - Extended Test Suite

**Triggers:**
- Manual workflow dispatch
- Scheduled: Nightly at 2 AM UTC

**What it does:**
- Runs unit tests separately from integration tests
- Uses matrix strategy for parallel execution
- Integration tests continue on error (may require credentials)
- Publishes test report across all test categories
- Uploads test results as artifacts

**Test Categories:**
- **Unit**: Fast, isolated tests (default)
- **Integration**: Tests requiring live Kusto/Azure (may fail without credentials)

### ✅ pre-commit.yml - Pre-commit Checks

**Triggers:**
- Pull requests to `main`, `master`, or `develop` branches
- Manual workflow dispatch

**What it does:**
1. **Formatting check**: Runs `dotnet format --verify-no-changes`
   - Comments on PR if formatting issues found
2. **File length check**: Enforces 500-line limit per file
   - Fails if any .cs file exceeds 500 lines
3. **Quick tests**: Runs unit tests in Debug mode
   - Uses minimal verbosity for fast feedback
4. **Failure notification**: Comments on PR if checks fail

**File Length Policy:**
- Maximum: 500 lines per .cs file
- Excludes: `*.Designer.cs`, `*.g.cs` (generated files)
- Violations block PR merge

### 📦 publish.yml - Release Publishing

**Triggers:**
- GitHub release published
- Manual workflow dispatch (with version input)

**What it does:**
1. Determines version from release tag or input
2. Builds solution with version metadata
3. Runs full test suite
4. Publishes application for linux-x64
5. Creates release archives (.tar.gz)
6. Uploads artifacts to release
7. Creates deployment package with README and version info

**Artifacts:**
- `IcmMcpServer-v{version}-linux-x64.tar.gz` - Main application bundle
- `deployment-package.tar.gz` - Deployment-ready package with metadata

## Test Categories

Tests are filtered using xUnit traits:

```csharp
[Trait("Category", "Integration")]  // Excluded from CI, run in test.yml
[Trait("Category", "Live")]         // Excluded from CI, run in test.yml
// No trait = Unit test (runs in CI)
```

## Coverage Requirements

- **Minimum line coverage**: 80%
- **Reported metrics**: Line coverage, branch coverage
- **Format**: OpenCover XML
- **Tools**: 
  - XPlat Code Coverage (collector)
  - ReportGenerator (report generation)
  - Cobertura Action (PR comments)

## Local Development

### Run tests like CI:
```bash
# Unit tests with coverage
dotnet test --filter "Category!=Integration&Category!=Live" --collect:"XPlat Code Coverage"

# Check formatting
dotnet format --verify-no-changes

# Check file lengths
pwsh scripts/check-file-length.ps1
```

### Generate coverage report:
```bash
dotnet test --collect:"XPlat Code Coverage" -- DataCollectionRunSettings.DataCollectors.DataCollector.Configuration.Format=opencover
dotnet tool install -g dotnet-reportgenerator-globaltool
reportgenerator -reports:TestResults/**/coverage.opencover.xml -targetdir:CoverageReport -reporttypes:"Html;TextSummary"
```

## Secrets Required

No secrets are required for basic CI. Integration tests may require:
- `AZURE_TENANT_ID` (optional, for live Kusto tests)
- `AZURE_CLIENT_ID` (optional, for live Kusto tests)
- `AZURE_CLIENT_SECRET` (optional, for live Kusto tests)

## Workflow Status

Add badges to README.md:

```markdown
[![Build](https://github.com/YOUR_ORG/incredible-icm/actions/workflows/build.yml/badge.svg)](https://github.com/YOUR_ORG/incredible-icm/actions/workflows/build.yml)
[![Tests](https://github.com/YOUR_ORG/incredible-icm/actions/workflows/test.yml/badge.svg)](https://github.com/YOUR_ORG/incredible-icm/actions/workflows/test.yml)
```
