---- MODULE PokePokeMerge_TTrace_1776888668 ----
EXTENDS Sequences, TLCExt, PokePokeMerge_TEConstants, Toolbox, PokePokeMerge, Naturals, TLC

_expression ==
    LET PokePokeMerge_TEExpression == INSTANCE PokePokeMerge_TEExpression
    IN PokePokeMerge_TEExpression!expression
----

_trace ==
    LET PokePokeMerge_TETrace == INSTANCE PokePokeMerge_TETrace
    IN PokePokeMerge_TETrace!trace
----

_prop ==
    ~(([]<>(
            lockHolder = (a1)
            /\
            retryCount = ((a1 :> 0 @@ a2 :> 0 @@ a3 :> 0))
            /\
            agentState = ((a1 :> "merging" @@ a2 :> "done" @@ a3 :> "waiting_lock"))
            /\
            masterDirty = (FALSE)
            /\
            mergeConflicts = ((a1 :> FALSE @@ a2 :> TRUE @@ a3 :> TRUE))
    ))/\([]<>(
            lockHolder = (a1)
            /\
            retryCount = ((a1 :> 0 @@ a2 :> 0 @@ a3 :> 0))
            /\
            agentState = ((a1 :> "merging" @@ a2 :> "done" @@ a3 :> "waiting_lock"))
            /\
            masterDirty = (FALSE)
            /\
            mergeConflicts = ((a1 :> TRUE @@ a2 :> FALSE @@ a3 :> TRUE))
    )))
----

_init ==
    /\ retryCount = _TETrace[1].retryCount
    /\ lockHolder = _TETrace[1].lockHolder
    /\ mergeConflicts = _TETrace[1].mergeConflicts
    /\ agentState = _TETrace[1].agentState
    /\ masterDirty = _TETrace[1].masterDirty
----

_next ==
    /\ \E i,j \in DOMAIN _TETrace:
        /\ \/ /\ j = i + 1
              /\ i = TLCGet("level")
           \/ /\ i = _TTraceLassoEnd
              /\ j = _TTraceLassoStart
        /\ retryCount  = _TETrace[i].retryCount
        /\ retryCount' = _TETrace[j].retryCount
        /\ lockHolder  = _TETrace[i].lockHolder
        /\ lockHolder' = _TETrace[j].lockHolder
        /\ mergeConflicts  = _TETrace[i].mergeConflicts
        /\ mergeConflicts' = _TETrace[j].mergeConflicts
        /\ agentState  = _TETrace[i].agentState
        /\ agentState' = _TETrace[j].agentState
        /\ masterDirty  = _TETrace[i].masterDirty
        /\ masterDirty' = _TETrace[j].masterDirty

\* Uncomment the ASSUME below to write the states of the error trace
\* to the given file in Json format. Note that you can pass any tuple
\* to `JsonSerialize`. For example, a sub-sequence of _TETrace.
    \* ASSUME
    \*     LET J == INSTANCE Json
    \*         IN J!JsonSerialize("PokePokeMerge_TTrace_1776888668.json", _TETrace)


_view ==
    <<retryCount, lockHolder, mergeConflicts, agentState, masterDirty, IF TLCGet("level") = _TTraceLassoEnd + 1 THEN _TTraceLassoStart ELSE TLCGet("level")>>
=============================================================================

 Note that you can extract this module `PokePokeMerge_TEExpression`
  to a dedicated file to reuse `expression` (the module in the 
  dedicated `PokePokeMerge_TEExpression.tla` file takes precedence 
  over the module `PokePokeMerge_TEExpression` below).

---- MODULE PokePokeMerge_TEExpression ----
EXTENDS Sequences, TLCExt, PokePokeMerge_TEConstants, Toolbox, PokePokeMerge, Naturals, TLC

expression == 
    [
        \* To hide variables of the `PokePokeMerge` spec from the error trace,
        \* remove the variables below.  The trace will be written in the order
        \* of the fields of this record.
        retryCount |-> retryCount
        ,lockHolder |-> lockHolder
        ,mergeConflicts |-> mergeConflicts
        ,agentState |-> agentState
        ,masterDirty |-> masterDirty
        
        \* Put additional constant-, state-, and action-level expressions here:
        \* ,_stateNumber |-> _TEPosition
        \* ,_retryCountUnchanged |-> retryCount = retryCount'
        
        \* Format the `retryCount` variable as Json value.
        \* ,_retryCountJson |->
        \*     LET J == INSTANCE Json
        \*     IN J!ToJson(retryCount)
        
        \* Lastly, you may build expressions over arbitrary sets of states by
        \* leveraging the _TETrace operator.  For example, this is how to
        \* count the number of times a spec variable changed up to the current
        \* state in the trace.
        \* ,_retryCountModCount |->
        \*     LET F[s \in DOMAIN _TETrace] ==
        \*         IF s = 1 THEN 0
        \*         ELSE IF _TETrace[s].retryCount # _TETrace[s-1].retryCount
        \*             THEN 1 + F[s-1] ELSE F[s-1]
        \*     IN F[_TEPosition - 1]
    ]

=============================================================================



Parsing and semantic processing can take forever if the trace below is long.
 In this case, it is advised to uncomment the module below to deserialize the
 trace from a generated binary file.

