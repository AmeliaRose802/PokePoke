# Quality Gate Protection System

## Overview

This repository uses a **multi-layered defense-in-depth approach** to prevent AI agents (or anyone) from bypassing code quality checks.

## Protection Layers

### Layer 1: CODEOWNERS File Protection
- **File:** `.github/CODEOWNERS`
- **What it does:** Requires @ameliapayne approval for any changes to:
  - All files in `.githooks/` (quality gate scripts)
  - `.github/CODEOWNERS` itself
  - `.github/copilot-instructions.md`
  - `azure-pipelines.yml` (CI/CD pipeline)

**Effect:** No one can modify quality gates without admin review on GitHub.

### Layer 2: Pre-commit Integrity Check
- **File:** `.githooks/pre-commit.ps1`
- **What it does:** Before running quality checks, scans all quality gate scripts for tampering:
  - Detects bypass parameters (`SkipCheck`, `SKIP_*` environment variables)
  - Detects early exit bypasses
  - Detects file exclusion patterns
  - Detects lowered coverage thresholds

**Effect:** Even if scripts are modified locally, commits will fail with security warnings.

### Layer 3: Standalone Verification Script
- **File:** `.githooks/verify-integrity.ps1`
- **What it does:** Can be run independently to verify script integrity
- **Usage:** `.\.githooks\verify-integrity.ps1`

**Effect:** Allows manual verification and can be used in CI/CD pipelines.

### Layer 4: Scripts Hidden in `.githooks/`
- **Location:** All quality gate scripts moved from `scripts/` to `.githooks/`
- **Why:** Agents are less likely to search in `.githooks/` compared to `scripts/`
- **Protected scripts:**
  - `check-build.ps1`
  - `check-code-quality.ps1`
  - `check-compile-warnings.ps1`
  - `check-coverage.ps1`
  - `check-file-length.ps1`
  - `check-mcp-health.ps1`
  - `check-skipped-tests.ps1`
  - `pre-commit.ps1`
  - `run-tests.ps1`

### Layer 5: No Bypass Parameters
- **All bypass mechanisms removed:** No `SkipCheck` parameters, no `SKIP_*` environment variables
- **Effect:** Scripts cannot be skipped or bypassed under any circumstances

### Layer 6: Copilot Instructions Enhancement
- **File:** `.github/copilot-instructions.md`
- **Contains:** Explicit warnings that modifying quality scripts is ABSOLUTELY FORBIDDEN
- **Protected by:** CODEOWNERS (requires admin approval to modify instructions)

### Layer 7: Azure Pipeline Enforcement (Future)
- **File:** `azure-pipelines.yml`
- **What it will do:** Run identical checks in CI/CD
- **Effect:** Even if local checks are bypassed, CI/CD will catch violations

## Forbidden Patterns Detected

The integrity checker detects these tampering attempts:

### Bypass Parameters
```powershell
param([switch]$SkipCheck)
$env:SKIP_COVERAGE_CHECK
if ($SkipCheck) { exit 0 }
```

### Coverage Threshold Manipulation
```powershell
[int]$MinCoverage = 50  # Below 80
$MinCoverage = 70
```

### File Exclusion Patterns
```powershell
Where-Object { $_ -notmatch 'MyFile.cs' }  # EXCLUDE
$excludePattern = "SomePattern"
```

### Early Exit Bypasses
```powershell
exit 0  # skip check
return $true  # bypass
if ($SKIP_MODE) { exit 0 }
```

## How Protection Works

### Scenario 1: Agent tries to modify scripts directly
1. Agent edits `.githooks/check-coverage.ps1` to add bypass
2. Agent attempts `git commit`
3. **Pre-commit hook detects tampering** → Commit blocked with security warning
4. Agent cannot proceed

### Scenario 2: Agent tries to commit with `--no-verify`
1. Agent attempts `git commit --no-verify`
2. This bypasses local pre-commit hooks
3. **Push to GitHub triggers CODEOWNERS** → PR cannot merge without admin approval
4. Admin sees the attempted bypass and rejects

### Scenario 3: Agent tries to modify CODEOWNERS
1. Agent edits `.github/CODEOWNERS` to remove protections
2. **CODEOWNERS protects itself** → PR cannot merge without admin approval
3. Admin sees the attempted removal and rejects

### Scenario 4: Agent tries to modify copilot-instructions.md
1. Agent edits instructions to remove warnings
2. **CODEOWNERS protects instructions** → PR cannot merge without admin approval
3. Admin sees the attempted modification and rejects

## Verification Commands

```powershell
# Verify integrity of all quality scripts
.\.githooks\verify-integrity.ps1

# Run pre-commit checks manually
.\.githooks\pre-commit.ps1

# Test specific quality check
.\.githooks\check-coverage.ps1
.\.githooks\check-code-quality.ps1
```

## Restoration Commands

If scripts are tampered with:

```powershell
# Restore all quality gate scripts from main branch
git checkout origin/main .githooks/

# Restore specific script
git checkout origin/main .githooks/check-coverage.ps1

# Verify restoration
.\.githooks\verify-integrity.ps1
```

## For Repository Administrators

### Setting Up Branch Protection (Recommended)

1. Go to GitHub repository Settings → Branches
2. Add branch protection rule for `main`:
   - ✅ Require pull request reviews before merging
   - ✅ Require review from Code Owners
   - ✅ Require status checks to pass before merging
   - ✅ Require conversation resolution before merging
   - ✅ Include administrators (prevents admin bypass)

### Monitoring Tampering Attempts

Watch for PRs that modify:
- `.githooks/**`
- `.github/CODEOWNERS`
- `.github/copilot-instructions.md`
- `azure-pipelines.yml`

These should be **rare** and require careful scrutiny.

## Why This Approach Works

1. **Multiple Independent Checks:** Defeating all layers requires coordinated bypass
2. **Self-Protection:** The protection system protects itself (CODEOWNERS protects CODEOWNERS)
3. **Visibility:** All protection files are tracked in git with full history
4. **GitHub Integration:** CODEOWNERS leverages GitHub's access control
5. **Obscurity as Defense:** Scripts in `.githooks/` are less visible to agents
6. **Programmatic Detection:** Integrity checker catches common bypass patterns
7. **No Legitimate Bypass:** No environment variables or parameters to skip checks

## Limitations & Considerations

### What This Protects Against
✅ Agent modifications to quality scripts  
✅ Adding bypass parameters  
✅ Lowering coverage thresholds  
✅ Adding file exclusions  
✅ Removing quality checks  
✅ Modifying protection instructions  

### What This Does NOT Protect Against
❌ Admin deliberately bypassing all checks (admin has that right)  
❌ Force pushing to protected branch (requires branch protection rules)  
❌ Sophisticated agents that understand the entire protection system  
❌ Committing low-quality code that passes all checks  

### Future Enhancements

1. **CI/CD Integration:** Add integrity check to Azure Pipelines
2. **Hash Verification:** Store cryptographic hashes of scripts
3. **Mandatory Status Checks:** Require CI/CD pipeline success on GitHub
4. **Alert System:** Notify admin when protection files are modified
5. **Audit Log:** Log all quality check executions and failures

## Conclusion

This defense-in-depth approach makes it **extremely difficult** for agents to bypass quality gates without detection. The combination of GitHub CODEOWNERS, programmatic integrity checks, script obscurity, and comprehensive monitoring creates multiple barriers that must all be defeated simultaneously.

**Key principle:** Make it harder to bypass checks than to write good code.
