namespace PokePoke.Models;

/// <summary>
/// Performance metrics for the merge queue.
/// Tracks throughput, latency, and failure rates for the serialized merge pipeline.
/// </summary>
public sealed class MergeQueueStats
{
    // Counters
    public int TotalMerges { get; set; }
    public int SuccessfulMerges { get; set; }
    public int FailedMerges { get; set; }
    public int TotalRebases { get; set; }
    public int SuccessfulRebases { get; set; }
    public int FailedRebases { get; set; }
    public int HighConflictMerges { get; set; }

    // Timing samples (seconds)
    public List<double> MergeDurations { get; init; } = [];
    public List<double> WaitTimes { get; init; } = [];
    public List<int> QueueDepthSamples { get; init; } = [];
    public List<double> DoubleRebaseOverheadSeconds { get; init; } = [];

    public double AvgMergeDuration =>
        MergeDurations.Count > 0 ? MergeDurations.Average() : 0.0;

    public double MaxMergeDuration =>
        MergeDurations.Count > 0 ? MergeDurations.Max() : 0.0;

    public double AvgWaitTime =>
        WaitTimes.Count > 0 ? WaitTimes.Average() : 0.0;

    public double MaxWaitTime =>
        WaitTimes.Count > 0 ? WaitTimes.Max() : 0.0;

    public int MaxQueueDepth =>
        QueueDepthSamples.Count > 0 ? QueueDepthSamples.Max() : 0;

    public double AvgQueueDepth =>
        QueueDepthSamples.Count > 0 ? QueueDepthSamples.Average() : 0.0;

    /// <summary>Fraction of rebases that succeeded (0.0-1.0).</summary>
    public double RebaseSuccessRate =>
        TotalRebases > 0 ? (double)SuccessfulRebases / TotalRebases : 0.0;

    public double AvgDoubleRebaseOverhead =>
        DoubleRebaseOverheadSeconds.Count > 0 ? DoubleRebaseOverheadSeconds.Average() : 0.0;

    /// <summary>Return a shallow copy with independent lists.</summary>
    public MergeQueueStats Copy() => new()
    {
        TotalMerges = TotalMerges,
        SuccessfulMerges = SuccessfulMerges,
        FailedMerges = FailedMerges,
        TotalRebases = TotalRebases,
        SuccessfulRebases = SuccessfulRebases,
        FailedRebases = FailedRebases,
        HighConflictMerges = HighConflictMerges,
        MergeDurations = [.. MergeDurations],
        WaitTimes = [.. WaitTimes],
        QueueDepthSamples = [.. QueueDepthSamples],
        DoubleRebaseOverheadSeconds = [.. DoubleRebaseOverheadSeconds],
    };
}
