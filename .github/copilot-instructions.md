# GitHub Copilot Instructions for PokePoke

## 🚨 CRITICAL: QUALITY GATE PROTECTION SYSTEM 🚨

**READ THIS FIRST - VIOLATION RESULTS IN IMMEDIATE COMMIT FAILURE**

This repository uses a **multi-layered defense-in-depth protection system** to prevent bypass of quality gates.

### ⛔ ABSOLUTELY FORBIDDEN - NO EXCEPTIONS

**NEVER, under ANY circumstances:**

1. **Modify ANY files in `.githooks/` directory** without explicit human approval
   - All quality gate scripts are protected by CODEOWNERS
   - Pre-commit hooks contain integrity checks that detect tampering
   - Violations are logged and commits are blocked

2. **Add bypass mechanisms to quality scripts:**
   - ❌ NO `SkipCheck` parameters
   - ❌ NO `SKIP_*` environment variables  
   - ❌ NO early exit bypasses (`exit 0 # skip`)
   - ❌ NO file exclusion patterns to hide files from checks
   - ❌ NO lowering coverage thresholds below 80%
   - ❌ NO commenting out quality checks
   - ❌ NO `--no-verify` on git commits

3. **Modify protection system files:**
   - ❌ `.github/CODEOWNERS` - protects quality gate files
   - ❌ `.github/copilot-instructions.md` - this file itself
   - ❌ `.githooks/**` - all quality gate scripts
   - ❌ `azure-pipelines.yml` - CI/CD enforcement

### 🛡️ Protection System Overview

**Location:** All quality gate scripts are in `.githooks/` (intentionally less visible)

**Protected Scripts:**
- `pre-commit.ps1` - Main pre-commit hook with integrity checks
- `verify-integrity.ps1` - Standalone integrity verification
- `check-coverage.ps1` - 80% coverage enforcement (NO BYPASS)
- `check-code-quality.ps1` - Code quality enforcement (NO BYPASS)
- `check-compile-warnings.ps1` - Zero warnings policy (NO BYPASS)
- `check-file-length.ps1` - File length limits (NO BYPASS)
- `check-build.ps1` - Build verification
- `check-mcp-health.ps1` - MCP server health check
- `check-skipped-tests.ps1` - No skipped tests allowed

**How Protection Works:**
1. Every commit runs integrity check FIRST (detects tampering)
2. GitHub CODEOWNERS requires admin approval for `.githooks/` changes
3. Pattern matching detects bypass attempts programmatically
4. Pre-commit hook blocks commits if tampering detected

**Full Documentation:** `.githooks/README.md`

### ✅ What You SHOULD Do Instead

If quality checks fail:
- ✅ **FIX THE CODE** - Write tests, fix quality issues
- ✅ **WRITE TESTS** - Add coverage for untested code
- ✅ **IMPROVE CODE** - Resolve code quality warnings
- ✅ **ASK FOR HELP** - Request clarification from user

**NEVER bypass the checks. Period.**

---

## Project Overview

