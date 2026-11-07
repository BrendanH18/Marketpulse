using System.Diagnostics;
using System.Text;
using System.Text.Json;
using System.Text.Json.Serialization;

namespace MarketPulse.Demo;

public sealed record DemoSnapshot(decimal NetWorth, string Currency);

public static class DemoBackend
{
    public static async Task<DemoSnapshot> LoadAsync(string pythonPath, CancellationToken cancellationToken = default)
    {
        pythonPath = Path.GetFullPath(pythonPath);
        if (!File.Exists(pythonPath))
            throw new FileNotFoundException("Python backend not found. Build the backend or pass --python with its full path.", pythonPath);

        var scratch = Directory.CreateTempSubdirectory("marketpulse-windows-demo-");
        using var timeout = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);
        timeout.CancelAfter(TimeSpan.FromSeconds(30));
        using var process = new Process();
        process.StartInfo = new ProcessStartInfo(pythonPath)
        {
            UseShellExecute = false,
            CreateNoWindow = true,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            StandardOutputEncoding = Encoding.UTF8,
            StandardErrorEncoding = Encoding.UTF8,
            WorkingDirectory = scratch.FullName,
        };
        foreach (var arg in new[] { "-I", "-B", "-X", "utf8", "-m", "marketpulse", "desktop", "snapshot", "--demo" })
            process.StartInfo.ArgumentList.Add(arg);
        process.StartInfo.Environment["MARKETPULSE_DATA"] = Path.Combine(scratch.FullName, "data");
        process.StartInfo.Environment["MARKETPULSE_CONFIG"] = Path.Combine(scratch.FullName, "config.toml");
        try
        {
            process.Start();
            var output = process.StandardOutput.ReadToEndAsync(timeout.Token);
            var errors = process.StandardError.ReadToEndAsync(timeout.Token);
            try
            {
                await process.WaitForExitAsync(timeout.Token);
                var json = await output;
                var errorText = await errors;
                if (process.ExitCode != 0)
                    throw new InvalidOperationException($"Demo backend exited with code {process.ExitCode}: {errorText.Trim()}");
                return Decode(json);
            }
            catch (OperationCanceledException)
            {
                if (!process.HasExited)
                    process.Kill(entireProcessTree: true);
                await process.WaitForExitAsync(CancellationToken.None);
                // Observe both readers after cancellation before disposing their streams.
                try { await Task.WhenAll(output, errors); }
                catch (OperationCanceledException) { }
                throw;
            }
        }
        finally
        {
            scratch.Delete(recursive: true);
        }
    }

    public static DemoSnapshot Decode(string json)
    {
        var payload = JsonSerializer.Deserialize<SnapshotPayload>(json)
            ?? throw new InvalidDataException("The demo backend returned an empty snapshot.");
        if (payload.Version != 1)
            throw new InvalidDataException($"Unsupported desktop bridge version {payload.Version}; expected 1.");
        if (!payload.Demo)
            throw new InvalidDataException("The backend did not return a fictional demo snapshot.");
        if (payload.Status is null || string.IsNullOrWhiteSpace(payload.Status.Currency))
            throw new InvalidDataException("The snapshot is missing its base currency.");
        return new DemoSnapshot(payload.Status.NetWorth, payload.Status.Currency);
    }

    private sealed class SnapshotPayload
    {
        [JsonPropertyName("version")] public required int Version { get; init; }
        [JsonPropertyName("demo")] public required bool Demo { get; init; }
        [JsonPropertyName("status")] public required StatusPayload? Status { get; init; }
    }

    private sealed class StatusPayload
    {
        [JsonPropertyName("net_worth")] public required decimal NetWorth { get; init; }
        [JsonPropertyName("base")] public required string? Currency { get; init; }
    }
}
