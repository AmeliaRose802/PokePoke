# Merge Workflow

Visual diagrams of PokePoke's worktree merge pipeline — how completed agent work gets merged back to the target branch.

## General Merge Flow (End-to-End)

The full sequence from "agent work complete" to "worktree cleaned up", including lock acquisition, validation, and rollback. PokePoke only performs local merges — the user decides when to push.

**Color key:**
- 🟦 Blue = **holding merge lock** (serialized, one agent at a time)
- ⬜ Default = **no lock held** (pre-lock or post-release)
- 🟥 Red = **failure exit** (lock released on exit)
- 🟩 Green = **success terminal**

```mermaid
flowchart TD
    START(["0. Agent work complete"]) --> WT_CHECK{"4. Worktree<br/>clean?<br/>(pre-lock)"}

    WT_CHECK -- "Uncommitted changes" --> FAIL_WT(["FAIL — worktree<br/>not cleaned up<br/>(no lock acquired)"])
    WT_CHECK -- Clean --> COMMIT_COUNT{"5. Commits on<br/>branch?<br/>(pre-lock)"}

    COMMIT_COUNT -- "0 commits" --> SKIP_MERGE["5a. Skip merge<br/>cleanup worktree force=True<br/>(no lock needed)"]
    COMMIT_COUNT -- "≥1 commit" --> LOCK["1. Acquire merge lock<br/>600s timeout, 15min stale detection"]

    LOCK --> MAIN_CHECK{"2. Main repo<br/>clean?"}

    MAIN_CHECK -- "Only .beads/ changes" --> AUTO_BEADS["3a. Auto-commit .beads/<br/>git add .beads/ && git commit"]
    MAIN_CHECK -- "Clean" --> SYNC
    MAIN_CHECK -- "Non-beads dirty files" --> CLEANUP_AGENT["3b. Invoke cleanup agent<br/>autonomous mode"]

    AUTO_BEADS --> SYNC

    CLEANUP_AGENT --> RECHECK{"3c. Main repo<br/>clean now?"}
    RECHECK -- Yes --> SYNC
    RECHECK -- No --> FAIL_DIRTY(["FAIL — add to<br/>uncleaned manifest"])

    SYNC["6. Sync & prepare main<br/>bd sync + commit stragglers"] --> CHECKOUT["7. git checkout target_branch"]
    CHECKOUT --> MERGE["8. git merge --no-ff branch_name"]

    MERGE -- Success --> VALIDATE["9. Post-merge validation<br/>correct branch? clean status?"]
    MERGE -- Conflict --> CONFLICT_FLOW[["Handle conflicts<br/>see Conflict Handling below"]]

    VALIDATE -- Pass --> CLEANUP_WT["10. git worktree remove --force<br/>git branch -D branch_name"]
    VALIDATE -- Fail --> ROLLBACK_V["git reset --hard HEAD~1"]

    CLEANUP_WT --> RELEASE(["11. Release merge lock<br/>DONE"])

    ROLLBACK_V --> FAIL_MERGE(["FAIL — rollback applied"])
    SKIP_MERGE --> RELEASE_NOLOCK(["11. DONE<br/>(no merge needed)"])

    %% Lock held (blue) — steps 1–11 under lock
    style LOCK fill:#4a90d9,stroke:#333,color:#fff
    style MAIN_CHECK fill:#4a90d9,stroke:#333,color:#fff
    style AUTO_BEADS fill:#4a90d9,stroke:#333,color:#fff
    style CLEANUP_AGENT fill:#4a90d9,stroke:#333,color:#fff
    style RECHECK fill:#4a90d9,stroke:#333,color:#fff
    style SYNC fill:#4a90d9,stroke:#333,color:#fff
    style CHECKOUT fill:#4a90d9,stroke:#333,color:#fff
    style MERGE fill:#4a90d9,stroke:#333,color:#fff
    style CONFLICT_FLOW fill:#4a90d9,stroke:#333,color:#fff
    style VALIDATE fill:#4a90d9,stroke:#333,color:#fff
    style CLEANUP_WT fill:#4a90d9,stroke:#333,color:#fff

    %% Failure exits (red) — lock released on exit
    style FAIL_DIRTY fill:#e74c3c,stroke:#333,color:#fff
    style FAIL_WT fill:#e74c3c,stroke:#333,color:#fff
    style FAIL_MERGE fill:#e74c3c,stroke:#333,color:#fff
    style ROLLBACK_V fill:#e74c3c,stroke:#333,color:#fff

    %% Success terminal (green)
    style RELEASE fill:#27ae60,stroke:#333,color:#fff
    style RELEASE_NOLOCK fill:#27ae60,stroke:#333,color:#fff
```

Steps 4, 5, and 5a run **before** lock acquisition — they are read-only operations on the worktree (isolated per-agent, no shared state). Dirty worktrees and empty branches fail/skip fast without blocking the merge queue. Steps 1–11 (blue) execute under the lock. PokePoke does not push to remote — the user decides when to `git push`.

