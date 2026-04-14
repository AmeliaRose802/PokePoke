using System.Collections.Frozen;

namespace PokePoke.Models;

/// <summary>
/// Registry metadata for a known agent type.
/// Maps to Python's AgentTypeDefinition dataclass.
/// </summary>
public sealed record AgentTypeDefinition(
    string Key,
    string DisplayName,
    string Emoji,
    bool AlwaysShow = false
)
{
    public string RunAttr { get; } = $"{Key}_agent_runs";
}

/// <summary>
/// Static registry of all known agent types, mirroring the Python AGENT_TYPES dict.
/// </summary>
public static class AgentTypeRegistry
{
    public static readonly FrozenDictionary<string, AgentTypeDefinition> All =
        new Dictionary<string, AgentTypeDefinition>
        {
            ["work"] = new("work", "Work", "\U0001f4cb", AlwaysShow: true),
            ["gate"] = new("gate", "Gate", "\U0001f6aa"),
            ["cleanup"] = new("cleanup", "Cleanup", "\U0001f9f9"),
            ["tech_debt"] = new("tech_debt", "Tech Debt", "\U0001f4ca"),
            ["janitor"] = new("janitor", "Janitor", "\U0001f9fd"),
            ["backlog_cleanup"] = new("backlog_cleanup", "Backlog Cleanup", "\U0001f5d1"),
            ["beta_tester"] = new("beta_tester", "Beta Tester", "\U0001f9ea"),
            ["code_review"] = new("code_review", "Code Review", "\U0001f9d0"),
            ["worktree_cleanup"] = new("worktree_cleanup", "Worktree Cleanup", "\U0001f332"),
            ["decomposition"] = new("decomposition", "Decomposition", "\U0001f500"),
        }.ToFrozenDictionary();

    /// <summary>Create a zeroed-out agent run counts dict with all known agent keys.</summary>
    public static Dictionary<string, int> EmptyRunCounts() =>
        All.Keys.ToDictionary(k => k, _ => 0);

    /// <summary>
    /// Resolve a human-friendly agent identifier to its registry entry.
    /// Throws <see cref="ArgumentException"/> for unknown agent types.
    /// </summary>
    public static AgentTypeDefinition Resolve(string agentName)
    {
        var normalized = agentName.Trim().ToLowerInvariant().Replace(' ', '_');
        if (All.TryGetValue(normalized, out var definition))
            return definition;

        // Search by display name
        foreach (var entry in All.Values)
        {
            if (string.Equals(entry.DisplayName, agentName, StringComparison.OrdinalIgnoreCase))
                return entry;
        }

        throw new ArgumentException($"Unknown agent type: {agentName}", nameof(agentName));
    }
}
