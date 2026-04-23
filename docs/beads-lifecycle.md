# Beads Work Item Lifecycle & Concurrency Model

Visual diagrams of a beads work item's complete lifecycle — from discovery through completion — including all locks, concurrent agent coordination, and ownership boundaries.

## Work Item State Machine

The complete set of states a beads item can occupy and who triggers each transition.

**Color key:**
- 🟦 Blue = **orchestrator-owned** transition
- 🟪 Purple = **worker-owned** transition
- 🟨 Yellow = **beads daemon** (automatic)
- 🟥 Red = **failure state**
- 🟩 Green = **terminal state**

```mermaid
stateDiagram-v2
    [*] --> open: bd create
    open --> in_progress: assign_and_sync_item()
    in_progress --> closed: close_item()
    in_progress --> blocked: block_item()
    in_progress --> backlog: defer_item()
    in_progress --> open: fail_task() → unassign

    blocked --> open: dependency resolved
    backlog --> open: manual triage

    closed --> [*]

    note right of open
        Visible via bd ready --json
        Unblocked + unassigned
    end note

    note right of in_progress
        Assigned to specific agent
        Protected by per-item claim lock
    end note

    note right of closed
        bd close + reason
        ~30s daemon debounce before propagation
    end note
```

## End-to-End Item Lifecycle (Single Worker)

The full journey of one work item from poll discovery through merge and closure.

**Color key:**
- 🟦 Blue = **holding worktree-setup lock**
- 🟪 Purple = **holding merge-queue lock**
- 🟨 Yellow = **holding beads-claim-{id} lock**
- ⬜ Default = **no shared lock held**
- 🟥 Red = **failure exit**
- 🟩 Green = **success terminal**

