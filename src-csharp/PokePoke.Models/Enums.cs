namespace PokePoke.Models;

/// <summary>
/// Type of agent that can be dispatched by the orchestrator.
/// Maps to the Python AGENT_TYPES registry keys.
/// </summary>
public enum AgentType
{
    Work,
    Gate,
    Cleanup,
    TechDebt,
    Janitor,
    BacklogCleanup,
    BetaTester,
    CodeReview,
    WorktreeCleanup,
    Decomposition,
}

/// <summary>
/// Type of dependency relationship between beads issues.
/// </summary>
public enum DependencyType
{
    Parent,
    Blocks,
    Related,
    DiscoveredFrom,
}

/// <summary>
/// Status of a beads work item.
/// </summary>
public enum WorkItemStatus
{
    Open,
    InProgress,
    Closed,
    Blocked,
}

/// <summary>
/// Status reported by a work agent at the end of its session.
/// </summary>
public enum WorkAgentOutcomeStatus
{
    Completed,
    Blocked,
    NeedsClarification,
    TooLarge,
}

/// <summary>
/// Type of beads issue.
/// </summary>
public enum IssueType
{
    Bug,
    Feature,
    Task,
    Epic,
    Chore,
}

/// <summary>
/// Backoff mode for retry configuration.
/// </summary>
public enum BackoffMode
{
    Exponential,
    Linear,
}
