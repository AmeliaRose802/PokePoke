# Orchestrator Flow

Visual diagrams of PokePoke's top-level orchestration loop — how work items are fetched, claimed, processed, validated, and finalized.

## Full Orchestrator Loop (End-to-End)

The complete sequence from process start to shutdown, including initialization, work selection, agent invocation, gate review, and merge. Covers both single-shot and continuous modes.

**Color key:**
- � Purple = **AI agent invocation** (work, cleanup, gate, decomposition, maintenance)
- 🟦 Blue = **holding a lock** (worktree-setup or merge lock)
- 🟨 Yellow = **deterministic retry loop** (orchestrator logic, no AI)
- 🟩 Green = **success terminal**
- 🟥 Red = **failure terminal**
- ⬜ Default = **deterministic step** (code logic, CLI commands, git operations)

```mermaid
flowchart TD
    START(["0. python -m pokepoke"]) --> INIT["1. Startup &<br/>initialization"]
    INIT --> PREFLIGHT{"2. Preflight<br/>health checks"}

    PREFLIGHT -- Fail --> EXIT_FAIL(["EXIT code 1"])
    PREFLIGHT -- Pass --> FETCH["3. Fetch ready<br/>work items"]

    FETCH -- "bd/br query fails" --> EXIT_FAIL
    FETCH -- "Items returned" --> SELECT["4. Select<br/>work item"]

    SELECT -- "No items available" --> EXIT_OK(["EXIT code 0<br/>no work"])
    SELECT -- "Item selected" --> CLAIM["5. Claim item<br/>(worktree-setup lock)"]

    CLAIM -- Fail --> SKIP["Add to failed_claim_ids<br/>skip in future rounds"]
    CLAIM -- Success --> WORKTREE["6. Create worktree"]

    SKIP --> CONTINUOUS

    WORKTREE -- Fail --> FAIL_ITEM(["FAIL item"])
    WORKTREE -- Success --> RESUME{"7. Reclaimed<br/>item?"}

    RESUME -- Yes --> BUILD_RESUME["7a. Build resume<br/>context from git log"]
    RESUME -- No --> WORK_LOOP
    BUILD_RESUME --> WORK_LOOP

    WORK_LOOP["🤖 8. Work agent<br/>retry loop"] --> CLEANUP["9. Cleanup loop<br/>(commit + 🤖 if needed)"]
    CLEANUP --> GATE["🤖 10. Gate agent<br/>review loop"]

    GATE -- "Approved" --> FINALIZE_OK["11. Finalize success<br/>merge + close"]
    GATE -- "Rejected ≥ max" --> DECOMP_CHECK{"11b. Decomposition<br/>eligible?"}
    GATE -- "Rejected < max" --> WORK_LOOP

    DECOMP_CHECK -- "failures ≥ threshold<br/>or too_large signal" --> DECOMP_AGENT["🤖 11c. Decomposition<br/>agent"]
    DECOMP_CHECK -- "disabled or<br/>max depth reached" --> FAIL_ITEM

    DECOMP_AGENT --> FAIL_ITEM

    FINALIZE_OK --> RECORD["12. Record result<br/>& update stats"]
    FAIL_ITEM --> RECORD

    RECORD --> MAINT{"13. Maintenance<br/>due?"}
    MAINT -- Yes --> RUN_MAINT["🤖 13a. Run periodic<br/>maintenance agents"]
    MAINT -- No --> CONTINUOUS

    RUN_MAINT --> CONTINUOUS

    CONTINUOUS{"14. Continue?"}
    CONTINUOUS -- "Single-shot" --> FINALIZE_SESSION["15. Finalize session"]
    CONTINUOUS -- "Continuous + more work" --> PREFLIGHT
    CONTINUOUS -- "Shutdown signal" --> FINALIZE_SESSION

    FINALIZE_SESSION --> EXIT_OK_DONE(["EXIT code 0"])

    %% Lock-held steps (blue)
    style CLAIM fill:#4a90d9,stroke:#333,color:#fff

    %% AI agent invocations (purple)
    style WORK_LOOP fill:#9b59b6,stroke:#333,color:#fff
    style GATE fill:#9b59b6,stroke:#333,color:#fff
    style DECOMP_AGENT fill:#9b59b6,stroke:#333,color:#fff
    style RUN_MAINT fill:#9b59b6,stroke:#333,color:#fff

    %% Failure (red)
    style EXIT_FAIL fill:#e74c3c,stroke:#333,color:#fff
    style FAIL_ITEM fill:#e74c3c,stroke:#333,color:#fff

    %% Success (green)
    style EXIT_OK fill:#27ae60,stroke:#333,color:#fff
    style EXIT_OK_DONE fill:#27ae60,stroke:#333,color:#fff
    style FINALIZE_OK fill:#27ae60,stroke:#333,color:#fff
```

