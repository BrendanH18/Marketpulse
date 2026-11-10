using System.Diagnostics;
using System.Text;
using System.Text.Json;

namespace MarketPulse.Demo;

public sealed class BackendRejectedException(string message) : InvalidOperationException(message);

/// <summary>Runs the existing engine without a shell; financial values remain engine-owned.</summary>
public sealed class BackendClient
{
    private readonly string _pythonPath;
    private readonly string? _dataDirectory;
    private readonly string? _configPath;
    public bool IsDemo { get; }

    public BackendClient(string pythonPath, bool demo = false, string? dataDirectory = null, string? configPath = null)
    {
        _pythonPath = Path.GetFullPath(pythonPath);
        IsDemo = demo;
        _dataDirectory = dataDirectory is null ? null : Path.GetFullPath(dataDirectory);
        _configPath = configPath is null ? null : Path.GetFullPath(configPath);
    }

    public async Task<JsonElement> SnapshotAsync(CancellationToken cancellationToken = default) =>
        DecodeSnapshot(await ReadAsync("snapshot", cancellationToken), expectDemo: IsDemo);

    public async Task<JsonElement> TaxAsync(CancellationToken cancellationToken = default) =>
        DecodeTax(await ReadAsync("tax", cancellationToken), expectDemo: IsDemo);

    public async Task<JsonElement> ExportTaxCsvAsync(int year, string path, CancellationToken cancellationToken = default)
    {
        var json = await RunAsync(["desktop", "tax-csv", "--year",
            year.ToString(System.Globalization.CultureInfo.InvariantCulture), "--", path], cancellationToken);
        using var document = JsonDocument.Parse(json);
        var root = document.RootElement;
        Require(root.ValueKind == JsonValueKind.Object && root.TryGetProperty("exported", out var count) &&
            count.ValueKind == JsonValueKind.Number && count.TryGetInt32(out var rows) && rows >= 0, "The tax export did not return a row count.");
        RequireArray(root, "issues");
        return root.Clone();
    }

    private async Task<string> ReadAsync(string command, CancellationToken cancellationToken)
    {
        if (!IsDemo)
            return await ExecuteAsync(["desktop", command], null, cancellationToken);

        var scratch = Directory.CreateTempSubdirectory("marketpulse-windows-demo-");
        try
        {
            return await ExecuteAsync(["desktop", command, "--demo"], scratch.FullName, cancellationToken);
        }
        finally
        {
            try { scratch.Delete(recursive: true); }
            catch (IOException error) { Console.Error.WriteLine($"Could not remove demo scratch directory: {error.Message}"); }
            catch (UnauthorizedAccessException error) { Console.Error.WriteLine($"Could not remove demo scratch directory: {error.Message}"); }
        }
    }

    /// <summary>Arguments must put user-entered positional values after the CLI's -- delimiter.</summary>
    public Task<string> RunAsync(IReadOnlyList<string> arguments, CancellationToken cancellationToken = default)
    {
        if (IsDemo)
            throw new InvalidOperationException("The fictional demo is read-only. Open your portfolio to make changes.");
        return ExecuteAsync(arguments, null, cancellationToken);
    }