```mermaid
flowchart TD
    POLL(["1. Poll loop<br/>bd ready --json"]) --> SELECT["2. Select item<br/>(priority-based or user pick)"]

    SELECT --> CLAIM_LOCK["3. Acquire beads-claim-{id}<br/>timeout=0 (non-blocking!)"]
    CLAIM_LOCK -- "Lock held by another agent" --> SKIP(["SKIP — another agent<br/>already claiming this item"])
    CLAIM_LOCK -- "Lock acquired" --> VERIFY["4. Verify item unassigned<br/>bd show {id} --json"]

    VERIFY -- "Already assigned" --> RELEASE_CLAIM(["Release claim lock<br/>skip item"])
    VERIFY -- "Unassigned" --> WT_LOCK["5. Acquire worktree-setup lock<br/>180s timeout, 5min stale"]

    WT_LOCK --> ASSIGN["6. bd update {id}<br/>--status in_progress<br/>-a agent_name"]
    ASSIGN --> VERIFY2["7. Detect-and-abort<br/>re-read bd show → verify<br/>assignee == agent_name"]
    VERIFY2 -- "Mismatch!" --> ABORT_CLAIM(["INVARIANT VIOLATION<br/>abort + crash"])
    VERIFY2 -- "Confirmed" --> CREATE_WT["8. git worktree add<br/>worktrees/task-{id}"]

    CREATE_WT --> RELEASE_SETUP["9. Release worktree-setup lock<br/>+ release claim lock"]

    RELEASE_SETUP --> INVOKE["10. Invoke AI backend<br/>cwd = worktree path<br/>task context + instructions"]

    INVOKE --> VALIDATE{"11. Validate<br/>work output"}

    VALIDATE -- "Tests fail / quality gate" --> RETRY_AGENT["12. Retry AI with<br/>corrective feedback"]
    RETRY_AGENT --> VALIDATE

    VALIDATE -- "Max retries exhausted" --> FAIL_TASK["13. fail_task()<br/>unassign item → open"]
    VALIDATE -- "Pass" --> MERGE_LOCK["14. Acquire merge-queue lock<br/>600s timeout, 10min stale"]

    MERGE_LOCK --> PRE_MERGE["15. Pre-merge checks<br/>(see merge-workflow.md)"]
    PRE_MERGE --> INTEGRATE["16. Integrate target into worktree<br/>git merge target in worktree"]

    INTEGRATE -- "Clean" --> MERGE["17. git merge --no-ff<br/>on target branch"]
    INTEGRATE -- "Conflict" --> CONFLICT["Handle conflicts<br/>(see merge-workflow.md)"]

    MERGE --> POST_VAL{"18. Post-merge<br/>validation"}
    POST_VAL -- "Pass" --> CLEANUP_WT["19. git worktree remove --force<br/>git branch -D"]
    POST_VAL -- "Fail" --> ROLLBACK["git reset --hard HEAD~1"]

    CLEANUP_WT --> CLOSE["20. bd close {id}<br/>--reason 'message'"]
    CLOSE --> RELEASE_MERGE(["21. Release merge lock<br/>DONE ✓"])

    FAIL_TASK --> RELEASE_FAIL(["Item back to open<br/>worktree preserved"])

    %% Claim lock (yellow)
    style CLAIM_LOCK fill:#f1c40f,stroke:#333,color:#333
    style VERIFY fill:#f1c40f,stroke:#333,color:#333

    %% Worktree-setup lock (blue)
    style WT_LOCK fill:#4a90d9,stroke:#333,color:#fff
    style ASSIGN fill:#4a90d9,stroke:#333,color:#fff
    style VERIFY2 fill:#4a90d9,stroke:#333,color:#fff
    style CREATE_WT fill:#4a90d9,stroke:#333,color:#fff

    %% Merge lock (purple)
    style MERGE_LOCK fill:#8e44ad,stroke:#333,color:#fff
    style PRE_MERGE fill:#8e44ad,stroke:#333,color:#fff
    style INTEGRATE fill:#8e44ad,stroke:#333,color:#fff
    style MERGE fill:#8e44ad,stroke:#333,color:#fff
    style POST_VAL fill:#8e44ad,stroke:#333,color:#fff
    style CLEANUP_WT fill:#8e44ad,stroke:#333,color:#fff
    style CLOSE fill:#8e44ad,stroke:#333,color:#fff

    %% Failure
    style SKIP fill:#e74c3c,stroke:#333,color:#fff
    style RELEASE_CLAIM fill:#e74c3c,stroke:#333,color:#fff
    style ABORT_CLAIM fill:#e74c3c,stroke:#333,color:#fff
    style FAIL_TASK fill:#e74c3c,stroke:#333,color:#fff
    style ROLLBACK fill:#e74c3c,stroke:#333,color:#fff

    %% Success
    style RELEASE_MERGE fill:#27ae60,stroke:#333,color:#fff
```

Steps 3–4 (yellow) use the **per-item non-blocking claim lock** — if another agent is already claiming this specific item, we fail immediately (timeout=0) rather than waiting. Steps 5–9 (blue) serialize worktree creation and beads assignment atomically. Steps 14–21 (purple) serialize merges to the target branch. The AI invocation (step 10) runs with **no shared locks held** — only the worktree branch provides isolation.

## Parallel Agent Coordination

How multiple agents interact with the shared beads database and lock system when running concurrently via `ThreadPoolExecutor`.

