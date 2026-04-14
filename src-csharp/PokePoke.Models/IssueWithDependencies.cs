namespace PokePoke.Models;

/// <summary>
/// Represents an issue with full dependency information from <c>bd show --json</c>.
/// </summary>
public record IssueWithDependencies
{
    public required string Id { get; init; }
    public required string Title { get; init; }
    public required string Status { get; init; }
    public required int Priority { get; init; }
    public required string IssueType { get; init; }

    public string? Description { get; init; }
    public IReadOnlyList<Dependency>? Dependencies { get; init; }
    public IReadOnlyList<Dependency>? Dependents { get; init; }
    public string? Owner { get; init; }

    /// <summary>Agent actively working on this item.</summary>
    public string? Assignee { get; init; }

    public string? CreatedAt { get; init; }
    public string? CreatedBy { get; init; }
    public string? UpdatedAt { get; init; }
    public IReadOnlyList<string>? Labels { get; init; }
    public string? Notes { get; init; }
}
