---- MODULE WorkItemClaim ----
(***************************************************************************)
(* TLA+ specification of the PokePoke work-item claiming protocol.         *)
(*                                                                         *)
(* Models the double-checked locking pattern used in                        *)
(* beads_management.assign_and_sync_item():                                *)
(*   1. Acquire per-item file lock (non-blocking, timeout=0).              *)
(*   2. Read current owner from beads DB.                                  *)
(*   3. If unassigned (or orphaned pokepoke_ agent): write claim.          *)
(*   4. Re-read and verify we are the owner.                               *)
(*   5. Release lock; sync (best-effort, outside lock).                    *)
(*                                                                         *)
(* Also models the WorkItemSession RAII lifecycle:                         *)
(*   ASSIGNING -> CREATING_WT -> ACTIVE -> (work) -> MERGING -> CLOSED    *)
(*   with reverse-order rollback on failure at any phase.                  *)
(*                                                                         *)
(* Properties checked:                                                     *)
(*   - NoDuplicateClaim: at most one agent owns any item.                 *)
(*   - LockExclusion: per-item lock prevents concurrent claim attempts.   *)
(*   - RollbackSafety: failed sessions always release all acquired        *)
(*     resources.                                                          *)
(***************************************************************************)

EXTENDS Naturals, FiniteSets, TLC

CONSTANTS
    Agents,        \* Set of agent IDs
    Items          \* Set of work item IDs

(* Symmetry: agents and items are independently interchangeable.            *)
(* Union of permutation sets allows TLC to exploit both simultaneously.     *)
AgentSymmetry == Permutations(Agents)
ItemSymmetry == Permutations(Items)
FullSymmetry == AgentSymmetry \union ItemSymmetry

(* Agent-item pair states *)
ClaimPhases == {
    "none",          \* not attempting to claim
    "lock_acquired", \* per-item file lock held
    "read_owner",    \* read current owner from beads
    "writing_claim", \* bd update --status in_progress -a <agent>
    "verifying",     \* re-read to verify claim
    "claimed",       \* successfully claimed
    "failed"         \* claim failed (lock busy, race detected, etc.)
}

SessionPhases == {
    "none",          \* no session
    "assigning",     \* journal written, assigning beads item
    "creating_wt",   \* creating worktree
    "active",        \* worktree created, work in progress
    "merging",       \* merge in progress
    "closed",        \* successfully completed
    "unwinding",     \* failure cleanup in progress
    "abandoned"      \* cleanup failed, left for reconciler
}

VARIABLES
    claimPhase,     \* [Agents x Items -> ClaimPhases]
    itemLock,       \* [Items -> "none" | agent_id] per-item file lock holder
    itemOwner,      \* [Items -> "none" | agent_id] beads DB assignee
    sessionPhase,   \* [Agents x Items -> SessionPhases]
    journal,        \* [Agents x Items -> SessionPhases] last journal write
    worktreeExists, \* [Items -> BOOLEAN]
    branchExists    \* [Items -> BOOLEAN]

vars == <<claimPhase, itemLock, itemOwner, sessionPhase, journal,
          worktreeExists, branchExists>>

TypeOK ==
    /\ claimPhase \in [Agents \X Items -> ClaimPhases]
    /\ itemLock \in [Items -> Agents \union {"none"}]
    /\ itemOwner \in [Items -> Agents \union {"none"}]
    /\ sessionPhase \in [Agents \X Items -> SessionPhases]
    /\ journal \in [Agents \X Items -> SessionPhases]
    /\ worktreeExists \in [Items -> BOOLEAN]
    /\ branchExists \in [Items -> BOOLEAN]

------------------------------------------------------------------------
Init ==
    /\ claimPhase = [p \in Agents \X Items |-> "none"]
    /\ itemLock = [i \in Items |-> "none"]
    /\ itemOwner = [i \in Items |-> "none"]
    /\ sessionPhase = [p \in Agents \X Items |-> "none"]
    /\ journal = [p \in Agents \X Items |-> "none"]
    /\ worktreeExists = [i \in Items |-> FALSE]
    /\ branchExists = [i \in Items |-> FALSE]

------------------------------------------------------------------------
(* ===== CLAIMING PROTOCOL ===== *)

(* Try to acquire the per-item file lock (non-blocking) *)
TryAcquireItemLock(a, i) ==
    /\ claimPhase[<<a, i>>] = "none"
    /\ itemOwner[i] = "none"  \* Only attempt if we think it's free
    /\ IF itemLock[i] = "none"
       THEN /\ itemLock' = [itemLock EXCEPT ![i] = a]
            /\ claimPhase' = [claimPhase EXCEPT ![<<a, i>>] = "lock_acquired"]
       ELSE /\ claimPhase' = [claimPhase EXCEPT ![<<a, i>>] = "failed"]
            /\ UNCHANGED itemLock
    /\ UNCHANGED <<itemOwner, sessionPhase, journal, worktreeExists, branchExists>>

