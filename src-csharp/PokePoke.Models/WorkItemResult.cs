namespace PokePoke.Models;

/// <summary>
/// Result of processing a single work item.
/// </summary>
public sealed record WorkItemResult
{
    public required bool Success { get; init; }
    public required int RequestCount { get; init; }
    public AgentStats? Stats { get; init; }
    public int CleanupAgentRuns { get; init; }
    public int GateAgentRuns { get; init; }
    public ModelCompletionRecord? ModelCompletion { get; init; }
    public string? FailureReason { get; init; }
}