\*
\*---- MODULE PokePokeMerge_TETrace ----
\*EXTENDS IOUtils, PokePokeMerge_TEConstants, PokePokeMerge, TLC
\*
\*trace == IODeserialize("PokePokeMerge_TTrace_1776888668.bin", TRUE)
\*
\*=============================================================================
\*

---- MODULE PokePokeMerge_TETrace ----
EXTENDS PokePokeMerge_TEConstants, PokePokeMerge, TLC

trace == 
    <<
    ([lockHolder |-> "none",retryCount |-> (a1 :> 0 @@ a2 :> 0 @@ a3 :> 0),agentState |-> (a1 :> "idle" @@ a2 :> "idle" @@ a3 :> "idle"),masterDirty |-> FALSE,mergeConflicts |-> (a1 :> TRUE @@ a2 :> FALSE @@ a3 :> TRUE)]),
    ([lockHolder |-> "none",retryCount |-> (a1 :> 0 @@ a2 :> 0 @@ a3 :> 0),agentState |-> (a1 :> "waiting_lock" @@ a2 :> "idle" @@ a3 :> "idle"),masterDirty |-> FALSE,mergeConflicts |-> (a1 :> TRUE @@ a2 :> FALSE @@ a3 :> TRUE)]),
    ([lockHolder |-> "none",retryCount |-> (a1 :> 0 @@ a2 :> 0 @@ a3 :> 0),agentState |-> (a1 :> "waiting_lock" @@ a2 :> "waiting_lock" @@ a3 :> "idle"),masterDirty |-> FALSE,mergeConflicts |-> (a1 :> TRUE @@ a2 :> FALSE @@ a3 :> TRUE)]),
    ([lockHolder |-> a2,retryCount |-> (a1 :> 0 @@ a2 :> 0 @@ a3 :> 0),agentState |-> (a1 :> "waiting_lock" @@ a2 :> "pre_check" @@ a3 :> "idle"),masterDirty |-> FALSE,mergeConflicts |-> (a1 :> TRUE @@ a2 :> FALSE @@ a3 :> TRUE)]),
    ([lockHolder |-> a2,retryCount |-> (a1 :> 0 @@ a2 :> 0 @@ a3 :> 0),agentState |-> (a1 :> "waiting_lock" @@ a2 :> "merging" @@ a3 :> "idle"),masterDirty |-> FALSE,mergeConflicts |-> (a1 :> TRUE @@ a2 :> FALSE @@ a3 :> TRUE)]),
    ([lockHolder |-> "none",retryCount |-> (a1 :> 0 @@ a2 :> 0 @@ a3 :> 0),agentState |-> (a1 :> "waiting_lock" @@ a2 :> "done" @@ a3 :> "idle"),masterDirty |-> FALSE,mergeConflicts |-> (a1 :> TRUE @@ a2 :> FALSE @@ a3 :> TRUE)]),
    ([lockHolder |-> a1,retryCount |-> (a1 :> 0 @@ a2 :> 0 @@ a3 :> 0),agentState |-> (a1 :> "pre_check" @@ a2 :> "done" @@ a3 :> "idle"),masterDirty |-> FALSE,mergeConflicts |-> (a1 :> TRUE @@ a2 :> FALSE @@ a3 :> TRUE)]),
    ([lockHolder |-> a1,retryCount |-> (a1 :> 0 @@ a2 :> 0 @@ a3 :> 0),agentState |-> (a1 :> "merging" @@ a2 :> "done" @@ a3 :> "idle"),masterDirty |-> FALSE,mergeConflicts |-> (a1 :> TRUE @@ a2 :> FALSE @@ a3 :> TRUE)]),
    ([lockHolder |-> a1,retryCount |-> (a1 :> 0 @@ a2 :> 0 @@ a3 :> 0),agentState |-> (a1 :> "merging" @@ a2 :> "done" @@ a3 :> "waiting_lock"),masterDirty |-> FALSE,mergeConflicts |-> (a1 :> TRUE @@ a2 :> FALSE @@ a3 :> TRUE)]),
    ([lockHolder |-> a1,retryCount |-> (a1 :> 0 @@ a2 :> 0 @@ a3 :> 0),agentState |-> (a1 :> "merging" @@ a2 :> "done" @@ a3 :> "waiting_lock"),masterDirty |-> FALSE,mergeConflicts |-> (a1 :> FALSE @@ a2 :> TRUE @@ a3 :> TRUE)])
    >>
----


=============================================================================

---- MODULE PokePokeMerge_TEConstants ----
EXTENDS PokePokeMerge

CONSTANTS a1, a2, a3, _TTraceLassoStart, _TTraceLassoEnd

=============================================================================

---- CONFIG PokePokeMerge_TTrace_1776888668 ----
CONSTANTS
    Agents = { a1 , a2 , a3 }
    MaxConflictRetries = 3
    a2 = a2
    a3 = a3
    a1 = a1
_TTraceLassoStart = 9
_TTraceLassoEnd = 10

PROPERTY
    _prop

CHECK_DEADLOCK
    \* CHECK_DEADLOCK off because of PROPERTY or INVARIANT above.
    FALSE

INIT
    _init

NEXT
    _next

VIEW
    _view

CONSTANT
    _TETrace <- _trace

ALIAS
    _expression
=============================================================================
\* Generated on Wed Apr 22 13:11:13 PDT 2026