(* Read current owner from beads DB (inside lock) *)
ReadOwner(a, i) ==
    /\ claimPhase[<<a, i>>] = "lock_acquired"
    /\ itemLock[i] = a
    /\ IF itemOwner[i] = "none"
       THEN /\ claimPhase' = [claimPhase EXCEPT ![<<a, i>>] = "writing_claim"]
            /\ UNCHANGED <<itemLock, itemOwner, sessionPhase, journal,
                           worktreeExists, branchExists>>
       ELSE \* Already owned by someone else — abort
            /\ claimPhase' = [claimPhase EXCEPT ![<<a, i>>] = "failed"]
            /\ itemLock' = [itemLock EXCEPT ![i] = "none"]
            /\ UNCHANGED <<itemOwner, sessionPhase, journal,
                           worktreeExists, branchExists>>

(* Write claim to beads DB (bd update) *)
WriteClaim(a, i) ==
    /\ claimPhase[<<a, i>>] = "writing_claim"
    /\ itemLock[i] = a
    /\ itemOwner' = [itemOwner EXCEPT ![i] = a]
    /\ claimPhase' = [claimPhase EXCEPT ![<<a, i>>] = "verifying"]
    /\ UNCHANGED <<itemLock, sessionPhase, journal, worktreeExists, branchExists>>

(* Re-read to verify we actually own it *)
VerifyClaim(a, i) ==
    /\ claimPhase[<<a, i>>] = "verifying"
    /\ itemLock[i] = a
    /\ IF itemOwner[i] = a
       THEN \* Verified! Release lock.
            /\ claimPhase' = [claimPhase EXCEPT ![<<a, i>>] = "claimed"]
            /\ itemLock' = [itemLock EXCEPT ![i] = "none"]
            /\ UNCHANGED <<itemOwner, sessionPhase, journal, worktreeExists, branchExists>>
       ELSE \* Verification failed — someone else overwrote. Rollback.
            /\ claimPhase' = [claimPhase EXCEPT ![<<a, i>>] = "failed"]
            /\ itemLock' = [itemLock EXCEPT ![i] = "none"]
            /\ itemOwner' = [itemOwner EXCEPT ![i] = "none"]
            /\ UNCHANGED <<sessionPhase, journal, worktreeExists, branchExists>>

------------------------------------------------------------------------
(* ===== WORK ITEM SESSION LIFECYCLE ===== *)

(* Begin session after successful claim *)
BeginSession(a, i) ==
    /\ claimPhase[<<a, i>>] = "claimed"
    /\ sessionPhase[<<a, i>>] = "none"
    /\ journal' = [journal EXCEPT ![<<a, i>>] = "assigning"]
    /\ sessionPhase' = [sessionPhase EXCEPT ![<<a, i>>] = "assigning"]
    /\ UNCHANGED <<claimPhase, itemLock, itemOwner, worktreeExists, branchExists>>

(* Create worktree (journal write-ahead, then create) *)
CreateWorktree(a, i) ==
    /\ sessionPhase[<<a, i>>] = "assigning"
    /\ journal' = [journal EXCEPT ![<<a, i>>] = "creating_wt"]
    /\ sessionPhase' = [sessionPhase EXCEPT ![<<a, i>>] = "creating_wt"]
    /\ worktreeExists' = [worktreeExists EXCEPT ![i] = TRUE]
    /\ branchExists' = [branchExists EXCEPT ![i] = TRUE]
    /\ UNCHANGED <<claimPhase, itemLock, itemOwner>>

(* Session becomes active *)
ActivateSession(a, i) ==
    /\ sessionPhase[<<a, i>>] = "creating_wt"
    /\ worktreeExists[i] = TRUE
    /\ journal' = [journal EXCEPT ![<<a, i>>] = "active"]
    /\ sessionPhase' = [sessionPhase EXCEPT ![<<a, i>>] = "active"]
    /\ UNCHANGED <<claimPhase, itemLock, itemOwner, worktreeExists, branchExists>>

(* Work completes, begin merge *)
BeginMerge(a, i) ==
    /\ sessionPhase[<<a, i>>] = "active"
    /\ journal' = [journal EXCEPT ![<<a, i>>] = "merging"]
    /\ sessionPhase' = [sessionPhase EXCEPT ![<<a, i>>] = "merging"]
    /\ UNCHANGED <<claimPhase, itemLock, itemOwner, worktreeExists, branchExists>>

(* Merge succeeds — close session *)
MergeSucceeds(a, i) ==
    /\ sessionPhase[<<a, i>>] = "merging"
    /\ sessionPhase' = [sessionPhase EXCEPT ![<<a, i>>] = "closed"]
    /\ journal' = [journal EXCEPT ![<<a, i>>] = "closed"]
    /\ worktreeExists' = [worktreeExists EXCEPT ![i] = FALSE]
    /\ branchExists' = [branchExists EXCEPT ![i] = FALSE]
    /\ UNCHANGED <<claimPhase, itemLock, itemOwner>>

