---- MODULE StaleLockRecovery_TTrace_1776888393 ----
EXTENDS Sequences, StaleLockRecovery_TEConstants, TLCExt, Toolbox, Naturals, TLC, StaleLockRecovery

_expression ==
    LET StaleLockRecovery_TEExpression == INSTANCE StaleLockRecovery_TEExpression
    IN StaleLockRecovery_TEExpression!expression
----

_trace ==
    LET StaleLockRecovery_TETrace == INSTANCE StaleLockRecovery_TETrace
    IN StaleLockRecovery_TETrace!trace
----

_inv ==
    ~(
        TLCGet("level") = Len(_TETrace)
        /\
        lockFile = ((merge :> "free" @@ worktree_setup :> "free"))
        /\
        journalExists = ((p1 :> FALSE @@ p2 :> FALSE @@ p3 :> FALSE))
        /\
        detecting = ((p1 :> "none" @@ p2 :> "none" @@ p3 :> "none"))
        /\
        lockMeta = ((merge :> "free" @@ worktree_setup :> "free"))
        /\
        procState = ((p1 :> "crashed" @@ p2 :> "crashed" @@ p3 :> "crashed"))
        /\
        lockMetaPid = ((merge :> 0 @@ worktree_setup :> 0))
        /\
        resourcesOrphan = ((p1 :> TRUE @@ p2 :> TRUE @@ p3 :> TRUE))
    )
----

_init ==
    /\ detecting = _TETrace[1].detecting
    /\ lockMeta = _TETrace[1].lockMeta
    /\ lockFile = _TETrace[1].lockFile
    /\ procState = _TETrace[1].procState
    /\ journalExists = _TETrace[1].journalExists
    /\ lockMetaPid = _TETrace[1].lockMetaPid
    /\ resourcesOrphan = _TETrace[1].resourcesOrphan
----

_next ==
    /\ \E i,j \in DOMAIN _TETrace:
        /\ \/ /\ j = i + 1
              /\ i = TLCGet("level")
        /\ detecting  = _TETrace[i].detecting
        /\ detecting' = _TETrace[j].detecting
        /\ lockMeta  = _TETrace[i].lockMeta
        /\ lockMeta' = _TETrace[j].lockMeta
        /\ lockFile  = _TETrace[i].lockFile
        /\ lockFile' = _TETrace[j].lockFile
        /\ procState  = _TETrace[i].procState
        /\ procState' = _TETrace[j].procState
        /\ journalExists  = _TETrace[i].journalExists
        /\ journalExists' = _TETrace[j].journalExists
        /\ lockMetaPid  = _TETrace[i].lockMetaPid
        /\ lockMetaPid' = _TETrace[j].lockMetaPid
        /\ resourcesOrphan  = _TETrace[i].resourcesOrphan
        /\ resourcesOrphan' = _TETrace[j].resourcesOrphan

\* Uncomment the ASSUME below to write the states of the error trace
\* to the given file in Json format. Note that you can pass any tuple
\* to `JsonSerialize`. For example, a sub-sequence of _TETrace.
    \* ASSUME
    \*     LET J == INSTANCE Json
    \*         IN J!JsonSerialize("StaleLockRecovery_TTrace_1776888393.json", _TETrace)

=============================================================================

 Note that you can extract this module `StaleLockRecovery_TEExpression`
  to a dedicated file to reuse `expression` (the module in the 
  dedicated `StaleLockRecovery_TEExpression.tla` file takes precedence 
  over the module `StaleLockRecovery_TEExpression` below).

---- MODULE StaleLockRecovery_TEExpression ----
EXTENDS Sequences, StaleLockRecovery_TEConstants, TLCExt, Toolbox, Naturals, TLC, StaleLockRecovery

expression == 
    [
        \* To hide variables of the `StaleLockRecovery` spec from the error trace,
        \* remove the variables below.  The trace will be written in the order
        \* of the fields of this record.
        detecting |-> detecting
        ,lockMeta |-> lockMeta
        ,lockFile |-> lockFile
        ,procState |-> procState
        ,journalExists |-> journalExists
        ,lockMetaPid |-> lockMetaPid
        ,resourcesOrphan |-> resourcesOrphan
        
        \* Put additional constant-, state-, and action-level expressions here:
        \* ,_stateNumber |-> _TEPosition
        \* ,_detectingUnchanged |-> detecting = detecting'
        
        \* Format the `detecting` variable as Json value.
        \* ,_detectingJson |->
        \*     LET J == INSTANCE Json
        \*     IN J!ToJson(detecting)
        
        \* Lastly, you may build expressions over arbitrary sets of states by
        \* leveraging the _TETrace operator.  For example, this is how to
        \* count the number of times a spec variable changed up to the current
        \* state in the trace.
        \* ,_detectingModCount |->
        \*     LET F[s \in DOMAIN _TETrace] ==
        \*         IF s = 1 THEN 0
        \*         ELSE IF _TETrace[s].detecting # _TETrace[s-1].detecting
        \*             THEN 1 + F[s-1] ELSE F[s-1]
        \*     IN F[_TEPosition - 1]
    ]

