namespace PokePoke.Models;

/// <summary>
/// Record of a single work item completion for a specific model.
/// Used for A/B testing and model performance tracking.
/// </summary>
public sealed record ModelCompletionRecord
{
    public required string ItemId { get; init; }
    public required string Model { get; init; }
    public required double DurationSeconds { get; init; }

    /// <summary>Null means the gate was not run.</summary>
    public bool? GatePassed { get; init; }

    public int InputTokens { get; init; }
    public int OutputTokens { get; init; }
    public int AgentTurns { get; init; }
    public double Cost { get; init; }
    public int RetryAttempts { get; init; }
    public double? ApiDuration { get; init; }
    public int? LinesAdded { get; init; }
    public int? LinesRemoved { get; init; }

    /// <summary>Model used by the gate agent.</summary>
    public string? GateModel { get; init; }
}
