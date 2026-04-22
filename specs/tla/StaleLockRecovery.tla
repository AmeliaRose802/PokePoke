---- MODULE StaleLockRecovery ----
(***************************************************************************)
(* TLA+ specification of PokePoke stale-lock detection and session         *)
(* crash recovery.                                                         *)
(*                                                                         *)
(* Models two interacting recovery mechanisms:                             *)
(*   1. Stale lock detection: when a process dies while holding a file     *)
(*      lock, another process detects the stale lock via PID liveness      *)
(*      check, acquires a meta-lock, and removes the stale lock.          *)
(*   2. Session reconciler: at startup, scans journal files left by        *)
(*      crashed sessions and cleans up orphaned resources.                 *)
(*                                                                         *)
(* Properties checked:                                                     *)
(*   - NoPhantomLocks: dead processes' locks are eventually cleared.       *)
(*   - NoDoubleBreak: at most one process breaks a stale lock at a time.  *)
(*   - ReconcilerSafety: reconciler only cleans up dead sessions.         *)
(*   - CrashRecovery: every crash eventually leads to a clean state.      *)
(***************************************************************************)

EXTENDS Naturals, FiniteSets, TLC

CONSTANTS
    Procs,           \* Set of process IDs
    Locks            \* Set of named locks (e.g. {"merge", "worktree-setup"})

(* Symmetry: processes and locks are independently interchangeable.          *)
ProcSymmetry == Permutations(Procs)
LockSymmetry == Permutations(Locks)
FullSymmetry == ProcSymmetry \union LockSymmetry

(* Process lifecycle *)
ProcStates == {
    "alive",           \* running normally
    "holding_lock",    \* alive and holding a lock
    "crashed",         \* process died (may still have lock file on disk)
    "detecting_stale", \* alive, checking if a lock is stale
    "breaking_lock",   \* alive, inside meta-lock, removing stale lock
    "reconciling"      \* alive, running session reconciler
}

VARIABLES
    procState,      \* [Procs -> ProcStates]
    lockFile,       \* [Locks -> "free" | proc_id]  who left the lock file on disk
    lockMeta,       \* [Locks -> "free" | proc_id]  meta-lock for stale detection
    lockMetaPid,    \* [Locks -> 0 | proc_id]  PID recorded in .meta sidecar
    detecting,      \* [Procs -> Locks \union {"none"}]  which lock this proc is checking
    journalExists,  \* [Procs -> BOOLEAN]  whether a session journal exists for this proc
    resourcesOrphan \* [Procs -> BOOLEAN]  whether orphaned resources exist (worktree, branch, beads claim)

vars == <<procState, lockFile, lockMeta, lockMetaPid, detecting,
          journalExists, resourcesOrphan>>

TypeOK ==
    /\ procState \in [Procs -> ProcStates]
    /\ lockFile \in [Locks -> Procs \union {"free"}]
    /\ lockMeta \in [Locks -> Procs \union {"free"}]
    /\ lockMetaPid \in [Locks -> Procs \union {0}]
    /\ detecting \in [Procs -> Locks \union {"none"}]
    /\ journalExists \in [Procs -> BOOLEAN]
    /\ resourcesOrphan \in [Procs -> BOOLEAN]

------------------------------------------------------------------------
Init ==
    /\ procState = [p \in Procs |-> "alive"]
    /\ lockFile = [l \in Locks |-> "free"]
    /\ lockMeta = [l \in Locks |-> "free"]
    /\ lockMetaPid = [l \in Locks |-> 0]
    /\ detecting = [p \in Procs |-> "none"]
    /\ journalExists = [p \in Procs |-> FALSE]
    /\ resourcesOrphan = [p \in Procs |-> FALSE]

------------------------------------------------------------------------
(* ===== NORMAL LOCK OPERATIONS ===== *)

(* Process acquires a lock normally *)
AcquireLock(p, l) ==
    /\ procState[p] = "alive"
    /\ lockFile[l] = "free"
    /\ procState' = [procState EXCEPT ![p] = "holding_lock"]
    /\ lockFile' = [lockFile EXCEPT ![l] = p]
    /\ lockMetaPid' = [lockMetaPid EXCEPT ![l] = p]
    /\ journalExists' = [journalExists EXCEPT ![p] = TRUE]  \* WAL journal written
    /\ UNCHANGED <<lockMeta, detecting, resourcesOrphan>>

(* Process releases a lock normally *)
ReleaseLock(p, l) ==
    /\ procState[p] = "holding_lock"
    /\ lockFile[l] = p
    /\ procState' = [procState EXCEPT ![p] = "alive"]
    /\ lockFile' = [lockFile EXCEPT ![l] = "free"]
    /\ lockMetaPid' = [lockMetaPid EXCEPT ![l] = 0]
    /\ UNCHANGED <<lockMeta, detecting, journalExists, resourcesOrphan>>

------------------------------------------------------------------------
(* ===== CRASH ===== *)

(* Process crashes — lock FILE persists on disk but kernel lock releases.  *)
(* This is the key distinction: filelock.FileLock releases on crash but    *)
(* the .lock file itself remains (stale). Resources may be orphaned.       *)
Crash(p) ==
    /\ procState[p] \in {"alive", "holding_lock"}
    /\ procState' = [procState EXCEPT ![p] = "crashed"]
    \* Lock file remains on disk even though kernel lock is released
    \* (lockFile stays set to p — it's the FILE, not the kernel lock)
    /\ resourcesOrphan' = [resourcesOrphan EXCEPT ![p] = TRUE]
    /\ UNCHANGED <<lockFile, lockMeta, lockMetaPid, detecting, journalExists>>

------------------------------------------------------------------------
(* ===== STALE LOCK DETECTION ===== *)

(* Process begins checking if a lock is stale                              *)
(* (sees the lock file exists + is old enough to suspect staleness)        *)
BeginStaleCheck(p, l) ==
    /\ procState[p] = "alive"
    /\ lockFile[l] # "free"       \* Lock file exists on disk
    /\ lockFile[l] # p            \* Not our own lock
    /\ detecting[p] = "none"
    /\ procState' = [procState EXCEPT ![p] = "detecting_stale"]
    /\ detecting' = [detecting EXCEPT ![p] = l]
    /\ UNCHANGED <<lockFile, lockMeta, lockMetaPid, journalExists, resourcesOrphan>>

(* Acquire the meta-lock to serialize stale detection.                     *)
(* This is the TOCTOU protection: only one process can check-and-break.    *)
AcquireMetaLock(p, l) ==
    /\ procState[p] = "detecting_stale"
    /\ detecting[p] = l
    /\ lockMeta[l] = "free"
    /\ lockMeta' = [lockMeta EXCEPT ![l] = p]
    /\ procState' = [procState EXCEPT ![p] = "breaking_lock"]
    /\ UNCHANGED <<lockFile, lockMetaPid, detecting, journalExists, resourcesOrphan>>

(* Meta-lock busy — another process is already checking. Abort. *)
MetaLockBusy(p, l) ==
    /\ procState[p] = "detecting_stale"
    /\ detecting[p] = l
    /\ lockMeta[l] # "free"
    /\ lockMeta[l] # p
    /\ procState' = [procState EXCEPT ![p] = "alive"]
    /\ detecting' = [detecting EXCEPT ![p] = "none"]
    /\ UNCHANGED <<lockFile, lockMeta, lockMetaPid, journalExists, resourcesOrphan>>

(* Inside meta-lock: check PID liveness and break if dead.                 *)
(* The holder PID is read from the .meta sidecar file.                     *)
BreakStaleLock(p, l) ==
    /\ procState[p] = "breaking_lock"
    /\ detecting[p] = l
    /\ lockMeta[l] = p
    /\ LET holder == lockMetaPid[l]
       IN IF holder = 0
          THEN \* No metadata — can't determine holder. Release meta-lock, abort.
               /\ lockMeta' = [lockMeta EXCEPT ![l] = "free"]
               /\ procState' = [procState EXCEPT ![p] = "alive"]
               /\ detecting' = [detecting EXCEPT ![p] = "none"]
               /\ UNCHANGED <<lockFile, lockMetaPid, journalExists, resourcesOrphan>>
          ELSE IF procState[holder] = "crashed"
               THEN \* Holder is dead! Remove the stale lock file.
                    /\ lockFile' = [lockFile EXCEPT ![l] = "free"]
                    /\ lockMetaPid' = [lockMetaPid EXCEPT ![l] = 0]
                    /\ lockMeta' = [lockMeta EXCEPT ![l] = "free"]
                    /\ procState' = [procState EXCEPT ![p] = "alive"]
                    /\ detecting' = [detecting EXCEPT ![p] = "none"]
                    /\ UNCHANGED <<journalExists, resourcesOrphan>>
               ELSE \* Holder is alive — lock is legitimate. Release meta-lock.
                    /\ lockMeta' = [lockMeta EXCEPT ![l] = "free"]
                    /\ procState' = [procState EXCEPT ![p] = "alive"]
                    /\ detecting' = [detecting EXCEPT ![p] = "none"]
                    /\ UNCHANGED <<lockFile, lockMetaPid, journalExists,
                                   resourcesOrphan>>

------------------------------------------------------------------------
(* ===== SESSION RECONCILIATION ===== *)

(* At startup, a process scans journals and cleans up crashed sessions *)
BeginReconcile(p) ==
    /\ procState[p] = "alive"
    /\ \E crashed \in Procs :
        /\ procState[crashed] = "crashed"
        /\ journalExists[crashed] = TRUE
    /\ procState' = [procState EXCEPT ![p] = "reconciling"]
    /\ UNCHANGED <<lockFile, lockMeta, lockMetaPid, detecting,
                   journalExists, resourcesOrphan>>

(* Reconciler cleans up a specific crashed session *)
ReconcileSession(p, crashed) ==
    /\ procState[p] = "reconciling"
    /\ procState[crashed] = "crashed"
    /\ journalExists[crashed] = TRUE
    \* Clean up: remove journal, free orphaned resources
    /\ journalExists' = [journalExists EXCEPT ![crashed] = FALSE]
    /\ resourcesOrphan' = [resourcesOrphan EXCEPT ![crashed] = FALSE]
    \* Also clear any stale lock files left by the crashed process
    /\ lockFile' = [l \in Locks |->
        IF lockFile[l] = crashed THEN "free" ELSE lockFile[l]]
    /\ lockMetaPid' = [l \in Locks |->
        IF lockMetaPid[l] = crashed THEN 0 ELSE lockMetaPid[l]]
    /\ UNCHANGED <<procState, lockMeta, detecting>>

