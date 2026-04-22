---- MODULE WorkItemClaim_TTrace_1776888315 ----
EXTENDS WorkItemClaim_TEConstants, Sequences, TLCExt, WorkItemClaim, Toolbox, Naturals, TLC

_expression ==
    LET WorkItemClaim_TEExpression == INSTANCE WorkItemClaim_TEExpression
    IN WorkItemClaim_TEExpression!expression
----

_trace ==
    LET WorkItemClaim_TETrace == INSTANCE WorkItemClaim_TETrace
    IN WorkItemClaim_TETrace!trace
----

_inv ==
    ~(
        TLCGet("level") = Len(_TETrace)
        /\
        itemOwner = ()
        /\
        claimPhase = ((<<a1, i1>> :> "claimed" @@ <<a1, i2>> :> "none" @@ <<a2, i1>> :> "none" @@ <<a2, i2>> :> "none"))
        /\
        journal = ((<<a1, i1>> :> "none" @@ <<a1, i2>> :> "none" @@ <<a2, i1>> :> "none" @@ <<a2, i2>> :> "none"))
        /\
        branchExists = ((i1 :> FALSE @@ i2 :> FALSE))
        /\
        itemLock = ((i1 :> "none" @@ i2 :> "none"))
        /\
        worktreeExists = ((i1 :> FALSE @@ i2 :> FALSE))
        /\
        sessionPhase = ((<<a1, i1>> :> "none" @@ <<a1, i2>> :> "none" @@ <<a2, i1>> :> "none" @@ <<a2, i2>> :> "none"))
    )
----

_init ==
    /\ claimPhase = _TETrace[1].claimPhase
    /\ sessionPhase = _TETrace[1].sessionPhase
    /\ branchExists = _TETrace[1].branchExists
    /\ journal = _TETrace[1].journal
    /\ itemLock = _TETrace[1].itemLock
    /\ itemOwner = _TETrace[1].itemOwner
    /\ worktreeExists = _TETrace[1].worktreeExists
----

_next ==
    /\ \E i,j \in DOMAIN _TETrace:
        /\ \/ /\ j = i + 1
              /\ i = TLCGet("level")
        /\ claimPhase  = _TETrace[i].claimPhase
        /\ claimPhase' = _TETrace[j].claimPhase
        /\ sessionPhase  = _TETrace[i].sessionPhase
        /\ sessionPhase' = _TETrace[j].sessionPhase
        /\ branchExists  = _TETrace[i].branchExists
        /\ branchExists' = _TETrace[j].branchExists
        /\ journal  = _TETrace[i].journal
        /\ journal' = _TETrace[j].journal
        /\ itemLock  = _TETrace[i].itemLock
        /\ itemLock' = _TETrace[j].itemLock
        /\ itemOwner  = _TETrace[i].itemOwner
        /\ itemOwner' = _TETrace[j].itemOwner
        /\ worktreeExists  = _TETrace[i].worktreeExists
        /\ worktreeExists' = _TETrace[j].worktreeExists

\* Uncomment the ASSUME below to write the states of the error trace
\* to the given file in Json format. Note that you can pass any tuple
\* to `JsonSerialize`. For example, a sub-sequence of _TETrace.
    \* ASSUME
    \*     LET J == INSTANCE Json
    \*         IN J!JsonSerialize("WorkItemClaim_TTrace_1776888315.json", _TETrace)

=============================================================================

 Note that you can extract this module `WorkItemClaim_TEExpression`
  to a dedicated file to reuse `expression` (the module in the 
  dedicated `WorkItemClaim_TEExpression.tla` file takes precedence 
  over the module `WorkItemClaim_TEExpression` below).

---- MODULE WorkItemClaim_TEExpression ----
EXTENDS WorkItemClaim_TEConstants, Sequences, TLCExt, WorkItemClaim, Toolbox, Naturals, TLC

expression == 
    [
        \* To hide variables of the `WorkItemClaim` spec from the error trace,
        \* remove the variables below.  The trace will be written in the order
        \* of the fields of this record.
        claimPhase |-> claimPhase
        ,sessionPhase |-> sessionPhase
        ,branchExists |-> branchExists
        ,journal |-> journal
        ,itemLock |-> itemLock
        ,itemOwner |-> itemOwner
        ,worktreeExists |-> worktreeExists
        
        \* Put additional constant-, state-, and action-level expressions here:
        \* ,_stateNumber |-> _TEPosition
        \* ,_claimPhaseUnchanged |-> claimPhase = claimPhase'
        
        \* Format the `claimPhase` variable as Json value.
        \* ,_claimPhaseJson |->
        \*     LET J == INSTANCE Json
        \*     IN J!ToJson(claimPhase)
        
        \* Lastly, you may build expressions over arbitrary sets of states by
        \* leveraging the _TETrace operator.  For example, this is how to
        \* count the number of times a spec variable changed up to the current
        \* state in the trace.
        \* ,_claimPhaseModCount |->
        \*     LET F[s \in DOMAIN _TETrace] ==
        \*         IF s = 1 THEN 0
        \*         ELSE IF _TETrace[s].claimPhase # _TETrace[s-1].claimPhase
        \*             THEN 1 + F[s-1] ELSE F[s-1]
        \*     IN F[_TEPosition - 1]
    ]

=============================================================================



Parsing and semantic processing can take forever if the trace below is long.
 In this case, it is advised to uncomment the module below to deserialize the
 trace from a generated binary file.

