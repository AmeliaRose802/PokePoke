namespace PokePoke.Models;

/// <summary>
/// Result from running the gate agent.
/// </summary>
public sealed record GateAgentResult
{
    public required bool Success { get; init; }
    public required string Reason { get; init; }
    public AgentStats? Stats { get; init; }
    public bool Crashed { get; init; }
    public bool IsTimeout { get; init; }
    public string? SessionId { get; init; }
    public string? LastOutputSummary { get; init; }
}