**Repository:** PokePoke (https://github.com/AmeliaRose802/PokePoke.git)  
**Language:** TypeScript/Node.js  
**Purpose:** Autonomous workflow orchestrator that integrates Beads issue tracker with GitHub Copilot CLI for automated development

## PokePoke - Autonomous Beads + Copilot CLI Orchestrator

This workspace provides **PokePoke**, an autonomous workflow management tool that:

**Core Capabilities:**
- 🤖 Reads pending items from beads database
- 🌳 Creates isolated git worktrees for each task
- 🚀 Invokes GitHub Copilot CLI in programmatic (non-interactive) mode
- ✅ Validates work with configurable quality gates
- 🔄 Retries with corrective feedback until validations pass
- 🧹 Merges completed work and cleans up worktrees
- 🔧 Runs periodic maintenance (integration tests, cleanup, discovery agents)

**Key Features:**
- ⚡ Fully autonomous operation - no human intervention required
- 🔁 Infinite retry loop with intelligent corrective prompts
- 🎯 Priority-based task selection from beads ready queue
- 🔒 Isolated worktree execution prevents conflicts
- 📊 Configurable maintenance cycles and thresholds
- 🪝 GitHub Copilot CLI hooks for validation integration

## Architecture Components

### 1. Main Orchestrator
- Queries `bd ready --json` for available work
- Creates worktrees with pattern: `./worktrees/task-{id}`
- Invokes Copilot CLI with task context and custom instructions
- Monitors completion and validation status

### 2. Validation Engine
- Fast checks: tests, linting, type checking, git status
- Configurable quality gates via hooks
- Generates corrective feedback for retry attempts

### 3. Periodic Maintenance
- Integration test runner
- Code cleanup agent (refactoring, removing duplication)
- Discovery agent (finds issues, creates beads items)

## Requirements

- **🚫 NEVER bypass git quality gates** - Let validations fail and fix the code
- Use beads (`bd`) for ALL task tracking - no markdown TODO lists
- Follow Copilot CLI programmatic mode best practices
- Use `--allow-all-tools` cautiously with appropriate `--deny-tool` restrictions
- Configure maintenance thresholds in `pokepoke.config.json`
- Use worktrees for isolation - NEVER work directly in main repo during autonomous operation 

## 🚫 PowerShell Command Safety

**CRITICAL: FORBIDDEN PARAMETERS**

**NEVER use `-First` or `-Last` parameters** on any PowerShell command or pipeline. These parameters can cause the terminal to hang indefinitely if there is insufficient output.

**❌ FORBIDDEN:**
```powershell
Get-Content file.txt | Select-Object -First 10   # WILL HANG if file has <10 lines
Get-ChildItem | Select-Object -Last 5            # WILL HANG if <5 items
npm test | Select-Object -First 1                # WILL HANG on slow output
```

**✅ SAFE ALTERNATIVES:**

1. **Use array slicing after collection:**
   ```powershell
   $items = Get-Content file.txt
   $items[0..9]  # First 10 items (handles small arrays gracefully)
   ```

2. **Use `-Head` or `-Tail` with Get-Content:**
   ```powershell
   Get-Content file.txt -Head 10    # Safe: reads first 10 lines
   Get-Content file.txt -Tail 5     # Safe: reads last 5 lines
   ```

3. **Use `Where-Object` with index filtering:**
   ```powershell
   Get-ChildItem | Where-Object { $_.PSIndex -lt 10 }
   ```

4. **Collect full output first, then slice:**
   ```powershell
   $results = npm test
   $results[0..4]  # Safe: operates on complete array
   ```

**WHY THIS MATTERS:**
- `-First`/`-Last` use pipeline streaming and wait for enough items
- If insufficient items exist, PowerShell hangs waiting for more
- This creates deadlocks in non-interactive terminal contexts
- Always collect data first, then filter/slice the complete result

---

## 🧪 TESTING

**Note:** Pre-commit hooks automatically run tests on every commit.

### Test Strategy

**Unit Tests:**
- Fast, isolated tests that don't require external services
- Run automatically on every commit via pre-commit hooks
- Must have 80%+ coverage for modified files
- Use `npm test` for quick iteration during development

**Integration Tests:**
- Test interaction between components
- Test Copilot CLI invocation
- Test worktree creation and cleanup
- Test beads database integration
- Run with `npm run test:integration`

### Testing Usage Examples

```powershell
# Run all tests
npm test

# Run tests in watch mode during development
npm test -- --watch

# Run specific test file
npm test -- path/to/test.spec.ts

# Run tests with coverage
npm run test:coverage

# Run integration tests
npm run test:integration
```

### When to Run Integration Tests

**REQUIRED - Run before:**
- ✅ Finishing a work session with significant changes
- ✅ Creating a pull request
- ✅ Completing work on orchestrator or validation logic
- ✅ Modifying Copilot CLI invocation
- ✅ Changing worktree or beads integration

**Optional - Run if:**
- Testing specific external integrations during development
- Debugging issues with Copilot CLI or git operations
- Verifying end-to-end workflows

---

## 🔗 TASK TRACKING WITH BEADS

### Overview

This project uses **[bd (beads)](https://github.com/steveyegge/beads)** for ALL task tracking and issue management. Beads is a git-backed issue tracker designed specifically for AI-supervised coding workflows.

### ✅ REQUIRED: Use bd for All Task Tracking

**NEVER create:**
- Markdown TODO lists
- Task files in `/tasklist`
- External issue trackers
- Duplicate tracking systems

**ALWAYS use:**
- `bd` commands for creating, updating, and tracking work
- `bd ready` to find unblocked work
- `bd create` with `discovered-from` links when discovering new work

### Installation & Setup

If bd is not already initialized:

```bash
# Non-interactive setup (for agents)
bd init --quiet

# Verify installation
bd info --json
```

### Core Workflow for AI Agents

1. **Check for ready work**:
   ```bash
   bd ready --json
   ```

2. **Claim a task**:
   ```bash
   bd update <id> --status in_progress --json
   ```

3. **While working, discover new issues?**:
   ```bash
   # First, check if similar issue already exists to avoid duplicates
   bd list --status open --json
   
   # If not a duplicate, create and link with dependencies
   bd create "Found bug in auth" -t bug -p 1 --deps discovered-from:<current-id> --json
   ```

4. **Update progress**:
   ```bash
   bd update <id> --priority 1 --json
   bd update <id> --status in_progress --json
   ```

5. **Complete work**:
   ```bash
   bd close <id> --reason "Implemented and tested" --json
   ```

6. **Commit early and often**:
   ```bash
   git add <files>
   git commit -m "descriptive message"
   ```

7. **End of session - sync immediately**:
   ```bash
   bd sync
   ```

### 💾 COMMIT FREQUENTLY: Git Best Practices

**CRITICAL:** Commit your work regularly throughout development, not just at the end.

**When to commit:**
- ✅ After completing a logical unit of work (single function, test, or small feature)
- ✅ After fixing a bug or issue
- ✅ After adding tests that pass
- ✅ Before switching to a different task or file
- ✅ After refactoring code
- ✅ When you've made progress worth preserving
- ✅ At natural breakpoints in your work

**When NOT to commit:**
- ❌ Code that doesn't compile/build
- ❌ Code with failing tests (unless explicitly work-in-progress)
- ❌ Incomplete changes that break functionality
- ❌ Large monolithic commits with unrelated changes

**Commit message guidelines:**
- Use conventional commits format: `type(scope): description`
- Types: `feat`, `fix`, `refactor`, `test`, `docs`, `chore`, `style`, `perf`
- Be specific and descriptive
- Reference beads issues when relevant: `Relates to incredible_icm-123`
- Use multi-line messages for complex changes

**Examples of good commit frequency:**
```bash
# Good: Small, focused commits
git commit -m "feat(kusto): add parameter validation to query builder"
git commit -m "test(kusto): add tests for parameter validation"
git commit -m "refactor(kusto): extract query formatting logic"
git commit -m "docs: update query parameter documentation"

# Bad: One huge commit at the end
git commit -m "feat: add entire new feature with tests and docs"
```

**Benefits of frequent commits:**
- 🔄 Easy to revert specific changes
- 📊 Better code review granularity  
- 🔍 Clearer history and blame information
- 💾 Regular backups of your work
- 🎯 Easier to identify when bugs were introduced
- 🤝 Better collaboration and merge conflict resolution

**Pre-commit hooks will run on every commit:**
- Tests are executed automatically
- Coverage is checked for modified files
- Only commits meeting quality standards will succeed
- This ensures code quality with each small commit

**🚨 CRITICAL: NEVER USE `--no-verify`**
- **ABSOLUTELY FORBIDDEN:** Using `git commit --no-verify` or `git commit -n`
- Pre-commit hooks exist to catch bugs and maintain quality
- Bypassing hooks defeats the entire purpose of the safeguards
- If pre-commit fails, FIX THE ISSUE, don't bypass the check
- **Integrity checks detect tampering** - commits will fail if scripts modified
- Any agent that uses `--no-verify` is violating project requirements

**🚨 CRITICAL: NEVER MODIFY QUALITY GATE SCRIPTS IN `.githooks/`**
- **ABSOLUTELY FORBIDDEN:** Modifying ANY files in `.githooks/` directory
- **LOCATION CHANGE:** All quality scripts moved from `scripts/` to `.githooks/` for protection
- **ABSOLUTELY FORBIDDEN:** Adding files to exclusion lists, ignore patterns, or skip conditions
- **ABSOLUTELY FORBIDDEN:** Lowering coverage thresholds, warning limits, or quality gates
- **ABSOLUTELY FORBIDDEN:** Adding bypass parameters (`SkipCheck`, `SKIP_*` env vars)
- **ABSOLUTELY FORBIDDEN:** Commenting out or disabling quality checks
- **PROTECTION:** `.githooks/` protected by CODEOWNERS - requires @ameliapayne approval
- **DETECTION:** Pre-commit hook runs integrity check that detects tampering
- Coverage and quality requirements exist to maintain code health
- If coverage fails, WRITE TESTS for the code, don't exclude the files
- If quality checks fail, FIX THE CODE QUALITY issues, don't lower the bar
- Any modification to bypass quality gates triggers commit failure
- The ONLY acceptable changes are bug fixes that maintain or improve rigor (requires admin approval)

### Issue Types & Priorities

**Types:**
- `bug` - Something broken
- `feature` - New functionality
- `task` - Work item (tests, docs, refactoring)
- `epic` - Large feature with subtasks
- `chore` - Maintenance work

**Priorities:**
- `0` - Critical (security, data loss, broken builds)
- `1` - High (major features, important bugs)
- `2` - Medium (default, nice-to-have)
- `3` - Low (polish, optimization)
- `4` - Backlog (future ideas)

### Dependency Types

- `blocks` - Hard blocker (affects ready work detection)
- `related` - Soft relationship
- `parent-child` - Hierarchical relationship
- `discovered-from` - Track issues discovered during work

### Labels for Code Area Tracking

**Use labels to identify what code areas an issue touches:**

Common labels:
- `orchestrator` - Main workflow orchestrator logic
- `copilot-cli` - Copilot CLI invocation and integration
- `validation` - Validation engine and quality gates
- `worktrees` - Git worktree management
- `beads-integration` - Beads database integration
- `maintenance` - Periodic maintenance agents
- `config` - Configuration and settings
- `tests` - Test infrastructure
- `docs` - Documentation changes

**ALWAYS add labels when creating issues:**
```bash
# Create issue with labels indicating code areas
bd create "Refactor orchestrator loop" -t task -p 1 --json
bd label add incredible_icm-123 orchestrator validation --json
```

**Check labels before claiming work to avoid conflicts:**
```bash
# See all work in a code area
bd list --label orchestrator --status in_progress --json

# If others are working on the same label, choose different work
```

### Best Practices for Creating Issues

**ALWAYS check for duplicates before creating new issues:**
```bash
# Search existing issues first
bd list --status open --json
bd list --label <relevant-label> --json
```

**ALWAYS create issues with appropriate dependencies and labels:**
- Use `--deps discovered-from:<id>` when finding issues during work
- Use `--deps blocks:<id>` when new issue blocks existing work
- Use `--deps related:<id>` when issues are related but not blocking
- Use `--deps parent:<id>` for subtasks of larger features
- **Add labels** to indicate what code areas the issue touches

**Examples:**
```bash
# Discovered issue while working on incredible_icm-42
bd create "Fix validation error" -t bug -p 1 --deps discovered-from:incredible_icm-42 --json
bd label add incredible_icm-123 validation --json

# New issue blocks existing work
bd create "Add missing config" -t task -p 0 --deps blocks:incredible_icm-15 --json
bd label add incredible_icm-124 config --json

# Subtask of larger feature
bd create "Add unit tests" -t task -p 1 --deps parent:incredible_icm-10 --json
bd label add incredible_icm-125 tests --json
```

### Common Commands

```bash
# Find ready work
bd ready --json

# Create issue
bd create "Issue title" -t bug -p 1 -d "Description" --json

# Create with dependencies
bd create "Fix auth bug" -p 1 --deps discovered-from:bd-42 --json

# Add labels
bd label add bd-42 security backend --json

# Show issue details
bd show bd-42 --json

# View dependency tree
bd dep tree bd-42

# List issues
bd list --status open --priority 1 --json
bd list --label backend,security --json

# Statistics
bd stats --json

# Force immediate sync
bd sync
```

### Auto-Sync Behavior

Beads automatically syncs with git:
- **Exports** to `.beads/issues.jsonl` after changes (30s debounce for batching)
- **Imports** from JSONL after `git pull`
- **Manual sync** with `bd sync` forces immediate flush/commit/push

**IMPORTANT:** Always run `bd sync` at the end of your session to ensure changes are committed.

### 🔀 Git Worktrees Support

**This project is configured for full git worktree support with shared beads database.**

#### Configuration

- **Sync Branch:** `beads-sync` (configured in `.beads/config.yaml`)
- **Shared Database:** All worktrees share `.beads/` in main repository
- **Daemon Mode:** Enabled across all worktrees
- **Auto-Sync:** Changes committed to `beads-sync` branch automatically

#### How Worktrees Work with Beads

**Database Architecture:**
```
Main Repository
├── .git/                    # Shared git directory
├── .beads/                  # Shared database (main repo)
│   ├── beads.db            # SQLite database
│   ├── issues.jsonl        # Issue data (git-tracked)
│   └── config.yaml         # Worktree configuration
├── feature-branch/         # Worktree 1
│   └── (code files only)
└── bugfix-branch/          # Worktree 2
    └── (code files only)
```

**Key Benefits:**
- ✅ One database - All worktrees share same `.beads` directory
- ✅ Daemon mode works - Commits to `beads-sync` branch safely
- ✅ Concurrent access - SQLite locking prevents corruption
- ✅ No branch conflicts - Sync branch isolated from work branches

#### Creating Worktrees for Parallel Work

**When user indicates multiple agents are working in parallel:**

1. **Create a unique agent name**:
   ```bash
   export AGENT_NAME="agent_alpha"  # Choose something unique
   ```

2. **Set up isolated worktree**:
   ```bash
   git worktree add ../PokePoke-$AGENT_NAME -b $AGENT_NAME/work
   cd ../PokePoke-$AGENT_NAME
   ```

3. **Verify beads access (automatic)**:
   ```bash
   # Database is automatically discovered from main repo
   bd list --json  # Should work immediately
   ```

4. **Before claiming work, check for label conflicts**:
   ```bash
   # See what code areas are actively being worked on
   bd list --status in_progress --json
   bd list --label orchestrator --status in_progress --json
   
   # AVOID claiming work with same labels as other agents
   # Choose work in different code areas to prevent merge conflicts
   ```

5. **Claim work and assign yourself**:
   ```bash
   bd ready --json
   bd show <id> --json  # Verify unassigned or assigned to you
   bd update <id> --assign $AGENT_NAME --status in_progress --json
   
   # Ensure labels are present
   bd label add <id> <relevant-labels> --json
   ```

6. **Work isolation rules**:
   - ✅ Only work on items assigned to you or unassigned
   - ✅ Check labels before claiming to avoid conflicts
   - ✅ Commit frequently and sync beads after updates
   - ✅ All beads commands work normally in worktrees
   - ❌ NEVER work on items assigned to other agents
   - ❌ NEVER claim items with same labels as other agents' active work
   - ❌ NEVER work in main repo when parallel work is active

7. **Cleanup after work**:
   ```bash
   cd ../PokePoke
   git worktree remove ../PokePoke-$AGENT_NAME
   git branch -d $AGENT_NAME/work
   ```

#### Beads-Created Worktrees (Sync Branch)

**Note:** Beads automatically creates its own worktrees in `.git/beads-worktrees/` for the sync branch feature. This is normal and expected.

**Location:**
```
.git/
├── beads-worktrees/          # Beads-created worktrees live here
│   └── beads-sync/           # Sync branch worktree
│       └── .beads/
│           └── issues.jsonl  # Issue data committed here
└── worktrees/                # User-created worktrees directory
```

**If you see "branch already checked out" errors:**
```bash
# Remove beads worktrees if needed
rm -rf .git/beads-worktrees
git worktree prune

# Now you can checkout the branch
git checkout main
```

#### Troubleshooting

**Database not found in worktree:**
```bash
# Ensure main repo has .beads directory
cd c:\Users\ameliapayne\PokePoke
ls -la .beads/

# Re-run bd init if needed (should not be necessary)
bd init --branch beads-sync --quiet
```

**Daemon commits to wrong branch:**
- Should not occur with sync branch configured
- Daemon automatically commits to `beads-sync` branch
- Your work branches remain untouched

**Reference:** See [WORKTREES.md](https://github.com/steveyegge/beads/blob/main/docs/WORKTREES.md) for complete documentation.

### Integration with Feature Development

When adding a new feature:
1. **Create a bd issue** for the feature: `bd create "Add feature X" -t feature -p 1 --json`
2. **Create feature spec**: `docs/feature_specs/<feature-name>.md`
3. **Commit the spec**: `git add docs/feature_specs/<feature-name>.md && git commit -m "docs: add spec for feature X"`
4. **Implement in small increments** with commits after each logical unit
5. **Link discovered work**: Use `--deps discovered-from:<feature-id>` for related tasks
6. **Update feature spec** when modifying existing features and commit changes
7. **Close issue** when complete: `bd close <id> --reason "Feature implemented and documented" --json`
8. **Final sync**: `bd sync` to push beads updates

**Example feature implementation flow:**
```bash
# 1. Create issue and spec
bd create "Add query caching" -t feature -p 1
# Create spec file
git commit -m "docs: add query caching feature spec"

# 2. Implement incrementally with frequent commits
git commit -m "feat(cache): add LRU cache infrastructure"
git commit -m "feat(cache): integrate cache with query service"
git commit -m "test(cache): add cache hit/miss tests"
git commit -m "feat(cache): add cache invalidation logic"
git commit -m "test(cache): add invalidation tests"
git commit -m "docs: update feature spec with cache behavior"

# 3. Close issue and sync
bd close incredible_icm-XXX --reason "Query caching implemented with tests"
bd sync
```

---

## � FEATURE SPECIFICATION REQUIREMENTS

### When Adding a New Feature

**REQUIRED:** Create a feature specification at `docs/feature_specs/<feature-name>.md`

The feature spec MUST include:
- **Overview** - What the feature does and why it exists
- **Input Parameters** - All parameters with types, defaults, and examples
- **Output Format** - Success and error response structures
- **Examples** - Working examples with actual input/output
- **Error Handling** - Common errors and resolutions
- **Implementation Details** - Key components and integration points
- **Testing** - Test coverage and manual testing steps

**Also REQUIRED:** Update `docs/feature_specs/toc.yml` with new entry

### When Modifying an Existing Feature

**REQUIRED:** Update the corresponding feature spec in `docs/feature_specs/`

Changes to document:
- Updated input/output formats
- New parameters or configuration options
- Changed behavior
- New error conditions
- Version increment in changelog

### Feature Spec Naming Convention

- Use kebab-case: `feature-name.md`
- Be descriptive: `query-handle-pattern.md` not `qh.md`
- Match tool name if applicable: `create-work-item.md` for `create-work-item` tool

---

## �🚫 CRITICAL: NO SUMMARY DOCS POLICY

### ❌ ABSOLUTELY FORBIDDEN TO CREATE UNLESS USER SPECIFICALLY ASKS:
- **ANY** summary files (e.g., `*_SUMMARY.md`, `*_COMPLETE.md`, `*_REPORT.md`, `*_ANALYSIS.md`)
- Implementation status documents or "completion reports"
- Changelog files outside of git commit messages
- Redundant "guide" files that duplicate existing documentation
- Verbose architecture documents that should be code comments
- **Analysis reports** or comprehensive documentation of work done
- "Beta test response" documents or improvement plans as files
- **Markdown TODO lists** (use `bd` for task tracking)

### ✅ EXCEPTION: USER EXPLICITLY REQUESTS DOCUMENTATION
- **If user specifically asks** for a summary, report, or analysis document, you may create it
- **Still prefer** updating existing documentation when possible
- **Ask for clarification** if the request is ambiguous

### ⚠️ IF USER ASKS FOR DOCUMENTATION WITHOUT BEING SPECIFIC:
1. **ASK** what specific documentation they need and where it should go
2. **SUGGEST** updating existing docs instead of creating new ones
3. **OFFER** to put details in git commit messages or bd issues
4. **ONLY CREATE** new docs if they explicitly confirm that's what they want

### ✅ ONLY ACCEPTABLE DOCUMENTATION:
- Updating existing `/docs` files with essential user info
- Code comments for implementation details
- Git commit messages for change history
- **bd issues** for task tracking and work discovery

### Project Structure:
- `/docs` - User-facing documentation only (update existing files)
- `/internal_resources` - Query templates (.kql), workflows, and resource files (not documentation)
- `/src` - C# source code with inline comments
- `/tests` - Unit and integration tests
- `.beads/` - Beads issue tracker database (auto-managed by bd)
- Code should be self-documenting with clear naming

### When Asked to Document Implementation/Analysis:
1. **SAY NO** to creating summary files
2. Explain the policy against summary documentation
3. Offer to:
   - Update existing functional documentation
   - Create bd issues for tracking work
   - Add code comments for implementation details
   - Write comprehensive git commit messages
4. Keep any updates focused on HOW to use, not WHAT was implemented
