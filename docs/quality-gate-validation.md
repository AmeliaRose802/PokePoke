# Quality Gate Validation Loop

Visual diagrams of PokePoke's quality gate pipeline — how agent work is verified and retried with corrective feedback.

## Overview

PokePoke has **two layers** of quality enforcement:
1. **Pre-commit hooks** (`.githooks/`) — automated syntax, type, coverage, lint checks that run on every `git commit`
2. **Gate agent** — AI-powered logic verification that checks whether changes actually satisfy the work item requirements

The gate agent runs *after* pre-commit passes. Pre-commit ensures code compiles and tests pass; the gate agent ensures the code is *correct and complete*.

## General Gate Validation Flow

**Color key:**
- Default = normal execution
- 🟩 Green = success terminal
- 🟥 Red = failure terminal
- 🟨 Yellow = feedback injection (retry path)

### Happy path + rejection loop

The main flow from work agent completion through gate verification to merge. Timeout/crash handling is broken out separately below.

```mermaid
flowchart TD
    START(["0. Work agent completes"]) --> CLEANUP["1. Cleanup phase<br/>run_cleanup_with_timeout()"]
    CLEANUP -- Fail --> FAIL_CLEANUP(["FAIL — cleanup failed"])
    CLEANUP -- Success --> GATE_ENABLED{"2. Gate agent<br/>enabled?"}

    GATE_ENABLED -- No --> SUCCESS_NOGATE(["SUCCESS — skip gate<br/>proceed to merge"])
    GATE_ENABLED -- Yes --> HANDOFF["3. Build handoff context<br/>list changed files + diff"]
    HANDOFF --> GATE["4. Invoke gate agent"]
    GATE --> RESULT{"5. Result?"}

    RESULT -- Success --> PASS(["SUCCESS — gate approved<br/>proceed to merge"])
    RESULT -- "Timeout / Crash" --> ERRORFLOW(["See error handling below"])
    RESULT -- Rejection --> INCREMENT["6a. Increment<br/>gate_rejection_count"]

    INCREMENT --> MAXED{"6b. Rejections<br/>≥ max? (default 3)"}
    MAXED -- Yes --> DEFER["6c. Defer item to queue"]
    DEFER --> DECOMPOSE["6d. Maybe decompose<br/>into subtasks"]
    DECOMPOSE --> FAIL_MAXED(["FAIL — max rejections"])

    MAXED -- No --> FEEDBACK["7. Build corrective feedback<br/>keep last 3 rejection reasons"]
    FEEDBACK --> REPROMPT["8. New work agent invocation<br/>with {{retry_feedback}}"]
    REPROMPT --> CLEANUP

    style PASS fill:#27ae60,stroke:#333,color:#fff
    style SUCCESS_NOGATE fill:#27ae60,stroke:#333,color:#fff
    style FAIL_CLEANUP fill:#e74c3c,stroke:#333,color:#fff
    style FAIL_MAXED fill:#e74c3c,stroke:#333,color:#fff
    style FEEDBACK fill:#f1c40f,stroke:#333,color:#333
    style REPROMPT fill:#f1c40f,stroke:#333,color:#333
```

### Gate agent error handling (timeout & crash)

When the gate agent times out or crashes, it retries up to 3 times before giving up. Timeouts resume the session; crashes start fresh.

```mermaid
flowchart TD
    GATE["5a. Invoke gate agent"] --> RESULT{"5b. Result?"}

    RESULT -- Timeout --> T_CHECK{"5c. Timeout<br/>attempts < 3?"}
    T_CHECK -- Yes --> T_RESUME["5d. Resume same session<br/>gate_timeout_attempts++"]
    T_RESUME --> GATE
    T_CHECK -- No --> T_FAIL(["5e. FAIL — timed out 3x"])

    RESULT -- Crashed --> C_CHECK{"5f. Crash<br/>attempts < 3?"}
    C_CHECK -- Yes --> C_RETRY["5g. Clear session, restart<br/>gate_crash_attempts++"]
    C_RETRY --> GATE
    C_CHECK -- No --> C_FAIL(["5h. FAIL — crashed 3x"])

    RESULT -- "Success / Rejection" --> MAIN(["Back to main flow"])

    style T_FAIL fill:#e74c3c,stroke:#333,color:#fff
    style C_FAIL fill:#e74c3c,stroke:#333,color:#fff
    style MAIN fill:#4a90d9,stroke:#333,color:#fff
```