=============================================================================



Parsing and semantic processing can take forever if the trace below is long.
 In this case, it is advised to uncomment the module below to deserialize the
 trace from a generated binary file.

\*
\*---- MODULE StaleLockRecovery_TETrace ----
\*EXTENDS IOUtils, StaleLockRecovery_TEConstants, TLC, StaleLockRecovery
\*
\*trace == IODeserialize("StaleLockRecovery_TTrace_1776888393.bin", TRUE)
\*
\*=============================================================================
\*

---- MODULE StaleLockRecovery_TETrace ----
EXTENDS StaleLockRecovery_TEConstants, TLC, StaleLockRecovery

trace == 
    <<
    ([lockFile |-> (merge :> "free" @@ worktree_setup :> "free"),journalExists |-> (p1 :> FALSE @@ p2 :> FALSE @@ p3 :> FALSE),detecting |-> (p1 :> "none" @@ p2 :> "none" @@ p3 :> "none"),lockMeta |-> (merge :> "free" @@ worktree_setup :> "free"),procState |-> (p1 :> "alive" @@ p2 :> "alive" @@ p3 :> "alive"),lockMetaPid |-> (merge :> 0 @@ worktree_setup :> 0),resourcesOrphan |-> (p1 :> FALSE @@ p2 :> FALSE @@ p3 :> FALSE)]),
    ([lockFile |-> (merge :> "free" @@ worktree_setup :> "free"),journalExists |-> (p1 :> FALSE @@ p2 :> FALSE @@ p3 :> FALSE),detecting |-> (p1 :> "none" @@ p2 :> "none" @@ p3 :> "none"),lockMeta |-> (merge :> "free" @@ worktree_setup :> "free"),procState |-> (p1 :> "crashed" @@ p2 :> "alive" @@ p3 :> "alive"),lockMetaPid |-> (merge :> 0 @@ worktree_setup :> 0),resourcesOrphan |-> (p1 :> TRUE @@ p2 :> FALSE @@ p3 :> FALSE)]),
    ([lockFile |-> (merge :> "free" @@ worktree_setup :> "free"),journalExists |-> (p1 :> FALSE @@ p2 :> FALSE @@ p3 :> FALSE),detecting |-> (p1 :> "none" @@ p2 :> "none" @@ p3 :> "none"),lockMeta |-> (merge :> "free" @@ worktree_setup :> "free"),procState |-> (p1 :> "crashed" @@ p2 :> "crashed" @@ p3 :> "alive"),lockMetaPid |-> (merge :> 0 @@ worktree_setup :> 0),resourcesOrphan |-> (p1 :> TRUE @@ p2 :> TRUE @@ p3 :> FALSE)]),
    ([lockFile |-> (merge :> "free" @@ worktree_setup :> "free"),journalExists |-> (p1 :> FALSE @@ p2 :> FALSE @@ p3 :> FALSE),detecting |-> (p1 :> "none" @@ p2 :> "none" @@ p3 :> "none"),lockMeta |-> (merge :> "free" @@ worktree_setup :> "free"),procState |-> (p1 :> "crashed" @@ p2 :> "crashed" @@ p3 :> "crashed"),lockMetaPid |-> (merge :> 0 @@ worktree_setup :> 0),resourcesOrphan |-> (p1 :> TRUE @@ p2 :> TRUE @@ p3 :> TRUE)])
    >>
----


=============================================================================

---- MODULE StaleLockRecovery_TEConstants ----
EXTENDS StaleLockRecovery

CONSTANTS p1, p2, p3, merge, worktree_setup

=============================================================================

---- CONFIG StaleLockRecovery_TTrace_1776888393 ----
CONSTANTS
    Procs = { p1 , p2 , p3 }
    Locks = { merge , worktree_setup }
    worktree_setup = worktree_setup
    p2 = p2
    p1 = p1
    merge = merge
    p3 = p3

INVARIANT
    _inv

CHECK_DEADLOCK
    \* CHECK_DEADLOCK off because of PROPERTY or INVARIANT above.
    FALSE

INIT
    _init

NEXT
    _next

CONSTANT
    _TETrace <- _trace

ALIAS
    _expression
=============================================================================
\* Generated on Wed Apr 22 13:06:35 PDT 2026