\*
\*---- MODULE WorkItemClaim_TETrace ----
\*EXTENDS WorkItemClaim_TEConstants, IOUtils, WorkItemClaim, TLC
\*
\*trace == IODeserialize("WorkItemClaim_TTrace_1776888315.bin", TRUE)
\*
\*=============================================================================
\*

---- MODULE WorkItemClaim_TETrace ----
EXTENDS WorkItemClaim_TEConstants, WorkItemClaim, TLC

trace == 
    <<
    ([itemOwner |-> (i1 :> "none" @@ i2 :> "none"),claimPhase |-> (<<a1, i1>> :> "none" @@ <<a1, i2>> :> "none" @@ <<a2, i1>> :> "none" @@ <<a2, i2>> :> "none"),journal |-> (<<a1, i1>> :> "none" @@ <<a1, i2>> :> "none" @@ <<a2, i1>> :> "none" @@ <<a2, i2>> :> "none"),branchExists |-> (i1 :> FALSE @@ i2 :> FALSE),itemLock |-> (i1 :> "none" @@ i2 :> "none"),worktreeExists |-> (i1 :> FALSE @@ i2 :> FALSE),sessionPhase |-> (<<a1, i1>> :> "none" @@ <<a1, i2>> :> "none" @@ <<a2, i1>> :> "none" @@ <<a2, i2>> :> "none")]),
    ([itemOwner |-> (i1 :> "none" @@ i2 :> "none"),claimPhase |-> (<<a1, i1>> :> "lock_acquired" @@ <<a1, i2>> :> "none" @@ <<a2, i1>> :> "none" @@ <<a2, i2>> :> "none"),journal |-> (<<a1, i1>> :> "none" @@ <<a1, i2>> :> "none" @@ <<a2, i1>> :> "none" @@ <<a2, i2>> :> "none"),branchExists |-> (i1 :> FALSE @@ i2 :> FALSE),itemLock |-> (i1 :> a1 @@ i2 :> "none"),worktreeExists |-> (i1 :> FALSE @@ i2 :> FALSE),sessionPhase |-> (<<a1, i1>> :> "none" @@ <<a1, i2>> :> "none" @@ <<a2, i1>> :> "none" @@ <<a2, i2>> :> "none")]),
    ([itemOwner |-> (i1 :> "none" @@ i2 :> "none"),claimPhase |-> (<<a1, i1>> :> "writing_claim" @@ <<a1, i2>> :> "none" @@ <<a2, i1>> :> "none" @@ <<a2, i2>> :> "none"),journal |-> (<<a1, i1>> :> "none" @@ <<a1, i2>> :> "none" @@ <<a2, i1>> :> "none" @@ <<a2, i2>> :> "none"),branchExists |-> (i1 :> FALSE @@ i2 :> FALSE),itemLock |-> (i1 :> a1 @@ i2 :> "none"),worktreeExists |-> (i1 :> FALSE @@ i2 :> FALSE),sessionPhase |-> (<<a1, i1>> :> "none" @@ <<a1, i2>> :> "none" @@ <<a2, i1>> :> "none" @@ <<a2, i2>> :> "none")]),
    ([itemOwner |-> (i1 :> a1 @@ i2 :> "none"),claimPhase |-> (<<a1, i1>> :> "verifying" @@ <<a1, i2>> :> "none" @@ <<a2, i1>> :> "none" @@ <<a2, i2>> :> "none"),journal |-> (<<a1, i1>> :> "none" @@ <<a1, i2>> :> "none" @@ <<a2, i1>> :> "none" @@ <<a2, i2>> :> "none"),branchExists |-> (i1 :> FALSE @@ i2 :> FALSE),itemLock |-> (i1 :> a1 @@ i2 :> "none"),worktreeExists |-> (i1 :> FALSE @@ i2 :> FALSE),sessionPhase |-> (<<a1, i1>> :> "none" @@ <<a1, i2>> :> "none" @@ <<a2, i1>> :> "none" @@ <<a2, i2>> :> "none")]),
    ([itemOwner |-> ,claimPhase |-> (<<a1, i1>> :> "claimed" @@ <<a1, i2>> :> "none" @@ <<a2, i1>> :> "none" @@ <<a2, i2>> :> "none"),journal |-> (<<a1, i1>> :> "none" @@ <<a1, i2>> :> "none" @@ <<a2, i1>> :> "none" @@ <<a2, i2>> :> "none"),branchExists |-> (i1 :> FALSE @@ i2 :> FALSE),itemLock |-> (i1 :> "none" @@ i2 :> "none"),worktreeExists |-> (i1 :> FALSE @@ i2 :> FALSE),sessionPhase |-> (<<a1, i1>> :> "none" @@ <<a1, i2>> :> "none" @@ <<a2, i1>> :> "none" @@ <<a2, i2>> :> "none")])
    >>
----


=============================================================================

---- MODULE WorkItemClaim_TEConstants ----
EXTENDS WorkItemClaim

CONSTANTS a1, a2, i1, i2

=============================================================================

---- CONFIG WorkItemClaim_TTrace_1776888315 ----
CONSTANTS
    Agents = { a1 , a2 }
    Items = { i1 , i2 }
    i1 = i1
    i2 = i2
    a2 = a2
    a1 = a1

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
\* Generated on Wed Apr 22 13:05:17 PDT 2026