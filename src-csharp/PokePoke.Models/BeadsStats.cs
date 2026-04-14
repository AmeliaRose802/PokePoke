namespace PokePoke.Models;

/// <summary>
/// Statistics from the beads database.
/// </summary>
public sealed record BeadsStats
{
    public int TotalIssues { get; init; }
    public int OpenIssues { get; init; }
    public int InProgressIssues { get; init; }
    public int ClosedIssues { get; init; }
    public int ReadyIssues { get; init; }
}