Steps 7–8 (yellow) are the retry feedback loop — the gate rejection reason is injected into the work agent's next prompt so it can address the specific issues.

## Pre-Commit Hook Pipeline

The automated checks that run on every `git commit` inside a worktree. These are enforced by `.githooks/pre-commit.ps1` and **cannot be bypassed**.

```mermaid
flowchart TD
    COMMIT(["git commit"]) --> INTEGRITY["1. Integrity check<br/>verify quality scripts<br/>not tampered"]

    INTEGRITY -- Tampered --> BLOCK_TAMPER(["BLOCKED — integrity<br/>violation detected"])
    INTEGRITY -- OK --> RUFF["2. Ruff lint<br/>syntax + style"]

    RUFF -- Fail --> BLOCK_LINT(["BLOCKED — lint errors<br/>fix and retry commit"])
    RUFF -- Pass --> MYPY["3. Code quality (mypy)<br/>type checking"]

    MYPY -- Fail --> BLOCK_TYPES(["BLOCKED — type errors<br/>fix and retry commit"])
    MYPY -- Pass --> COVERAGE["4. Test coverage<br/>check-coverage.py<br/>80% threshold on modified files"]

    COVERAGE -- Fail --> BLOCK_COV(["BLOCKED — coverage below 80%<br/>write tests"])
    COVERAGE -- Pass --> SKIPPED["5. Skipped tests check<br/>no @pytest.mark.skip allowed"]

    SKIPPED -- Fail --> BLOCK_SKIP(["BLOCKED — skipped tests<br/>found"])
    SKIPPED -- Pass --> DESKTOP{"6. Desktop files<br/>changed?"}

    DESKTOP -- Yes --> DBUILD["6a. Desktop build<br/>TypeScript compilation"]
    DESKTOP -- No --> LENGTH
    DBUILD -- Fail --> BLOCK_BUILD(["BLOCKED — desktop<br/>build failed"])
    DBUILD -- Pass --> ESLINT["6b. Desktop ESLint"]
    ESLINT -- Fail --> BLOCK_ESLINT(["BLOCKED — ESLint errors"])
    ESLINT -- Pass --> LENGTH

    LENGTH["7. File length check"] -- Fail --> BLOCK_LEN(["BLOCKED — file too long"])
    LENGTH -- Pass --> IMPORT["8. Pokepoke import check<br/>verify module boots"]

    IMPORT -- Fail --> BLOCK_IMPORT(["BLOCKED — import failed"])
    IMPORT -- Pass --> COMMIT_OK(["COMMIT ALLOWED"])

    %% Fast-fail: sequential chain, first failure blocks
    style BLOCK_TAMPER fill:#e74c3c,stroke:#333,color:#fff
    style BLOCK_LINT fill:#e74c3c,stroke:#333,color:#fff
    style BLOCK_TYPES fill:#e74c3c,stroke:#333,color:#fff
    style BLOCK_COV fill:#e74c3c,stroke:#333,color:#fff
    style BLOCK_SKIP fill:#e74c3c,stroke:#333,color:#fff
    style BLOCK_BUILD fill:#e74c3c,stroke:#333,color:#fff
    style BLOCK_ESLINT fill:#e74c3c,stroke:#333,color:#fff
    style BLOCK_LEN fill:#e74c3c,stroke:#333,color:#fff
    style BLOCK_IMPORT fill:#e74c3c,stroke:#333,color:#fff
    style COMMIT_OK fill:#27ae60,stroke:#333,color:#fff
```

This is a **fast-fail chain** — the first check that fails blocks the commit; remaining checks are skipped.

## Gate Agent Rejection Feedback Loop

Detail of how corrective feedback flows from gate rejection back to the work agent.