## Uncommitted Files on Worktree

What happens when the agent's worktree has uncommitted changes at merge time. This check runs **before lock acquisition** (step 4 in the general flow) — dirty worktrees fail fast without blocking the merge queue.

```mermaid
flowchart TD
    START(["Step 4 — pre-lock"]) --> CHECK["4a. is_worktree_clean<br/>git -C worktree status --porcelain"]

    CHECK -- "Empty output = clean" --> PROCEED(["Continue to step 5"])
    CHECK -- "Non-empty output = dirty" --> CATEGORIZE["4b. Worktree has<br/>uncommitted changes"]

    CATEGORIZE --> RESULT["4c. Return (False, False)<br/>merge lock never acquired"]
    RESULT --> PRESERVE["4d. Worktree is NOT<br/>auto-cleaned up"]
    PRESERVE --> MANIFEST["4e. Added to uncleaned manifest<br/>.pokepoke/uncleaned_worktrees.json"]
    MANIFEST --> NEXT(["Other agents continue<br/>merge queue unblocked"])

    NEXT --> MAINT["Maintenance cycle<br/>may retry later"]

    %% Pre-lock (no blue — lock not held)
    style CATEGORIZE fill:#e74c3c,stroke:#333,color:#fff
    style RESULT fill:#e74c3c,stroke:#333,color:#fff
    style PRESERVE fill:#e74c3c,stroke:#333,color:#fff
    style MANIFEST fill:#e74c3c,stroke:#333,color:#fff
    style PROCEED fill:#27ae60,stroke:#333,color:#fff
```

The worktree is preserved for manual intervention or a future maintenance pass.

## Uncommitted Files on Main Repo

What happens when the main repository has uncommitted changes before a merge begins. This corresponds to **step 2** in the general flow.

```mermaid
flowchart TD
    START(["Step 2 — lock held"]) --> STATUS["2a. git status --porcelain<br/>on main repo"]

    STATUS --> CATEGORIZE["2b. Categorize changes:<br/>beads / worktree / untracked / other"]

    CATEGORIZE --> DECISION{"2c. What type<br/>of changes?"}

    DECISION -- "Only .beads/ files" --> BEADS_COMMIT["3a. Auto-commit beads<br/>git add .beads/<br/>git commit"]
    BEADS_COMMIT --> OK(["Main repo clean<br/>proceed to step 6"])

    DECISION -- "Only worktrees/ dirs" --> WT_COMMIT["3a′. Auto-commit worktree cleanup<br/>git add worktrees/<br/>git commit"]
    WT_COMMIT --> OK

    DECISION -- "Other / mixed changes" --> CLEANUP["3b. Invoke cleanup agent<br/>loads cleanup.md prompt<br/>runs autonomous with timeout"]

    CLEANUP -- "Agent succeeds" --> RECHECK["3c. Re-run<br/>check_main_repo_ready_for_merge"]
    RECHECK -- Clean --> OK
    RECHECK -- Still dirty --> ABORT(["FAIL — abort merge<br/>preserve worktree<br/>add to uncleaned manifest"])

    CLEANUP -- "Agent fails / timeout" --> ABORT

    DECISION -- "Clean" --> OK

    %% Lock held (blue)
    style STATUS fill:#4a90d9,stroke:#333,color:#fff
    style CATEGORIZE fill:#4a90d9,stroke:#333,color:#fff
    style DECISION fill:#4a90d9,stroke:#333,color:#fff
    style BEADS_COMMIT fill:#4a90d9,stroke:#333,color:#fff
    style WT_COMMIT fill:#4a90d9,stroke:#333,color:#fff
    style CLEANUP fill:#4a90d9,stroke:#333,color:#fff
    style RECHECK fill:#4a90d9,stroke:#333,color:#fff

    %% Terminals
    style ABORT fill:#e74c3c,stroke:#333,color:#fff
    style OK fill:#27ae60,stroke:#333,color:#fff
```

Known-safe changes (`.beads/`, `worktrees/`) are auto-committed. Everything else triggers a cleanup agent.

## Merge Conflict Handling

How conflicts are detected, auto-resolved where possible, and escalated to a cleanup agent when not. This is the detail for **step 8** (conflict branch) in the general flow.

