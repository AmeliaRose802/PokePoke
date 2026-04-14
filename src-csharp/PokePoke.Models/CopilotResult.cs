namespace PokePoke.Models;

/// <summary>
/// Result from invoking the AI CLI backend (Copilot or Claude Code).
/// </summary>
public sealed record CopilotResult
{
    public required string WorkItemId { get; init; }
    public required bool Success { get; init; }
    public string? Output { get; init; }
    public string? Error { get; init; }
    public IReadOnlyList<string>? ValidationErrors { get; init; }
    public int AttemptCount { get; init; } = 1;

    /// <summary>True if error was due to rate limiting.</summary>
    public bool IsRateLimited { get; init; }

    public AgentStats? Stats { get; init; }

    /// <summary>Model used for this invocation.</summary>
    public string? Model { get; init; }

    /// <summary>SDK session ID, reusable for resume on timeout.</summary>
    public string? SessionId { get; init; }

    /// <summary>Truncated output summary for retry context.</summary>
    public string? LastOutputSummary { get; init; }

    /// <summary>Structured outcome from work agent.</summary>
    public WorkAgentOutcome? WorkAgentOutcome { get; init; }
}