```mermaid
flowchart TD
    REJECT(["FB-0. Gate agent rejects work"]) --> PARSE["FB-1. Parse GateAgentResult<br/>extract reason + details"]

    PARSE --> RECORD["FB-2. Record rejection<br/>increment_gate_rejection_count()<br/>beads_metadata.py"]

    RECORD --> COMMENT["FB-3. Add beads comment<br/>Gate Agent Rejection N/max:<br/>rejection reason"]

    COMMENT --> STATS["FB-4. Record gate check stats<br/>record_gate_check(model, item_id,<br/>success=False, reason)"]

    STATS --> ACCUMULATE["FB-5. Append to feedback buffer<br/>accumulated_feedback.append(reason)<br/>keep last 3 entries only"]

    ACCUMULATE --> TEMPLATE["FB-6. Inject into prompt template<br/>{{retry_feedback}} section in<br/>beads-item.md"]

    TEMPLATE --> INVOKE["FB-7. New work agent invocation<br/>fresh Copilot session<br/>new agent_id + iteration suffix"]

    INVOKE --> AGENT["FB-8. Work agent sees prompt:<br/>⚠️ PREVIOUS ATTEMPT FEEDBACK<br/>Address all of these issues..."]

    AGENT --> WORK["FB-9. Agent works on fix<br/>addresses feedback items"]

    WORK --> COMMIT_GATE["FB-10. Agent commits<br/>pre-commit hooks run again"]

    COMMIT_GATE --> NEXT(["Back to step 4<br/>gate re-verification"])

    style REJECT fill:#e74c3c,stroke:#333,color:#fff
    style ACCUMULATE fill:#f1c40f,stroke:#333,color:#333
    style TEMPLATE fill:#f1c40f,stroke:#333,color:#333
    style NEXT fill:#4a90d9,stroke:#333,color:#fff
```

## Work Agent Fail-Fast Outcomes

## Item Decomposition (Step 6d)

When an item exceeds its max gate rejections, PokePoke can invoke an AI agent to break it into smaller, independently completable subtasks.

```mermaid
flowchart TD
    START(["6d-0. Item exceeds max<br/>gate rejections"]) --> CHECK{"6d-1. Decomposition<br/>enabled?"}

    CHECK -- No --> SKIP(["Skip — item stays deferred"])
    CHECK -- Yes --> THRESHOLD{"6d-2. Total failures<br/>≥ threshold? (default 3)"}

    THRESHOLD -- No --> SKIP
    THRESHOLD -- Yes --> DEPTH{"6d-3. Decomposition<br/>depth < max? (default 3)"}

    DEPTH -- "Already decomposed 3x" --> SKIP
    DEPTH -- OK --> INVOKE["6d-4. Invoke decomposition agent<br/>AI reads item + codebase +<br/>failure history"]

    INVOKE -- Fail --> SKIP_FAIL(["6d-5. Decomposition failed<br/>item stays deferred"])
    INVOKE -- Success --> PARSE["6d-6. Parse subtask list from<br/>agent JSON output"]

    PARSE --> CREATE["6d-7. Create child beads items<br/>--deps parent:original_id<br/>label: auto-decomposed"]

    CREATE --> CHAIN["6d-8. Chain siblings with<br/>blocking deps<br/>child 1 → child 2 → child 3"]

    CHAIN --> META["6d-9. Update parent metadata<br/>decomposed: true<br/>child_ids, depth+1"]

    META --> BLOCK["6d-10. Set parent status: blocked<br/>prevents re-claiming"]

    BLOCK --> DONE(["Subtasks enter ready queue<br/>execute serially"])

    style SKIP fill:#888,stroke:#333,color:#fff
    style SKIP_FAIL fill:#888,stroke:#333,color:#fff
    style DONE fill:#27ae60,stroke:#333,color:#fff
    style INVOKE fill:#4a90d9,stroke:#333,color:#fff
```

Subtasks inherit parent labels and execute in serial order via blocking dependencies. If subtasks themselves fail, they can be re-decomposed up to 3 levels deep.

## Work Agent Fail-Fast Outcomes

