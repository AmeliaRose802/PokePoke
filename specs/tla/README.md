# PokePoke TLA+ Specifications

Formal models of the PokePoke concurrency protocol. These specs let TLC
exhaustively check safety and liveness properties that are hard to verify
through testing alone.

## Specs

| File | What it models | Key properties |
|---|---|---|
| `PokePokeMerge.tla` | Merge lock lifecycle with conflict-retry release-and-reacquire | MergeMutex, LockHolderConsistency, MergeLiveness |
| `WorkItemClaim.tla` | Double-checked locking claim protocol + WorkItemSession RAII | NoDuplicateClaim, JournalPrecedence, ClaimLiveness |
| `StaleLockRecovery.tla` | Stale lock detection via meta-lock + session reconciler | NoDoubleBreak, LiveLockNeverBroken, CrashRecovery |

## Running

Install the [TLA+ tools](https://github.com/tlaplus/tlaplus/releases) or
use the VS Code [TLA+ extension](https://marketplace.visualstudio.com/items?itemName=alygin.vscode-tlaplus).

```bash
# Check safety invariants (fast — explores full state space)
tlc PokePokeMerge.tla -config PokePokeMerge.cfg

# Check with liveness (slower — needs fairness)
# Edit .cfg: change SPECIFICATION to FairSpec, uncomment PROPERTY lines
tlc PokePokeMerge.tla -config PokePokeMerge.cfg
```

Each `.cfg` file defines small constant sets (2-3 agents, 1-2 items) to
keep the state space tractable. Increase for deeper exploration at the
cost of runtime.

## What each spec maps to in the codebase

### PokePokeMerge

Maps to the merge protocol in:
- `src/pokepoke/worktrees/worktree_merge_handler.py` — `handle_worktree_merge()`, `perform_worktree_merge()`
- `src/pokepoke/worktrees/merge_conflict_retry.py` — `run_conflict_retry_loop()`
- `src/pokepoke/worktrees/coordination.py` — `merge_lock()`

**Key risk modeled:** The conflict retry loop releases the merge lock,
runs cleanup outside it, then reacquires. During that window another agent
can merge, changing the base. The spec verifies mutex is maintained and
every agent eventually terminates.

### WorkItemClaim

Maps to the claiming protocol in:
- `src/pokepoke/beads/beads_management.py` — `assign_and_sync_item()`
- `src/pokepoke/orchestration/work_item_session.py` — `WorkItemSession`
- `src/pokepoke/stats/session_journal.py` — write-ahead journal

**Key risk modeled:** Two agents racing to claim the same item. The spec
verifies the per-item lock + read-write-verify sequence prevents double
claiming, and that session rollback always frees resources.

### StaleLockRecovery

Maps to the crash recovery mechanisms in:
- `src/pokepoke/worktrees/coordination.py` — `_break_stale_lock_if_needed()`, meta-lock
- `src/pokepoke/stats/session_journal.py` — `SessionReconciler` (startup recovery)

**Key risk modeled:** Two processes simultaneously detecting the same stale
lock. The meta-lock serializes the check-and-break operation. The spec
verifies no live process's lock is incorrectly broken, and that crashed
sessions are eventually cleaned up.

## Interpreting TLC output

- **No errors:** TLC explored the full state space and all invariants/properties hold.
- **Invariant violation:** TLC prints a counterexample trace showing the exact sequence of steps that breaks the property. Map each step back to the corresponding action in the codebase.
- **Deadlock:** TLC found a state where no action is enabled. This may indicate a real deadlock or a terminal state that needs a stuttering step.
- **Liveness violation:** TLC found an infinite execution that violates a temporal property (e.g., an agent that never finishes merging).

## Extending the specs

To model a new protocol aspect:
1. Add new variables and actions to the relevant `.tla` file.
2. Add invariants (safety) or temporal properties (liveness).
3. Run TLC with small constants first to validate quickly.
4. Increase constants to explore deeper state spaces.
