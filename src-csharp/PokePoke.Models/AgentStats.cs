namespace PokePoke.Models;

/// <summary>
/// Statistics from agent execution.
/// </summary>
public sealed class AgentStats
{
    public double WallDuration { get; set; }
    public double ApiDuration { get; set; }
    public int InputTokens { get; set; }
    public int OutputTokens { get; set; }
    public int LinesAdded { get; set; }
    public int LinesRemoved { get; set; }
    public int PremiumRequests { get; set; }
    public int Retries { get; set; }
    public int ToolCalls { get; set; }

    /// <summary>Add all fields from another <see cref="AgentStats"/> into this one.</summary>
    public void Accumulate(AgentStats other)
    {
        WallDuration += other.WallDuration;
        ApiDuration += other.ApiDuration;
        InputTokens += other.InputTokens;
        OutputTokens += other.OutputTokens;
        LinesAdded += other.LinesAdded;
        LinesRemoved += other.LinesRemoved;
        PremiumRequests += other.PremiumRequests;
        Retries += other.Retries;
        ToolCalls += other.ToolCalls;
    }

    /// <summary>Return a shallow copy of this instance.</summary>
    public AgentStats Copy() => (AgentStats)MemberwiseClone();
}
