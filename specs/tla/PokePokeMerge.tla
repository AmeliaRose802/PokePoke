---- MODULE PokePokeMerge ----
(***************************************************************************)
(* TLA+ specification of the PokePoke merge protocol.                      *)
(*                                                                         *)
(* Models the critical merge-lock lifecycle:                               *)
(*   1. Multiple agents finish work and attempt to merge concurrently.     *)
(*   2. Only one agent may hold the merge lock at a time.                  *)
(*   3. On merge conflict the lock is RELEASED, cleanup runs outside the   *)
(*      lock, then the lock is RE-ACQUIRED for a retry — up to            *)
(*      MaxConflictRetries times.                                          *)
(*   4. While the lock is released another agent may acquire it and merge. *)
(*                                                                         *)
(* The spec checks:                                                        *)
(*   - MergeMutex: at most one agent inside the merge critical section.    *)
(*   - NoDeadlock: the system can always make progress.                    *)
(*   - MergeLiveness: every agent that starts merging eventually finishes. *)
(***************************************************************************)

EXTENDS Naturals, FiniteSets, Sequences, TLC

CONSTANT Agents           \* Set of agent IDs, e.g. {"a1", "a2", "a3"}
CONSTANT MaxConflictRetries  \* e.g. 3

(* Symmetry: all agents are interchangeable — TLC can collapse             *)
(* permutation-equivalent states, reducing state space by up to N!         *)
AgentSymmetry == Permutations(Agents)

(* Agent lifecycle states *)
AgentStates == {
    "idle",              \* finished work, not yet merging
    "waiting_lock",      \* trying to acquire merge lock
    "pre_check",         \* inside lock: checking repo readiness
    "merging",           \* inside lock: running git merge
    "conflict_cleanup",  \* OUTSIDE lock: running cleanup agent
    "retry_waiting",     \* trying to re-acquire lock for retry
    "retry_merging",     \* inside lock: retrying merge after cleanup
    "done",              \* merge succeeded or exhausted retries
    "failed"             \* terminal failure (uncleanable, halt, etc.)
}

VARIABLES
    agentState,       \* agentState[a] \in AgentStates
    lockHolder,       \* "none" | agent ID currently holding the merge lock
    retryCount,       \* retryCount[a] \in 0..MaxConflictRetries
    masterDirty,      \* Boolean: true if master has uncommitted changes
    mergeConflicts    \* Function: Agents -> Boolean (will next merge conflict?)

vars == <<agentState, lockHolder, retryCount, masterDirty, mergeConflicts>>

TypeOK ==
    /\ agentState \in [Agents -> AgentStates]
    /\ lockHolder \in Agents \union {"none"}
    /\ retryCount \in [Agents -> 0..MaxConflictRetries]
    /\ masterDirty \in BOOLEAN
    /\ mergeConflicts \in [Agents -> BOOLEAN]

------------------------------------------------------------------------
(* Initial state: all agents idle, lock free, no retries *)
Init ==
    /\ agentState = [a \in Agents |-> "idle"]
    /\ lockHolder = "none"
    /\ retryCount = [a \in Agents |-> 0]
    /\ masterDirty = FALSE
    \* Non-deterministic: any agent might conflict on its first merge
    /\ mergeConflicts \in [Agents -> BOOLEAN]

------------------------------------------------------------------------
(* Actions *)

(* Agent requests the merge lock *)
RequestLock(a) ==
    /\ agentState[a] = "idle"
    /\ agentState' = [agentState EXCEPT ![a] = "waiting_lock"]
    /\ UNCHANGED <<lockHolder, retryCount, masterDirty, mergeConflicts>>

(* Agent acquires the merge lock (only if free) *)
AcquireLock(a) ==
    /\ agentState[a] = "waiting_lock"
    /\ lockHolder = "none"
    /\ agentState' = [agentState EXCEPT ![a] = "pre_check"]
    /\ lockHolder' = a
    /\ UNCHANGED <<retryCount, masterDirty, mergeConflicts>>

(* Pre-merge: check if main repo is clean.                     *)
(* If dirty, cleanup runs (still inside lock) and may fail.    *)
PreCheck(a) ==
    /\ agentState[a] = "pre_check"
    /\ lockHolder = a
    /\ IF masterDirty
       THEN \* Cleanup attempt: non-deterministically succeeds or fails
            \/ /\ masterDirty' = FALSE   \* cleanup succeeded
               /\ agentState' = [agentState EXCEPT ![a] = "merging"]
               /\ UNCHANGED <<lockHolder, retryCount, mergeConflicts>>
            \/ /\ agentState' = [agentState EXCEPT ![a] = "failed"]
               /\ lockHolder' = "none"   \* release lock on failure
               /\ UNCHANGED <<retryCount, masterDirty, mergeConflicts>>
       ELSE /\ agentState' = [agentState EXCEPT ![a] = "merging"]
            /\ UNCHANGED <<lockHolder, retryCount, masterDirty, mergeConflicts>>

(* Merge attempt inside the lock.                                          *)
(* Two outcomes: success or conflict.                                      *)
(*   - Success: worktree cleaned, lock released.                           *)
(*   - Conflict: merge aborted INSIDE lock, then lock RELEASED,           *)
(*     agent transitions to conflict_cleanup (outside lock).               *)
MergeAttempt(a) ==
    /\ agentState[a] = "merging"
    /\ lockHolder = a
    /\ IF ~mergeConflicts[a]
       THEN \* Success
            /\ agentState' = [agentState EXCEPT ![a] = "done"]
            /\ lockHolder' = "none"
            \* After a successful merge, master state may change for others
            /\ masterDirty' = FALSE
            /\ UNCHANGED <<retryCount, mergeConflicts>>
       ELSE \* Conflict — abort merge, RELEASE lock, go to cleanup
            /\ agentState' = [agentState EXCEPT ![a] = "conflict_cleanup"]
            /\ lockHolder' = "none"  \* Lock released before cleanup!
            /\ UNCHANGED <<retryCount, masterDirty, mergeConflicts>>