```mermaid
sequenceDiagram
    participant Poll as Poll Loop<br/>(main thread)
    participant W1 as Worker-1
    participant W2 as Worker-2
    participant BD as Beads DB<br/>(bd CLI)
    participant Locks as .pokepoke/locks/
    participant Git as Git Repo<br/>(main branch)

    Poll->>BD: bd ready --json
    BD-->>Poll: [item-A, item-B, item-C]

    par Dispatch workers
        Poll->>W1: process(item-A)
        Poll->>W2: process(item-B)
    end

    Note over W1,Locks: Both workers race for their items

    W1->>Locks: acquire beads-claim-A (non-blocking) ✓
    W2->>Locks: acquire beads-claim-B (non-blocking) ✓

    W1->>BD: bd show A → unassigned ✓
    W2->>BD: bd show B → unassigned ✓

    W1->>Locks: acquire worktree-setup ✓
    Note over W2,Locks: W2 blocks until W1 releases

    W1->>BD: bd update A --status in_progress
    W1->>Git: git worktree add task-A
    W1->>Locks: release worktree-setup

    W2->>Locks: acquire worktree-setup ✓
    W2->>BD: bd update B --status in_progress
    W2->>Git: git worktree add task-B
    W2->>Locks: release worktree-setup

    par AI invocation (no shared locks)
        W1->>W1: Copilot works in worktree-A
        W2->>W2: Copilot works in worktree-B
    end

    Note over W1,Git: W1 finishes first

    W1->>Locks: acquire merge-queue ✓
    W1->>Git: integrate + merge --no-ff A
    W1->>BD: bd close A
    W1->>Locks: release merge-queue

    W2->>Locks: acquire merge-queue ✓
    W2->>Git: integrate + merge --no-ff B
    W2->>BD: bd close B
    W2->>Locks: release merge-queue

    Poll->>BD: bd ready --json (next cycle)
```

**Key insight:** The `worktree-setup` lock serializes the critical section of claim + worktree creation but releases before the AI invocation begins. Workers run in parallel during the actual work phase with no shared locks — only their isolated worktree branches provide concurrency safety. The `merge-queue` lock serializes final merges one at a time.

## Double-Claim Prevention (TOCTOU Elimination)

How PokePoke prevents two agents from claiming the same work item, even when `bd ready` returns the same list to both.

```mermaid
sequenceDiagram
    participant A as Agent Alpha
    participant B as Agent Bravo
    participant Locks as .pokepoke/locks/
    participant BD as Beads DB

    Note over A,B: Both see item-123 in bd ready

    A->>Locks: acquire beads-claim-123<br/>timeout=0 ✓
    B->>Locks: acquire beads-claim-123<br/>timeout=0 ✗ LOCKED!
    B-->>B: Timeout → skip item-123

    A->>BD: bd show 123 → unassigned ✓
    A->>BD: bd update 123 --status in_progress -a Alpha
    A->>BD: bd show 123 → assignee=Alpha ✓ (detect-and-abort verify)
    A->>Locks: release beads-claim-123

    Note over B: Bravo moves to next item in ready list
    B->>Locks: acquire beads-claim-456<br/>timeout=0 ✓
    B->>BD: (claims item-456 instead)
```

The per-item lock is **non-blocking** (timeout=0). The second agent doesn't wait — it immediately moves on. After the `bd update`, the claimer does a **detect-and-abort** re-read to verify the assignment actually took effect (guards against beads CLI failures or races at the database level).

## Lock Inventory

All locks used by PokePoke, their scope, and which operations they protect.

| Lock Name | File | Scope | Timeout | Stale Age | Protects |
|-----------|------|-------|---------|-----------|----------|
| `beads-claim-{id}` | `.pokepoke/locks/beads-claim-{id}.lock` | Per-item | **0s** (non-blocking) | N/A | TOCTOU on item claim |
| `worktree-setup` | `.pokepoke/locks/worktree-setup.lock` | Global | 180s | 5min | `bd update` + `git worktree add` atomicity |
| `merge-queue` | `.pokepoke/locks/merge-queue.lock` | Global | 600s | 10min | Serializes merges to target branch |
| `beads-db` | `.pokepoke/locks/beads-db.lock` | Global | 180s | 5min | Beads mutation commands |
| `worktree-manifest` | `.pokepoke/locks/worktree-manifest.lock` | Global | 30s | 2min | `uncleaned_worktrees.json` read-modify-write |
| `model-registry` | `.pokepoke/locks/model-registry.lock` | Global | 30s | 2min | Warm session pool configuration |
| `_main_repo_git_lock` | *(threading.RLock, in-memory)* | Process | N/A | N/A | Git index.lock contention between poll loop and merge workers |

**Stale detection:** Each file lock writes a `.lock.meta` sidecar with PID + timestamp. On acquisition timeout, the holder PID is checked (`os.kill(pid, 0)` on POSIX, `OpenProcess()` on Windows). If the process is dead, the lock is broken and re-acquired.