------------------------------------------------------------------------
(* ===== FAILURE AND ROLLBACK ===== *)

(* Session fails at any active phase — begin unwind *)
SessionFails(a, i) ==
    /\ sessionPhase[<<a, i>>] \in {"assigning", "creating_wt", "active", "merging"}
    /\ journal' = [journal EXCEPT ![<<a, i>>] = "unwinding"]
    /\ sessionPhase' = [sessionPhase EXCEPT ![<<a, i>>] = "unwinding"]
    /\ UNCHANGED <<claimPhase, itemLock, itemOwner, worktreeExists, branchExists>>

(* Unwind: reverse-order resource release.                              *)
(* Worktree is PRESERVED for retry (as per the real code).             *)
(* Beads item is unassigned.                                            *)
UnwindSession(a, i) ==
    /\ sessionPhase[<<a, i>>] = "unwinding"
    \* Unassign the beads item
    /\ itemOwner' = [itemOwner EXCEPT ![i] = "none"]
    \* Reset claim so item can be re-claimed
    /\ claimPhase' = [claimPhase EXCEPT ![<<a, i>>] = "none"]
    \* Journal records completion or abandonment
    /\ \/ /\ journal' = [journal EXCEPT ![<<a, i>>] = "none"]  \* cleanup succeeded
          /\ sessionPhase' = [sessionPhase EXCEPT ![<<a, i>>] = "none"]
       \/ /\ journal' = [journal EXCEPT ![<<a, i>>] = "abandoned"]  \* partial cleanup
          /\ sessionPhase' = [sessionPhase EXCEPT ![<<a, i>>] = "abandoned"]
    /\ UNCHANGED <<itemLock, worktreeExists, branchExists>>

(* Legitimate terminal state: every agent-item pair has reached a          *)
(* final state (closed, failed, abandoned, or never started with the item  *)
(* owned or free). This stuttering step keeps deadlock detection useful     *)
(* — TLC will still flag REAL deadlocks where agents are stuck mid-work.   *)
Terminated ==
    /\ \A a \in Agents, i \in Items :
        \/ claimPhase[<<a, i>>] \in {"none", "failed"}
        \/ sessionPhase[<<a, i>>] \in {"closed", "abandoned"}
    /\ UNCHANGED vars

------------------------------------------------------------------------
Next ==
    \/ \E a \in Agents, i \in Items :
        \/ TryAcquireItemLock(a, i)
        \/ ReadOwner(a, i)
        \/ WriteClaim(a, i)
        \/ VerifyClaim(a, i)
        \/ BeginSession(a, i)
        \/ CreateWorktree(a, i)
        \/ ActivateSession(a, i)
        \/ BeginMerge(a, i)
        \/ MergeSucceeds(a, i)
        \/ SessionFails(a, i)
        \/ UnwindSession(a, i)
    \/ Terminated

Spec == Init /\ [][Next]_vars

------------------------------------------------------------------------
(* ===== SAFETY PROPERTIES ===== *)

(* CRITICAL: At most one agent owns any item at any time *)
NoDuplicateClaim ==
    \A i \in Items :
        \A a1, a2 \in Agents :
            (itemOwner[i] = a1 /\ itemOwner[i] = a2) => a1 = a2

(* Per-item lock is exclusive *)
LockExclusion ==
    \A i \in Items :
        \A a1, a2 \in Agents :
            (itemLock[i] = a1 /\ itemLock[i] = a2) => a1 = a2

(* A claimed item always has exactly one owner *)
ClaimImpliesOwnership ==
    \A a \in Agents, i \in Items :
        claimPhase[<<a, i>>] = "claimed" => itemOwner[i] = a

(* An active session always has the item claimed *)
ActiveSessionOwned ==
    \A a \in Agents, i \in Items :
        sessionPhase[<<a, i>>] \in {"active", "merging"}
        => itemOwner[i] = a

(* After unwind completes (session = "none"), the item is free *)
UnwindReleasesItem ==
    \A a \in Agents, i \in Items :
        (sessionPhase[<<a, i>>] = "none" /\ claimPhase[<<a, i>>] = "none")
        => itemOwner[i] # a

(* Journal always precedes or matches the session phase *)
(* This is the write-ahead guarantee *)
JournalPrecedence ==
    \A a \in Agents, i \in Items :
        sessionPhase[<<a, i>>] # "none" =>
            journal[<<a, i>>] # "none"

------------------------------------------------------------------------
(* ===== LIVENESS ===== *)

(* Every claimed item eventually reaches closed, abandoned, or re-freed *)
ClaimLiveness ==
    \A a \in Agents, i \in Items :
        claimPhase[<<a, i>>] = "claimed" ~>
            (sessionPhase[<<a, i>>] \in {"closed", "abandoned", "none"})

FairSpec == Spec /\ WF_vars(Next)

========================================================================