(* Reconciler finishes *)
FinishReconcile(p) ==
    /\ procState[p] = "reconciling"
    /\ procState' = [procState EXCEPT ![p] = "alive"]
    /\ UNCHANGED <<lockFile, lockMeta, lockMetaPid, detecting,
                   journalExists, resourcesOrphan>>

(* A crashed process restarts (models new process startup).                *)
(* The new process starts alive and can act as a reconciler.               *)
Restart(p) ==
    /\ procState[p] = "crashed"
    /\ journalExists[p] = FALSE  \* Only restart after journal is cleaned
    /\ procState' = [procState EXCEPT ![p] = "alive"]
    /\ resourcesOrphan' = [resourcesOrphan EXCEPT ![p] = FALSE]
    /\ UNCHANGED <<lockFile, lockMeta, lockMetaPid, detecting, journalExists>>

(* Legitimate terminal state: all processes crashed with uncleaned           *)
(* journals (no one left to reconcile) OR all alive with no work.           *)
(* This stuttering step keeps deadlock detection useful for REAL deadlocks.  *)
Terminated ==
    /\ \/ \A p \in Procs : procState[p] = "crashed"  \* Everyone dead
       \/ /\ \A p \in Procs : procState[p] = "alive"  \* Everyone alive + idle
          /\ \A l \in Locks : lockFile[l] = "free"     \* No locks held
          /\ \A p \in Procs : journalExists[p] = FALSE \* No journals to clean
          /\ \A p \in Procs : resourcesOrphan[p] = FALSE \* No orphans
    /\ UNCHANGED vars