Steps 8–10 (purple, 🤖) are **AI agent invocations** — the work agent, cleanup agent, and gate agent loop until the item passes or retries are exhausted. All other steps are **deterministic** orchestrator logic (git commands, beads CLI, config checks). Step 5 (blue) holds the worktree-setup lock to serialize beads mutations. Finalization (step 11) acquires the merge lock (see [merge-workflow.md](merge-workflow.md) for details).

---

## 1. Startup & Initialization

`_setup_orchestrator()` in `orchestration/orchestrator.py`. Prepares everything the loop needs before processing any work items.

```mermaid
flowchart TD
    ENTRY(["python -m pokepoke<br/>__main__.py → main()"]) --> ARGS["1a. Parse CLI args<br/>--autonomous, --continuous,<br/>--max-agents, --interactive"]

    ARGS --> READY["1b. ensure_project_ready()<br/>verify .beads/ exists"]
    READY --> IDENTITY["1c. Initialize agent identity<br/>set $AGENT_NAME env var"]
    IDENTITY --> LOGGER["1d. Create RunLogger<br/>.pokepoke/runs/{run_id}/"]
    LOGGER --> SIGNALS["1e. Register signal handlers<br/>SIGTERM, SIGINT → graceful stop"]
    SIGNALS --> CONFIG["1f. Load config<br/>.pokepoke/pokepoke.config.yaml"]
    CONFIG --> BEADS_INIT["1g. Init beads state<br/>backfill events, recover<br/>stuck unassigned items"]
    BEADS_INIT --> PLUGINS["1h. Run startup plugins<br/>sync models, warm session pool"]
    PLUGINS --> STALE["1i. Run startup cleanup<br/>remove stale worktrees"]
    STALE --> RECOVER["1j. Recover stale items<br/>find in_progress from<br/>previous crashed sessions"]
    RECOVER --> PARALLEL{"1k. Resolve<br/>parallelism"}

    PARALLEL -- "max-agents > 1<br/>+ autonomous" --> PARALLEL_MODE(["→ Parallel mode<br/>(thread pool)"])
    PARALLEL -- "max-agents = 1<br/>or interactive" --> SEQ_MODE(["→ Sequential mode<br/>(main loop)"])

    style PARALLEL_MODE fill:#4a90d9,stroke:#333,color:#fff
    style SEQ_MODE fill:#27ae60,stroke:#333,color:#fff
```