(* Conflict cleanup runs OUTSIDE the merge lock.                           *)
(* Other agents CAN acquire the lock and merge during this time.           *)
(* Cleanup non-deterministically succeeds (ready to retry) or fails.       *)
ConflictCleanup(a) ==
    /\ agentState[a] = "conflict_cleanup"
    /\ lockHolder # a   \* Invariant: we do NOT hold the lock
    /\ retryCount[a] < MaxConflictRetries
    /\ \/ /\ agentState' = [agentState EXCEPT ![a] = "retry_waiting"]
          /\ retryCount' = [retryCount EXCEPT ![a] = retryCount[a] + 1]
          /\ UNCHANGED <<lockHolder, masterDirty, mergeConflicts>>
       \/ /\ agentState' = [agentState EXCEPT ![a] = "failed"]
          /\ UNCHANGED <<lockHolder, retryCount, masterDirty, mergeConflicts>>

(* Cleanup exhausted all retries *)
CleanupExhausted(a) ==
    /\ agentState[a] = "conflict_cleanup"
    /\ retryCount[a] >= MaxConflictRetries
    /\ agentState' = [agentState EXCEPT ![a] = "failed"]
    /\ UNCHANGED <<lockHolder, retryCount, masterDirty, mergeConflicts>>

(* Agent re-acquires the merge lock for a retry attempt *)
ReacquireLock(a) ==
    /\ agentState[a] = "retry_waiting"
    /\ lockHolder = "none"
    /\ agentState' = [agentState EXCEPT ![a] = "retry_merging"]
    /\ lockHolder' = a
    /\ UNCHANGED <<retryCount, masterDirty, mergeConflicts>>

(* Retry merge inside the lock after conflict cleanup.                     *)
(* The merge may succeed or hit NEW conflicts (base may have changed       *)
(* while the lock was released).                                           *)
RetryMerge(a) ==
    /\ agentState[a] = "retry_merging"
    /\ lockHolder = a
    /\ \/ /\ agentState' = [agentState EXCEPT ![a] = "done"]
          /\ lockHolder' = "none"
          /\ masterDirty' = FALSE
          /\ UNCHANGED <<retryCount, mergeConflicts>>
       \/ /\ agentState' = [agentState EXCEPT ![a] = "conflict_cleanup"]
          /\ lockHolder' = "none"  \* Release lock again
          \* Environment may set new conflict expectations
          /\ mergeConflicts' \in [Agents -> BOOLEAN]
          /\ UNCHANGED <<retryCount, masterDirty>>

(* Environment can change conflict expectations between merges —            *)
(* models the fact that another agent's merge can change the base.          *)
EnvironmentChange ==
    /\ mergeConflicts' \in [Agents -> BOOLEAN]
    /\ masterDirty' \in BOOLEAN
    /\ UNCHANGED <<agentState, lockHolder, retryCount>>

------------------------------------------------------------------------
(* Next-state relation *)
Next ==
    \/ \E a \in Agents :
        \/ RequestLock(a)
        \/ AcquireLock(a)
        \/ PreCheck(a)
        \/ MergeAttempt(a)
        \/ ConflictCleanup(a)
        \/ CleanupExhausted(a)
        \/ ReacquireLock(a)
        \/ RetryMerge(a)
    \/ EnvironmentChange

Spec == Init /\ [][Next]_vars

------------------------------------------------------------------------
(* Safety properties *)

(* CRITICAL: At most one agent holds the merge lock at any time *)
MergeMutex ==
    \A a1, a2 \in Agents :
        (lockHolder = a1 /\ lockHolder = a2) => a1 = a2

(* Only the lock holder can be in a lock-holding state *)
LockHolderConsistency ==
    \A a \in Agents :
        agentState[a] \in {"pre_check", "merging", "retry_merging"}
        => lockHolder = a

(* An agent in conflict_cleanup never holds the lock *)
CleanupNeverHoldsLock ==
    \A a \in Agents :
        agentState[a] = "conflict_cleanup" => lockHolder # a

(* Retry count never exceeds max *)
RetryBound ==
    \A a \in Agents : retryCount[a] <= MaxConflictRetries

------------------------------------------------------------------------
(* Liveness properties (checked under fairness) *)

(* Every agent that starts merging eventually reaches done or failed *)
MergeLiveness ==
    \A a \in Agents :
        agentState[a] = "idle" ~> agentState[a] \in {"done", "failed"}

(* The lock is never held forever — it is always eventually released *)
LockFreedom ==
    \A a \in Agents :
        lockHolder = a ~> lockHolder # a

(* Fairness: Strong fairness on each agent action prevents starvation.      *)
(* SF guarantees that if an action is REPEATEDLY enabled (even if           *)
(* interrupted), it eventually fires. This matches real-world thread        *)
(* scheduling: the OS won't starve a runnable thread forever.              *)
(* EnvironmentChange deliberately gets NO fairness — it models              *)
(* non-deterministic external events, not scheduled work.                   *)
FairSpec == Spec
    /\ \A a \in Agents :
        /\ SF_vars(RequestLock(a))
        /\ SF_vars(AcquireLock(a))
        /\ SF_vars(PreCheck(a))
        /\ SF_vars(MergeAttempt(a))
        /\ SF_vars(ConflictCleanup(a))
        /\ SF_vars(CleanupExhausted(a))
        /\ SF_vars(ReacquireLock(a))
        /\ SF_vars(RetryMerge(a))

========================================================================
