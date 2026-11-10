namespace MarketPulse.Demo;

public sealed partial class BackendClient
{
    public Task<string> CreateBackupAsync(CancellationToken cancellationToken = default) =>
        RunAsync(["backup", "now"], cancellationToken);

    public Task<string> RestoreBackupAsync(string path, CancellationToken cancellationToken = default) =>
        RunAsync(["backup", "restore", "--yes", "--", path], cancellationToken);
}