The work agent can return structured outcomes that skip the gate entirely. **Note:** FF-7 (too_large → decomposition) is the proposed flow per PokePoke-dkhkr; currently too_large goes to FF-6 like the other fail-fast outcomes.

```mermaid
flowchart TD
    RESULT(["FF-0. Work agent returns"]) --> CHECK{"FF-1. Agent outcome<br/>status?"}

    CHECK -- "success" --> GATE(["Continue to gate<br/>verification"])
    CHECK -- "blocked" --> FF_BLOCKED["FF-2a. Fail-fast: blocked<br/>runtime-discovered dependency"]
    CHECK -- "needs_clarification" --> FF_CLARIFY["FF-2b. Fail-fast: needs clarification<br/>ambiguous requirements"]
    CHECK -- "too_large" --> FF_LARGE["FF-2c. Fail-fast: too large<br/>agent provides scope analysis"]
    CHECK -- "timeout" --> TIMEOUT{"FF-3. Session ID<br/>saved?"}
    CHECK -- "crash/error" --> RETRY{"FF-4. Copilot failure<br/>retries < max?"}

    TIMEOUT -- Yes --> RESUME["FF-3a. Save session for resume<br/>retry with continuation"]
    TIMEOUT -- No --> RETRY

    RETRY -- Yes --> REINVOKE["FF-4a. Retry invoke_copilot()<br/>failure_retries++"]
    RETRY -- No --> FAIL_MAX(["FF-4b. FAIL — max copilot<br/>failures exceeded"])

    FF_BLOCKED --> COMMENT_B["FF-5a. Add beads comment<br/>with blocking reason"]
    FF_CLARIFY --> COMMENT_C["FF-5b. Add beads comment<br/>with clarification needed"]
    COMMENT_B --> SKIP_GATE(["FF-6. Skip gate<br/>defer item"])
    COMMENT_C --> SKIP_GATE

    FF_LARGE --> COMMENT_L["FF-5c. Add beads comment<br/>with too_large reason"]
    COMMENT_L --> SKIP_GATE_L(["FF-6. Skip gate<br/>defer item"])

    style GATE fill:#4a90d9,stroke:#333,color:#fff
    style SKIP_GATE fill:#e74c3c,stroke:#333,color:#fff
    style SKIP_GATE_L fill:#e74c3c,stroke:#333,color:#fff
    style FAIL_MAX fill:#e74c3c,stroke:#333,color:#fff
    style DECOMPOSE fill:#f1c40f,stroke:#333,color:#333
    style FF_BLOCKED fill:#f96,stroke:#333,color:#333
    style FF_CLARIFY fill:#f96,stroke:#333,color:#333
    style FF_LARGE fill:#f96,stroke:#333,color:#333
```

## Two Layers Compared

| Aspect | Pre-Commit Hooks | Gate Agent |
|--------|-----------------|------------|
| **What** | Syntax, types, coverage, lint | Logic correctness vs requirements |
| **When** | Every `git commit` | After work agent finishes |
| **Can bypass?** | No — CODEOWNERS protected | Yes — `gate_agent_enabled` config |
| **Runs tests?** | Yes — full pytest on modified files | No — assumes pre-commit passed |
| **On failure** | Blocks commit | Rejects → retry with feedback |
| **Retries** | Infinite (agent keeps trying to commit) | Configurable (default 3) |
| **Fast-fail** | Sequential chain, first failure stops | Structured outcomes skip gate |

## Key Files

| Purpose | File |
|---------|------|
| Main orchestration loop | `_wf_feature.py` |
| Gate agent executor | `src/pokepoke/agents/gate_agent_executor.py` |
| Feedback injection | `src/pokepoke/orchestration/workflow_helpers.py` |
| Rejection count tracking | `src/pokepoke/beads/beads_metadata.py` |
| Configuration | `src/pokepoke/config_types.py` |
| Pre-commit orchestration | `.githooks/pre-commit.ps1` |
| Gate agent prompt | `.pokepoke/prompts/gate-agent.md` |
| Work agent retry section | `.pokepoke/prompts/beads-item.md` |