Interactive mode always forces sequential (1 agent). Parallel mode dispatches items to a thread pool — see [Parallel Mode](#parallel-mode) below.

---

## 2. Preflight Health Checks

`_run_preflight()` → `handle_preflight_checks()`. Verifies the environment is sane before fetching work.

```mermaid
flowchart TD
    PRE["2. handle_preflight_checks()"] --> GIT{"Git repo<br/>valid?"}
    GIT -- No --> FAIL(["FAIL — exit 1"])
    GIT -- Yes --> BD{"Beads CLI<br/>available?"}
    BD -- No --> FAIL
    BD -- Yes --> CFG{"Config<br/>valid?"}
    CFG -- No --> FAIL
    CFG -- Yes --> ENV{"Environment<br/>OK?"}
    ENV -- No --> FAIL
    ENV -- Yes --> PASS(["PASS — continue<br/>to step 3"])

    style FAIL fill:#e74c3c,stroke:#333,color:#fff
    style PASS fill:#27ae60,stroke:#333,color:#fff
```

---

## 3. Fetch Ready Work Items

`_fetch_work_items()`. Ensures the main repo is clean, then queries beads for available work.

```mermaid
flowchart TD
    FETCH["3. _fetch_work_items()"] --> MAIN_CLEAN["3a. check_and_commit_main_repo()<br/>auto-commit .beads/ if needed"]

    MAIN_CLEAN -- Fail --> FAIL(["FAIL — exit 1"])
    MAIN_CLEAN -- OK --> QUERY["3b. get_ready_work_items()<br/>bd ready --json"]

    QUERY -- "Query fails (None)" --> FAIL
    QUERY -- "Returns items[]" --> RESULT(["Items ready<br/>for selection"])

    style FAIL fill:#e74c3c,stroke:#333,color:#fff
    style RESULT fill:#27ae60,stroke:#333,color:#fff
```

---

## 4. Select Work Item

`select_work_item()` in `orchestration/work_item_selection.py`. Filters and picks the next item to process.

```mermaid
flowchart TD
    SELECT["4. select_work_item()"] --> RECLAIM{"4a. Reclaimed<br/>stale items?"}

    RECLAIM -- "Yes + autonomous" --> RETURN_RECLAIM(["Return reclaimed<br/>item immediately"])
    RECLAIM -- No --> EMPTY{"4b. Ready list<br/>empty?"}

    EMPTY -- Yes --> NO_WORK(["No work — exit 0"])

    EMPTY -- No --> FILTER_SKIP["4c. Remove failed_claim_ids<br/>(items that failed claiming<br/>earlier this session)"]

    FILTER_SKIP --> FILTER_AVAIL["4d. Remove unavailable items:<br/>• assigned to other agents<br/>• human-required label<br/>• already closed<br/>• blocked status<br/>• exceeded gate rejections"]

    FILTER_AVAIL --> MODE{"4e. Interactive<br/>or autonomous?"}

    MODE -- Interactive --> PROMPT["Display items list<br/>prompt user for selection"]
    MODE -- Autonomous --> AUTO["Hierarchical priority<br/>selection"]

    PROMPT --> ITEM(["Selected item"])
    AUTO --> ITEM

    style NO_WORK fill:#27ae60,stroke:#333,color:#fff
    style RETURN_RECLAIM fill:#27ae60,stroke:#333,color:#fff
    style ITEM fill:#27ae60,stroke:#333,color:#fff
```

Autonomous selection uses priority-based ordering. Items that exceeded `max_gate_rejections_per_item` (default 5) are silently dropped.

---

## 5. Claim Work Item

`assign_and_sync_item()`. Acquires the worktree-setup lock and marks the item as in-progress in beads.

```mermaid
flowchart TD
    CLAIM["5. assign_and_sync_item()"] --> LOCK["5a. Acquire<br/>worktree-setup.lock"]
    LOCK --> ASSIGN["5b. bd update {id}<br/>--status in_progress<br/>--assign $AGENT_NAME"]
    ASSIGN --> SYNC["5c. bd sync"]
    SYNC --> RELEASE["5d. Release lock"]
    RELEASE --> OK(["Item claimed"])

    ASSIGN -- Fail --> RELEASE_FAIL["Release lock"]
    RELEASE_FAIL --> SKIP(["Add to failed_claim_ids<br/>skip this item"])

    style LOCK fill:#4a90d9,stroke:#333,color:#fff
    style ASSIGN fill:#4a90d9,stroke:#333,color:#fff
    style SYNC fill:#4a90d9,stroke:#333,color:#fff
    style RELEASE fill:#4a90d9,stroke:#333,color:#fff
    style RELEASE_FAIL fill:#4a90d9,stroke:#333,color:#fff
    style OK fill:#27ae60,stroke:#333,color:#fff
    style SKIP fill:#e74c3c,stroke:#333,color:#fff
```

The lock serializes all beads mutations and worktree creation across agents.

---

## 6. Create Worktree

`create_worktree()` in `worktrees/worktrees.py`. Builds an isolated workspace for the agent.

```mermaid
flowchart TD
    WT["6. create_worktree()"] --> DIR["6a. Create directory<br/>./worktrees/task-{item_id}/"]
    DIR --> BRANCH["6b. Create git branch<br/>pokepoke/{item_id}<br/>from base branch"]
    BRANCH --> EXISTING{"6c. Existing<br/>worktree?"}

    EXISTING -- "Yes (reuse)" --> VALIDATE["6d. Validate integrity"]
    EXISTING -- "No (new)" --> ADD["6d. git worktree add"]

    ADD --> VALIDATE
    VALIDATE -- OK --> READY(["Worktree ready"])
    VALIDATE -- Fail --> FAIL(["FAIL — worktree<br/>creation failed"])

    style READY fill:#27ae60,stroke:#333,color:#fff
    style FAIL fill:#e74c3c,stroke:#333,color:#fff
```

---

## 7. Build Resume Context

For reclaimed items (recovered from a crashed session), the orchestrator extracts previous progress to help the agent continue where it left off.

```mermaid
flowchart TD
    CHECK{"7. Was item<br/>reclaimed?"}
    CHECK -- No --> FRESH["Build fresh prompt<br/>from work item"]
    CHECK -- Yes --> LOG["7a. Extract git log<br/>from existing worktree"]
    LOG --> CTX["7b. Format as resume<br/>context with previous<br/>progress summary"]
    CTX --> PROMPT(["Prompt ready<br/>→ enter work loop"])
    FRESH --> PROMPT

    style PROMPT fill:#27ae60,stroke:#333,color:#fff
```

---

## 8. Work Agent Retry Loop

`process_work_item()` in `orchestration/workflow.py`. The core loop that invokes the AI backend with retry and timeout logic.

```mermaid
flowchart TD
    LOOP_START(["8. Enter work<br/>agent loop"]) --> TIMEOUT{"8a. Timeout<br/>exceeded?"}

    TIMEOUT -- "Yes + restarts left" --> BACKOFF["8b. Sleep with backoff<br/>30s → 60s → 120s"]
    BACKOFF --> RESET["8c. Reset start_time<br/>decrement restarts"]
    RESET --> INVOKE

    TIMEOUT -- "Yes + no restarts" --> FAIL(["FAIL — timeout<br/>exhausted"])
    TIMEOUT -- No --> PROMPT["8d. Build prompt<br/>include retry feedback<br/>if previous attempt failed"]

    PROMPT --> INVOKE["🤖 8e. Invoke AI backend<br/>copilot/claude<br/>in worktree"]

    INVOKE --> RESULT{"8f. Agent<br/>result?"}

    RESULT -- Success --> EXIT_OK(["→ Step 9<br/>cleanup loop"])

    RESULT -- "blocked" --> BLOCK["8g. Mark blocked<br/>in beads"]
    BLOCK --> FAIL

    RESULT -- "needs_clarification" --> BLOCK_HUMAN["8h. Block item<br/>needs human input"]
    BLOCK_HUMAN --> FAIL

    RESULT -- "Crash / error" --> RETRY{"8i. Retries<br/>remaining?<br/>(max 3)"}

    RETRY -- "Yes + not rate limited" --> FEEDBACK["8j. Extract feedback<br/>from error output"]
    FEEDBACK --> LOOP_START

    RETRY -- No --> FAIL

    RESULT -- "Timeout + session_id" --> SAVE_SESSION["8k. Save session<br/>for resume"]
    SAVE_SESSION --> RETRY

    %% AI agent invocation (purple)
    style INVOKE fill:#9b59b6,stroke:#333,color:#fff

    %% Deterministic orchestrator logic (yellow)
    style LOOP_START fill:#f1c40f,stroke:#333,color:#333
    style TIMEOUT fill:#f1c40f,stroke:#333,color:#333
    style BACKOFF fill:#f1c40f,stroke:#333,color:#333
    style RESET fill:#f1c40f,stroke:#333,color:#333
    style PROMPT fill:#f1c40f,stroke:#333,color:#333
    style RESULT fill:#f1c40f,stroke:#333,color:#333
    style RETRY fill:#f1c40f,stroke:#333,color:#333
    style FEEDBACK fill:#f1c40f,stroke:#333,color:#333
    style SAVE_SESSION fill:#f1c40f,stroke:#333,color:#333

    style FAIL fill:#e74c3c,stroke:#333,color:#fff
    style EXIT_OK fill:#27ae60,stroke:#333,color:#fff
```

Session resume reuses the same `session_id` so the AI backend can continue from where it timed out rather than starting fresh.

---

## 9. Cleanup Loop

`run_cleanup_with_timeout()` in `orchestration/workflow_helpers.py`. Ensures all work is committed in the worktree before gate review. The loop first attempts a **deterministic** `git commit` (which triggers pre-commit hooks). Only if the commit fails (hooks reject it) does it invoke the **cleanup AI agent** to fix validation errors. If the commit succeeds on the first try, no agent is invoked.

```mermaid
flowchart TD
    CLEANUP(["9. Enter cleanup<br/>loop"]) --> CHECK{"9a. Uncommitted<br/>non-beads changes?<br/>(git status)"}

    CHECK -- Clean --> DONE(["→ Step 10<br/>gate review"])

    CHECK -- "Uncommitted changes" --> COMMIT["9b. Try git commit<br/>(runs pre-commit hooks)"]

    COMMIT -- "Commit succeeds<br/>(hooks pass)" --> DONE
    COMMIT -- "Commit fails<br/>(hooks reject)" --> AGENT["🤖 9c. Invoke cleanup agent<br/>to fix validation errors"]

    AGENT -- Success --> RECHECK{"9d. Re-check<br/>git status"}
    RECHECK -- Clean --> DONE
    RECHECK -- "Still dirty" --> COMMIT

    AGENT -- Fail --> FAIL(["FAIL item"])

    CHECK -- "Aggregate timeout" --> RESTART(["Restart work agent<br/>→ back to step 8"])

    %% AI agent invocation (purple) — only runs if commit fails
    style AGENT fill:#9b59b6,stroke:#333,color:#fff

    %% Deterministic orchestrator logic (yellow)
    style CLEANUP fill:#f1c40f,stroke:#333,color:#333
    style CHECK fill:#f1c40f,stroke:#333,color:#333
    style COMMIT fill:#f1c40f,stroke:#333,color:#333
    style RECHECK fill:#f1c40f,stroke:#333,color:#333

    style DONE fill:#27ae60,stroke:#333,color:#fff
    style FAIL fill:#e74c3c,stroke:#333,color:#fff
    style RESTART fill:#f39c12,stroke:#333,color:#fff
```

---

## 10. Gate Agent Review Loop

`run_gate_loop()` in `orchestration/gate_agent_loop.py`. A second AI agent validates the work (tests, coverage, quality) before merging.

```mermaid
flowchart TD
    GATE(["10. Enter gate<br/>agent loop"]) --> BUILD["10a. Build handoff context<br/>work result + git state"]
    BUILD --> INVOKE["🤖 10b. Invoke gate agent<br/>analyze tests, coverage,<br/>code quality"]

    INVOKE -- Exception --> CRASH_COUNT{"10c. Crash<br/>attempts < 3?"}
    CRASH_COUNT -- Yes --> BUILD
    CRASH_COUNT -- No --> FALLBACK

    INVOKE -- Timeout --> TIMEOUT_COUNT{"10d. Timeout<br/>attempts < 3?"}
    TIMEOUT_COUNT -- Yes --> RESUME["10e. Resume gate<br/>with session_id"]
    RESUME --> INVOKE
    TIMEOUT_COUNT -- No --> FALLBACK

    INVOKE -- Success --> VERDICT{"10f. Gate<br/>verdict?"}

    VERDICT -- Approved --> PASS(["→ Step 11<br/>finalize success"])

    VERDICT -- Rejected --> REJECTION_COUNT{"10g. Rejections<br/>≥ max? (5)"}
    REJECTION_COUNT -- No --> EXTRACT["10h. Extract gate<br/>feedback"]
    EXTRACT --> REWORK(["→ Back to step 8<br/>rework with feedback"])

    REJECTION_COUNT -- Yes --> TOO_LARGE{"10i. Reason =<br/>too_large?"}
    TOO_LARGE -- Yes --> DECOMPOSE["🤖 10j. Run<br/>decomposition agent"]
    DECOMPOSE --> FAIL(["FAIL item"])
    TOO_LARGE -- No --> BLOCK["10k. Block item<br/>in beads"]
    BLOCK --> FAIL

    FALLBACK{"Commits<br/>exist?"}
    FALLBACK -- Yes --> FALLBACK_ACCEPT(["Fallback accept<br/>→ step 11"])
    FALLBACK -- No --> FAIL

    %% AI agent invocations (purple)
    style INVOKE fill:#9b59b6,stroke:#333,color:#fff
    style DECOMPOSE fill:#9b59b6,stroke:#333,color:#fff

    %% Deterministic orchestrator logic (yellow)
    style GATE fill:#f1c40f,stroke:#333,color:#333
    style BUILD fill:#f1c40f,stroke:#333,color:#333
    style VERDICT fill:#f1c40f,stroke:#333,color:#333
    style CRASH_COUNT fill:#f1c40f,stroke:#333,color:#333
    style TIMEOUT_COUNT fill:#f1c40f,stroke:#333,color:#333
    style RESUME fill:#f1c40f,stroke:#333,color:#333
    style REJECTION_COUNT fill:#f1c40f,stroke:#333,color:#333
    style EXTRACT fill:#f1c40f,stroke:#333,color:#333

    style PASS fill:#27ae60,stroke:#333,color:#fff
    style FALLBACK_ACCEPT fill:#27ae60,stroke:#333,color:#fff
    style FAIL fill:#e74c3c,stroke:#333,color:#fff
    style REWORK fill:#f39c12,stroke:#333,color:#fff
```

Gate rejections feed back to the work agent as corrective prompts. After `max_gate_rejections_per_item` (default 5), the orchestrator calls `_maybe_decompose()` which checks `should_decompose()`: if total failures ≥ `decomposition_failure_threshold` (default 3) or the work/gate agent signalled `too_large`, and decomposition depth hasn't reached max — the decomposition agent splits the item into sub-tasks. Otherwise the item is just blocked. If the gate itself crashes/times out but commits exist, the orchestrator accepts the work as a fallback.

---

## 11. Finalization

`_finalize_item_result()` in `orchestration/finalization.py`. Merges successful work or records failure.

```mermaid
flowchart TD
    RESULT{"11. Item<br/>outcome?"}

    RESULT -- Success --> MERGE["11a. Merge worktree<br/>→ target branch<br/>(see merge-workflow.md)"]
    MERGE --> CLOSE["11b. bd close {id}<br/>with reason"]
    CLOSE --> CLEANUP_WT["11c. Remove worktree<br/>& delete branch"]
    CLEANUP_WT --> DISCOVERED["11d. Extract discovered<br/>items from output"]
    DISCOVERED --> DONE_OK(["Item complete"])

    RESULT -- Failure --> RECONCILE{"11e. Reconciliation:<br/>did work actually<br/>succeed?"}
    RECONCILE -- Yes --> MERGE
    RECONCILE -- No --> PRESERVE["11f. Preserve worktree<br/>for manual recovery"]
    PRESERVE --> FAIL_BD["11g. fail_task(id, reason)<br/>in beads"]
    FAIL_BD --> DONE_FAIL(["Item failed"])

    style MERGE fill:#4a90d9,stroke:#333,color:#fff
    style CLOSE fill:#4a90d9,stroke:#333,color:#fff
    style CLEANUP_WT fill:#4a90d9,stroke:#333,color:#fff
    style DONE_OK fill:#27ae60,stroke:#333,color:#fff
    style DONE_FAIL fill:#e74c3c,stroke:#333,color:#fff
```

The merge step acquires the merge lock — see [merge-workflow.md](merge-workflow.md) for the full merge pipeline. Reconciliation catches cases where the work agent reports failure but the code was actually committed and passing.

---

## 12. Record Result & Update Stats

`_record_item_result()` in `orchestration/session_lifecycle.py`. Captures metrics for the completed item.

```mermaid
flowchart TD
    RECORD["12. _record_item_result()"] --> RETRIES["12a. Record retries<br/>(request_count - 1)"]
    RETRIES --> AGENTS["12b. Record agent runs<br/>(work, cleanup, gate)"]
    AGENTS --> TOKENS["12c. Record token counts<br/>input/output per model"]
    TOKENS --> DURATION["12d. Record duration"]
    DURATION --> SESSION["12e. Update session stats<br/>items_completed++"]
    SESSION --> BEADS_METRICS["12f. Store beads metrics"]
    BEADS_METRICS --> CHECK{"12g. Repeated<br/>failures?"}
    CHECK -- Yes --> HUMAN["12h. Mark item<br/>needs-human-attention"]
    CHECK -- No --> DONE(["→ Step 13"])
    HUMAN --> DONE
```

---

## 13. Periodic Maintenance

`run_periodic_maintenance()` in `maintenance/maintenance_scheduler.py`. Triggered after a configurable number of completed items.

```mermaid
flowchart TD
    MAINT["13. run_periodic_maintenance()"] --> COLLECT["13a. Collect due agents<br/>from frequency config"]

    COLLECT --> AGENTS["Due agents:<br/>• Tech Debt (every 5 items)<br/>• Janitor (every 2 items)<br/>• Backlog Cleanup (every 7)<br/>• Worktree Cleanup (every 4)"]

    AGENTS --> EACH["For each due agent:"]

    EACH --> SINGLETON{"13b. Singleton<br/>guard?"}
    SINGLETON -- "Already running" --> SKIP["Skip (log deferral)"]

    SINGLETON -- "Available" --> EXCLUSIVE{"13c. Exclusive<br/>agent?<br/>(Janitor, WT Cleanup)"}

    EXCLUSIVE -- Yes --> DRAIN["13d. Wait for all<br/>work agents to drain"]
    DRAIN --> RUN

    EXCLUSIVE -- No --> RUN["🤖 13e. Run maintenance agent<br/>with prompt + optional worktree"]

    RUN --> STATS["13f. Update session stats"]
    STATS --> NEXT["Next agent"]
    SKIP --> NEXT

    %% AI agent invocation (purple)
    style RUN fill:#9b59b6,stroke:#333,color:#fff

    style DRAIN fill:#4a90d9,stroke:#333,color:#fff
```

Exclusive agents (Janitor, Worktree Cleanup) wait until all active work agents finish before running, to avoid conflicts on the main repo.

---

## 14. Loop Control

Decision point after each item — determines whether to continue or shut down.

```mermaid
flowchart TD
    DONE["Item processing<br/>complete"] --> SHUTDOWN{"14a. Shutdown<br/>signal received?"}

    SHUTDOWN -- Yes --> FINALIZE(["→ Step 15<br/>finalize session"])

    SHUTDOWN -- No --> MODE{"14b. Run mode?"}

    MODE -- Single-shot --> FINALIZE

    MODE -- "Continuous +<br/>interactive" --> PROMPT["14c. Prompt user:<br/>Process another? Y/n"]
    PROMPT -- Y --> RESTART(["→ Back to step 2<br/>preflight"])
    PROMPT -- N --> FINALIZE

    MODE -- "Continuous +<br/>autonomous" --> SLEEP["14d. Sleep 5 seconds"]
    SLEEP --> RESTART

    style RESTART fill:#f1c40f,stroke:#333,color:#333
    style FINALIZE fill:#27ae60,stroke:#333,color:#fff
```

---

## 15. Session Finalization & Shutdown

`_finalize_session()` in `orchestration/session_lifecycle.py`. Wraps up the session and cleans up resources.

```mermaid
flowchart TD
    FIN["15. _finalize_session()"] --> POSTMORTEM["🤖 15a. Run post-mortem<br/>agent (if enabled)"]
    POSTMORTEM --> BD_STATS["15b. Collect ending<br/>beads stats"]
    BD_STATS --> MERGE_STATS["15c. Collect merge<br/>queue stats"]
    MERGE_STATS --> STATE["15d. Commit state<br/>branch (if enabled)"]
    STATE --> SUMMARY["15e. Print summary:<br/>items completed, requests,<br/>elapsed time, tokens"]
    SUMMARY --> RUN_LOG["15f. Finalize run logger"]
    RUN_LOG --> CLEAR["15g. Clear session<br/>stats & banner"]
    CLEAR --> CLEANUP["15h. Process cleanup:<br/>stop UI, shutdown OTel,<br/>merge queue shutdown (10s),<br/>unregister signal handlers"]
    CLEANUP --> EXIT(["EXIT code 0"])

    %% AI agent invocation (purple)
    style POSTMORTEM fill:#9b59b6,stroke:#333,color:#fff

    style EXIT fill:#27ae60,stroke:#333,color:#fff
```

---

## Parallel Mode

When `--max-agents N` (N > 1) is used with `--autonomous`. Dispatches items to a thread pool instead of processing sequentially.

```mermaid
flowchart TD
    INIT["Thread pool executor<br/>(N workers)"] --> PREFLIGHT["2. Preflight checks<br/>(serial)"]
    PREFLIGHT --> FETCH["3. Fetch items<br/>(serial)"]
    FETCH --> SELECT["4. Select multiple items<br/>(parallel-safe,<br/>avoid label conflicts)"]

    SELECT --> DISPATCH["Dispatch to workers"]

    DISPATCH --> W1["🤖 Worker 1:<br/>steps 5–11"]
    DISPATCH --> W2["🤖 Worker 2:<br/>steps 5–11"]
    DISPATCH --> WN["🤖 Worker N:<br/>steps 5–11"]

    W1 --> COLLECT["Collect results<br/>(thread-safe)"]
    W2 --> COLLECT
    WN --> COLLECT

    COLLECT --> RECORD["12. Record results"]
    RECORD --> MAINT["13. Maintenance<br/>(serial)"]
    MAINT --> BREAKER{"Circuit<br/>breaker?"}

    BREAKER -- "Memory OK +<br/>failures < threshold" --> PREFLIGHT
    BREAKER -- "Tripped" --> FINALIZE(["15. Finalize session"])

    style W1 fill:#9b59b6,stroke:#333,color:#fff
    style W2 fill:#9b59b6,stroke:#333,color:#fff
    style WN fill:#9b59b6,stroke:#333,color:#fff
    style FINALIZE fill:#27ae60,stroke:#333,color:#fff
```

**Concurrency safety:**
- `worktree-setup.lock` serializes beads mutations + worktree creation
- `failed_claim_ids` protected by `threading.Lock`
- Session stats recorded atomically
- Circuit breaker monitors memory pressure and consecutive failures

---

## Retry & Threshold Summary

```mermaid
flowchart LR
    subgraph "Work Agent Retries"
        A["Copilot failures"] -->|"max 3"| A1["Retry with feedback"]
        B["Timeout restarts"] -->|"max 3"| B1["Backoff 30→60→120s"]
    end

    subgraph "Gate Agent Retries"
        C["Gate crashes"] -->|"max 3"| C1["Fresh retry"]
        D["Gate timeouts"] -->|"max 3"| D1["Resume with session_id"]
        E["Gate rejections"] -->|"max 5 per item"| E1["Rework with feedback"]
    end

    subgraph "Maintenance Frequencies"
        F["Janitor"] -->|"every 2 items"| F1["Exclusive"]
        G["Worktree Cleanup"] -->|"every 4 items"| G1["Exclusive"]
        H["Tech Debt"] -->|"every 5 items"| H1["Concurrent OK"]
        I["Backlog Cleanup"] -->|"every 7 items"| I1["Concurrent OK"]
    end
```

## Key Files

| Purpose | File |
|---------|------|
| Entry point | `src/pokepoke/__main__.py` |
| Orchestrator setup & loop | `src/pokepoke/orchestration/orchestrator.py` |
| Work item processing | `src/pokepoke/orchestration/workflow.py` |
| Workflow helpers (cleanup) | `src/pokepoke/orchestration/workflow_helpers.py` |
| Work item selection | `src/pokepoke/orchestration/work_item_selection.py` |
| Gate agent loop | `src/pokepoke/orchestration/gate_agent_loop.py` |
| Finalization | `src/pokepoke/orchestration/finalization.py` |
| Session lifecycle | `src/pokepoke/orchestration/session_lifecycle.py` |
| AI backend invocation | `src/pokepoke/models/ai_backends.py` |
| Parallel mode | `src/pokepoke/agents/parallel.py` |
| Maintenance scheduler | `src/pokepoke/maintenance/maintenance_scheduler.py` |
| Worktree management | `src/pokepoke/worktrees/worktrees.py` |
| Merge pipeline | `src/pokepoke/worktrees/worktree_merge_handler.py` |
| Signal handlers | `src/pokepoke/utils/signal_handlers.py` |
| Beads integration | `src/pokepoke/beads/beads_query.py` |
