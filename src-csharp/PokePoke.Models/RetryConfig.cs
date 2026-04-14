namespace PokePoke.Models;

/// <summary>
/// Configuration for retry logic with backoff.
/// Supports exponential (default) and linear backoff modes.
/// </summary>
public sealed record RetryConfig
{
    public int MaxRetries { get; init; } = 3;
    public double InitialDelaySeconds { get; init; } = 1.0;
    public double MaxDelaySeconds { get; init; } = 60.0;
    public double BackoffFactor { get; init; } = 2.0;

    /// <summary>Add random jitter to prevent thundering herd.</summary>
    public bool Jitter { get; init; } = true;

    public BackoffMode BackoffMode { get; init; } = BackoffMode.Exponential;
}