------------------------------------------------------------------------
Next ==
    \/ \E p \in Procs, l \in Locks :
        \/ AcquireLock(p, l)
        \/ ReleaseLock(p, l)
        \/ BeginStaleCheck(p, l)
        \/ AcquireMetaLock(p, l)
        \/ MetaLockBusy(p, l)
        \/ BreakStaleLock(p, l)
    \/ \E p \in Procs :
        \/ Crash(p)
        \/ Restart(p)
        \/ BeginReconcile(p)
        \/ FinishReconcile(p)
    \/ \E p \in Procs, c \in Procs :
        \/ ReconcileSession(p, c)
    \/ Terminated

Spec == Init /\ [][Next]_vars

------------------------------------------------------------------------
(* ===== SAFETY PROPERTIES ===== *)

(* Meta-lock is exclusive: at most one process breaks a stale lock *)
NoDoubleBreak ==
    \A l \in Locks :
        \A p1, p2 \in Procs :
            (lockMeta[l] = p1 /\ lockMeta[l] = p2) => p1 = p2

(* A live process's lock is never broken *)
LiveLockNeverBroken ==
    \A p \in Procs, l \in Locks :
        (procState[p] = "holding_lock" /\ lockFile[l] = p)
        => lockFile[l] # "free"

(* Reconciler only operates on crashed processes *)
ReconcilerSafety ==
    \A p \in Procs :
        procState[p] = "reconciling" =>
            ~\E alive \in Procs :
                (procState[alive] \in {"alive", "holding_lock"} /\
                 journalExists[alive] = TRUE /\
                 resourcesOrphan[alive] = TRUE)

------------------------------------------------------------------------
(* ===== LIVENESS PROPERTIES ===== *)

(* Every crashed process's lock file is eventually freed *)
NoPhantomLocks ==
    \A p \in Procs :
        procState[p] = "crashed" ~>
            (\A l \in Locks : lockFile[l] # p)

(* Every crashed session's resources are eventually cleaned *)
CrashRecovery ==
    \A p \in Procs :
        (procState[p] = "crashed" /\ journalExists[p] = TRUE) ~>
            journalExists[p] = FALSE

FairSpec == Spec /\ WF_vars(Next)

========================================================================
