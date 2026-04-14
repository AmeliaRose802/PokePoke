namespace PokePoke.Models;

/// <summary>
/// Represents a dependency relationship between beads issues.
/// </summary>
public record Dependency
{
    public required string Id { get; init; }
    public required string Title { get; init; }
    public required string IssueType { get; init; }

    /// <summary>parent, blocks, related, discovered-from.</summary>
    public required string DependencyTypeName { get; init; }

    public string? Status { get; init; }
    public int? Priority { get; init; }
    public string? Description { get; init; }
    public string? Owner { get; init; }
    public string? CreatedAt { get; init; }
    public string? CreatedBy { get; init; }
    public string? UpdatedAt { get; init; }
    public IReadOnlyList<string>? Labels { get; init; }
    public string? Notes { get; init; }
}