    private async Task<string> ExecuteAsync(IReadOnlyList<string> arguments, string? scratch,
        CancellationToken cancellationToken)
    {
        cancellationToken.ThrowIfCancellationRequested();
        if (!File.Exists(_pythonPath))
            throw new FileNotFoundException("Python backend not found. Build the backend or pass --python with its full path.", _pythonPath);
        using var timeout = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);
        timeout.CancelAfter(TimeSpan.FromSeconds(60));
        using var process = new Process();
        process.StartInfo = new ProcessStartInfo(_pythonPath)
        {
            UseShellExecute = false,
            CreateNoWindow = true,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            StandardOutputEncoding = Encoding.UTF8,
            StandardErrorEncoding = Encoding.UTF8,
            WorkingDirectory = scratch ?? AppContext.BaseDirectory,
        };
        foreach (var argument in new[] { "-I", "-B", "-X", "utf8", "-m", "marketpulse" })
            process.StartInfo.ArgumentList.Add(argument);
        foreach (var argument in arguments)
            process.StartInfo.ArgumentList.Add(argument);
        var data = scratch is null ? _dataDirectory : Path.Combine(scratch, "data");
        var config = scratch is null ? _configPath : Path.Combine(scratch, "config.toml");
        if (data is not null)
            process.StartInfo.Environment["MARKETPULSE_DATA"] = data;
        if (config is not null)
            process.StartInfo.Environment["MARKETPULSE_CONFIG"] = config;
        process.StartInfo.Environment["NO_COLOR"] = "1";
        process.Start();
        var output = process.StandardOutput.ReadToEndAsync(timeout.Token);
        var errors = process.StandardError.ReadToEndAsync(timeout.Token);
        try
        {
            await process.WaitForExitAsync(timeout.Token);
            var text = await output;
            var error = await errors;
            if (process.ExitCode != 0)
                throw new BackendRejectedException($"Backend exited with code {process.ExitCode}: {error.Trim()}");
            return text;
        }
        catch (OperationCanceledException)
        {
            if (!process.HasExited)
                process.Kill(entireProcessTree: true);
            await process.WaitForExitAsync(CancellationToken.None);
            try { await Task.WhenAll(output, errors); }
            catch (OperationCanceledException) { }
            if (cancellationToken.IsCancellationRequested)
                throw;
            throw new TimeoutException("The backend took too long. Try refreshing.");
        }
    }

    /// <summary>Checks the versioned contract before a workspace consumes it.</summary>
    public static JsonElement DecodeSnapshot(string json, bool expectDemo = false)
    {
        using var document = JsonDocument.Parse(json);
        var root = document.RootElement;
        Require(root.ValueKind == JsonValueKind.Object, "The snapshot must be an object.");
        Require(root.TryGetProperty("version", out var version) && version.ValueKind == JsonValueKind.Number &&
            version.TryGetInt32(out var number) && number == 1,
            "Unsupported desktop bridge version; expected 1.");
        Require(root.TryGetProperty("demo", out var demo) && demo.ValueKind is JsonValueKind.True or JsonValueKind.False,
            "The snapshot is missing its demo flag.");
        Require(demo.GetBoolean() == expectDemo, "The snapshot's demo flag does not match the requested portfolio.");
        RequireObject(root, "status");
        var status = root.GetProperty("status");
        Require(status.TryGetProperty("base", out var currency) && currency.ValueKind == JsonValueKind.String &&
            !string.IsNullOrWhiteSpace(currency.GetString()), "The snapshot is missing its base currency.");
        Require(status.TryGetProperty("net_worth", out var value) && value.ValueKind == JsonValueKind.Number && value.TryGetDecimal(out _),
            "The snapshot is missing its net worth.");
        foreach (var name in new[] { "accounts", "watchlist", "history" })
            RequireArray(status, name);
        foreach (var name in new[] { "accounts", "positions", "activity", "income_months", "room", "alerts", "warnings" })
            RequireArray(root, name);
        foreach (var name in new[] { "settings", "automation", "storage" })
            RequireObject(root, name);
        // Clone so consumers own the JSON after the parser is disposed; no floating-point conversion occurs.
        return root.Clone();
    }

    /// <summary>Checks required version-1 tax fields, preserving explicit unknown amounts.</summary>
    public static JsonElement DecodeTax(string json, bool expectDemo = false)
    {
        using var document = JsonDocument.Parse(json);
        var root = document.RootElement;
        Require(root.ValueKind == JsonValueKind.Object, "The tax report must be an object.");
        Require(root.TryGetProperty("version", out var version) && version.ValueKind == JsonValueKind.Number &&
            version.TryGetInt32(out var number) && number == 1, "Unsupported tax bridge version; expected 1.");
        RequireBoolean(root, "demo");
        Require(root.GetProperty("demo").GetBoolean() == expectDemo,
            "The tax report's demo flag does not match the requested portfolio.");
        RequireText(root, "base_currency");
        RequireNumber(root, "inclusion_rate");
        foreach (var field in new[] { "years", "issues", "room", "notes" }) RequireArray(root, field);
        foreach (var year in root.GetProperty("years").EnumerateArray())
        {
            Require(year.ValueKind == JsonValueKind.Object && year.TryGetProperty("year", out var value) &&
                value.ValueKind == JsonValueKind.Number && value.TryGetInt32(out _), "The tax report has an invalid year.");
            foreach (var field in new[] { "proceeds", "acb", "denied", "net_gain", "taxable", "inclusion_rate",
                "dispositions", "missing_fx", "superficial" }) RequireNumber(year, field);
            RequireArray(year, "securities");
            RequireArray(year, "rows");
            foreach (var security in year.GetProperty("securities").EnumerateArray())
            {
                RequireText(security, "symbol");
                foreach (var field in new[] { "dispositions", "quantity", "proceeds", "acb", "denied", "net_gain", "missing_fx" })
                    RequireNumber(security, field);
            }
            foreach (var row in year.GetProperty("rows").EnumerateArray())
            {
                foreach (var field in new[] { "date", "symbol", "currency", "kind" }) RequireText(row, field);
                foreach (var field in new[] { "complete", "archived", "superficial", "window_open" }) RequireBoolean(row, field);
                foreach (var field in new[] { "quantity", "acquired_in_window", "held_after_window" }) RequireNumber(row, field);
                foreach (var field in new[] { "proceeds", "acb", "gain", "denied", "allowed_gain" })
                    RequireNumber(row, field, nullable: !row.GetProperty("complete").GetBoolean());
                RequireNumber(row, "fx", nullable: true);
            }
        }
        return root.Clone();
    }

    private static void RequireNumber(JsonElement parent, string field, bool nullable = false) => Require(
        parent.ValueKind == JsonValueKind.Object && parent.TryGetProperty(field, out var value) &&
        ((nullable && value.ValueKind == JsonValueKind.Null) ||
            (value.ValueKind == JsonValueKind.Number && value.TryGetDecimal(out _))),
        $"The tax report is missing or has an invalid {field} value.");

    private static void RequireText(JsonElement parent, string field) => Require(
        parent.ValueKind == JsonValueKind.Object && parent.TryGetProperty(field, out var value) &&
        value.ValueKind == JsonValueKind.String && !string.IsNullOrWhiteSpace(value.GetString()),
        $"The tax report is missing its {field}.");

    private static void RequireBoolean(JsonElement parent, string field) => Require(
        parent.ValueKind == JsonValueKind.Object && parent.TryGetProperty(field, out var value) &&
        value.ValueKind is JsonValueKind.True or JsonValueKind.False,
        $"The tax report is missing its {field} flag.");

    private static void RequireArray(JsonElement parent, string name) => Require(
        parent.TryGetProperty(name, out var value) && value.ValueKind == JsonValueKind.Array,
        $"The response is missing its {name} array.");

    private static void RequireObject(JsonElement parent, string name) => Require(
        parent.TryGetProperty(name, out var value) && value.ValueKind == JsonValueKind.Object,
        $"The snapshot is missing its {name} object.");

    private static void Require(bool condition, string message)
    {
        if (!condition)
            throw new InvalidDataException(message);
    }
}
