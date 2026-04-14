namespace PokePoke.Models;

/// <summary>
/// Structured outcome returned by a work agent at the end of its session.
/// The orchestrator uses this to make intelligent decisions (fail-fast on
/// blocked/too_large items, pass structured context to the gate agent, etc.).
/// </summary>
public sealed record WorkAgentOutcome
{
    public required WorkAgentOutcomeStatus Status { get; init; }
    public string Reason { get; init; } = "";
    public IReadOnlyList<string> FilesModified { get; init; } = [];
    public IReadOnlyList<string> TestsAdded { get; init; } = [];
    public IReadOnlyList<string> SuggestedSplit { get; init; } = [];
}