## Responsibility Matrix

Which component owns which lifecycle operations.

```mermaid
flowchart LR
    subgraph "Orchestrator<br/>(orchestrator.py)"
        O1[Poll bd ready]
        O2[Select item]
        O3[Dispatch to worker]
        O4[Record stats]
    end

    subgraph "Workflow<br/>(workflow.py)"
        W1[Claim item<br/>assign_and_sync_item]
        W2[Create worktree]
        W3[Invoke AI backend]
        W4[Validation loop<br/>+ retry with feedback]
    end

    subgraph "Finalization<br/>(finalization.py)"
        F1[Merge worktree<br/>to target branch]
        F2[Close beads item<br/>bd close]
        F3[Cleanup worktree<br/>git worktree remove]
        F4[Close parent items<br/>if all children done]
    end

    subgraph "Beads Management<br/>(beads_management.py)"
        B1["assign_and_sync_item()"]
        B2["close_item()"]
        B3["fail_task() → unassign"]
        B4["block_item()"]
        B5["defer_item()"]
    end

    O1 --> O2 --> O3
    O3 --> W1 --> W2 --> W3 --> W4
    W4 -- "pass" --> F1 --> F2 --> F3
    W4 -- "fail" --> B3

    style O1 fill:#4a90d9,stroke:#333,color:#fff
    style O2 fill:#4a90d9,stroke:#333,color:#fff
    style O3 fill:#4a90d9,stroke:#333,color:#fff
    style O4 fill:#4a90d9,stroke:#333,color:#fff
    style F1 fill:#8e44ad,stroke:#333,color:#fff
    style F2 fill:#8e44ad,stroke:#333,color:#fff
    style F3 fill:#8e44ad,stroke:#333,color:#fff
    style F4 fill:#8e44ad,stroke:#333,color:#fff
```

**Critical rule:** Agents (workers) should NOT call `bd update` or `bd close` directly. The orchestrator and finalization pipeline own all lifecycle transitions. See `AGENTS.md` for details.

## Known Race: Close Propagation Delay

After `bd close`, the beads daemon has a ~30s debounce before the closure propagates. If the poll loop runs before propagation completes, it may see the item as still `in_progress` and re-schedule it.

```mermaid
sequenceDiagram
    participant W as Worker-2
    participant BD as Beads DB
    participant Poll as Poll Loop
    participant W2 as Worker-4

    W->>BD: bd close tplpj ✓
    Note over BD: Daemon debounce ~30s...<br/>Close not yet propagated

    Poll->>BD: bd ready --json (poll #64)
    BD-->>Poll: tplpj still shows in_progress!
    Poll->>W2: Resume tplpj (redundant!)

    Note over BD: ~2min later...<br/>Close propagates
    Poll->>BD: bd ready --json (poll #67)
    BD-->>Poll: tplpj gone ✓

    Note over W2: Worker-4 did redundant work<br/>on already-merged branch
```

**Mitigation (fixed):** Removed the `get_in_progress_items()` call from the poll loop entirely (PokePoke-jcdl0). The poll loop now only dispatches items from `bd ready`. Crash recovery for orphaned in-progress items from dead sessions is handled once at startup by `recover_stale_items_for_orchestrator()`.

## Key Files

| Purpose | File |
|---------|------|
| Poll loop & dispatch | `src/pokepoke/orchestrator.py` |
| Single-item workflow | `src/pokepoke/workflow.py` |
| Parallel dispatch | `src/pokepoke/agents/parallel.py` |
| Item claim & close | `src/pokepoke/beads/beads_management.py` |
| Item query (bd ready) | `src/pokepoke/beads/beads_query.py` |
| Lock coordination | `src/pokepoke/worktrees/coordination.py` |
| Worktree creation | `src/pokepoke/worktrees/worktrees.py` |
| Merge pipeline | `src/pokepoke/worktrees/worktree_merge_handler.py` |
| Finalization | `src/pokepoke/worktrees/worktree_finalization.py` |
| Merge details | [merge-workflow.md](merge-workflow.md) |