```mermaid
flowchart TD
    MERGE["8. git merge --no-ff branch_name"] -- "Exit code ≠ 0" --> DETECT["8a. Detect conflict state"]

    DETECT --> CHECK_HEAD{"8b. MERGE_HEAD<br/>file exists?"}
    CHECK_HEAD -- No --> GENERIC_FAIL(["Generic merge failure<br/>not a conflict"])
    CHECK_HEAD -- Yes --> PARSE["8c. Parse git status --porcelain<br/>for conflict markers"]

    PARSE --> TYPES["8d. Identify conflict types:<br/>UU = both modified<br/>AA = both added<br/>DD = both deleted<br/>AU/UA = add vs modify<br/>DU/UD = delete vs modify"]

    TYPES --> POKEPOKE_CHECK{"8e. All conflicts<br/>in .pokepoke/ only?"}

    POKEPOKE_CHECK -- Yes --> AUTO_RESOLVE["8f. Auto-resolve .pokepoke/<br/>git checkout --ours -- file<br/>git add -- file"]
    AUTO_RESOLVE --> COMMIT_MERGE["8g. git commit --no-edit<br/>complete merge"]
    COMMIT_MERGE --> SUCCESS(["Merge succeeded<br/>continue to step 9"])

    POKEPOKE_CHECK -- No --> PARTIAL_AUTO["8h. Auto-resolve .pokepoke/<br/>conflicts if any"]
    PARTIAL_AUTO --> ABORT_MERGE["8i. git merge --abort<br/>rollback to pre-merge state"]

    ABORT_MERGE --> INVOKE_AGENT["8j. Invoke merge conflict<br/>cleanup agent with:<br/>conflicted file list<br/>merge error details<br/>conflict count"]

    INVOKE_AGENT -- "Agent fixes conflicts" --> RETRY["8k. Retry merge_worktree<br/>cleanup=True"]
    RETRY -- Success --> SUCCESS
    RETRY -- Fails again --> FINAL_ABORT["8l. git merge --abort again"]

    INVOKE_AGENT -- "Agent fails / timeout" --> FINAL_ABORT

    FINAL_ABORT --> UNCLEANED["8m. Add to uncleaned<br/>worktree manifest"]
    UNCLEANED --> FAIL(["FAIL — worktree<br/>preserved for<br/>manual intervention"])

    %% Lock held throughout (blue)
    style MERGE fill:#4a90d9,stroke:#333,color:#fff
    style DETECT fill:#4a90d9,stroke:#333,color:#fff
    style CHECK_HEAD fill:#4a90d9,stroke:#333,color:#fff
    style PARSE fill:#4a90d9,stroke:#333,color:#fff
    style TYPES fill:#4a90d9,stroke:#333,color:#fff
    style POKEPOKE_CHECK fill:#4a90d9,stroke:#333,color:#fff
    style PARTIAL_AUTO fill:#4a90d9,stroke:#333,color:#fff
    style ABORT_MERGE fill:#4a90d9,stroke:#333,color:#fff
    style INVOKE_AGENT fill:#4a90d9,stroke:#333,color:#fff
    style RETRY fill:#4a90d9,stroke:#333,color:#fff
    style FINAL_ABORT fill:#4a90d9,stroke:#333,color:#fff
    style UNCLEANED fill:#4a90d9,stroke:#333,color:#fff

    %% Auto-resolve (yellow)
    style AUTO_RESOLVE fill:#f1c40f,stroke:#333,color:#333
    style COMMIT_MERGE fill:#f1c40f,stroke:#333,color:#333

    %% Terminals
    style SUCCESS fill:#27ae60,stroke:#333,color:#fff
    style FAIL fill:#e74c3c,stroke:#333,color:#fff
    style GENERIC_FAIL fill:#e74c3c,stroke:#333,color:#fff
```

`.pokepoke/` conflicts (yellow) are always auto-resolved with "ours" strategy since the orchestrator regenerates those files. All other steps (blue) execute under the merge lock.

## Retry and Rollback Summary

```mermaid
flowchart LR
    subgraph "Retry Strategies"
        B[Git Status] -->|"3 retries<br/>0.5s, 1s, 2s"| B1[index.lock recovery]
        C[Beads Sync] -->|"3 retries"| C1[Pre-merge sync]
        D[Merge Conflicts] -->|"1 retry"| D1[Cleanup agent + re-merge]
        E[Main Repo Dirty] -->|"1 retry"| E1[Cleanup agent + re-check]
    end

    subgraph "Rollback Actions"
        R1[Post-merge validation fail] --> R1a[git reset --hard HEAD~1]
        R3[Merge conflict] --> R3a[git merge --abort]
    end
```

## Key Files

| Purpose | File |
|---------|------|
| Worktree merge | `src/pokepoke/worktrees/worktrees.py` |
| Finalization | `src/pokepoke/worktrees/worktree_finalization.py` |
| Merge handler | `src/pokepoke/worktrees/worktree_merge_handler.py` |
| Helpers | `src/pokepoke/worktrees/worktree_helpers.py` |
| Merge execution | `src/pokepoke/git/git_operations.py` |
| Conflict detection | `src/pokepoke/git/merge_conflict.py` |
| Cleanup agents | `src/pokepoke/agents/cleanup_agents.py` |
| Lock coordination | `src/pokepoke/worktrees/coordination.py` |
