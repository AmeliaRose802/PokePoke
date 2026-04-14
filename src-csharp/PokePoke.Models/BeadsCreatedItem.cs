namespace PokePoke.Models;

/// <summary>
/// A beads item created by an agent during the session.
/// </summary>
public sealed record BeadsCreatedItem(
    string Id,
    string Title = "",
    string AgentType = "unknown"
);
