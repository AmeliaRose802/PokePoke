namespace PokePoke.Models;

/// <summary>
/// Represents a beads work item from <c>bd ready --json</c>.
/// </summary>
public record BeadsWorkItem
{
    public required string Id { get; init; }
    public required string Title { get; init; }
    public required string Status { get; init; }
    public required int Priority { get; init; }
    public required string IssueType { get; init; }

    public string? Description { get; init; }
    public string? Owner { get; init; }

    /// <summary>Agent actively working on this item (e.g. pokepoke_agent_123).</summary>
    public string? Assignee { get; init; }

    public string? CreatedAt { get; init; }
    public string? CreatedBy { get; init; }
    public string? UpdatedAt { get; init; }
    public IReadOnlyList<string>? Labels { get; init; }

    /// <summary>Metadata from beads (gate_rejection_count, etc.).</summary>
    public IReadOnlyDictionary<string, object>? Metadata { get; init; }

    /// <summary>True for synthetic items (cleanup, maintenance) not in beads DB.</summary>
    public bool IsEphemeral { get; init; }
}
