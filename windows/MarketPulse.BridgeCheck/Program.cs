using System.Text.Json;
using MarketPulse.Demo;

if (args.Length != 1)
    throw new ArgumentException("Pass the absolute path to the installed or bundled Python interpreter.");

var valid = """{"version":1,"demo":true,"status":{"net_worth":1234.56,"base":"CAD"}}""";
var decoded = DemoBackend.Decode(valid);
if (decoded != new DemoSnapshot(1234.56m, "CAD"))
    throw new Exception("Net worth or currency was changed while decoding.");
if (DemoBackend.Decode(valid.Replace("1234.56", "0")).NetWorth != 0)
    throw new Exception("A valid zero balance must be accepted.");

foreach (var invalid in new[]
{
    valid.Replace("\"version\":1", "\"version\":2"),
    valid.Replace("\"demo\":true", "\"demo\":false"),
    valid.Replace("\"net_worth\":1234.56,", ""),
    valid.Replace("1234.56", "null"),
    valid.Replace("\"CAD\"", "\"\""),
    valid.Replace("\"status\":{\"net_worth\":1234.56,\"base\":\"CAD\"}", "\"status\":null"),
    "{}", "null", "not JSON",
})
{
    try { DemoBackend.Decode(invalid); }
    catch (Exception error) when (error is JsonException or InvalidDataException) { continue; }
    throw new Exception($"Invalid snapshot was accepted: {invalid}");
}
Console.WriteLine("PASS: bridge version, demo flag, required fields, decimal value, currency, and invalid JSON checks.");

var live = await DemoBackend.LoadAsync(args[0]);
if (live.NetWorth <= 0 || live.Currency != "CAD")
    throw new Exception("Expected the fictional demo portfolio in CAD.");
Console.WriteLine($"PASS: real Python demo snapshot decoded ({live.NetWorth} {live.Currency}).");

using var canceled = new CancellationTokenSource();
canceled.Cancel();
try
{
    await DemoBackend.LoadAsync(args[0], canceled.Token);
    throw new Exception("A canceled request completed successfully.");
}
catch (OperationCanceledException)
{
    Console.WriteLine("PASS: canceled backend request terminates.");
}

try
{
    await DemoBackend.LoadAsync(Path.Combine(Path.GetTempPath(), Guid.NewGuid().ToString(), "missing-python.exe"));
    throw new Exception("A missing interpreter was accepted.");
}
catch (FileNotFoundException)
{
    Console.WriteLine("PASS: missing backend reports an error.");
}

var clientDemo = new BackendClient(args[0], demo: true);
var demo = await clientDemo.SnapshotAsync();
if (!demo.GetProperty("demo").GetBoolean() || demo.GetProperty("positions").GetArrayLength() == 0)
    throw new Exception("The workspace client did not decode the fictional portfolio.");
foreach (var invalid in new[]
{
    demo.GetRawText().Replace("\"version\": 1", "\"version\": 2"),
    demo.GetRawText().Replace("\"accounts\":", "\"missing_accounts\":"),
    demo.GetRawText().Replace("\"net_worth\":", "\"missing_net_worth\":"),
    "{}", "null", "[]", "{\"version\":\"1\"}", "not JSON",
})
{
    try { BackendClient.DecodeSnapshot(invalid, expectDemo: true); }
    catch (Exception error) when (error is JsonException or InvalidDataException) { continue; }
    throw new Exception("An incomplete or incompatible workspace snapshot was accepted.");
}
try
{
    await clientDemo.RunAsync(["accounts", "add", "--", "Forbidden demo write"]);
    throw new Exception("A write in read-only demo mode was accepted.");
}
catch (InvalidOperationException error) when (error.Message.Contains("read-only")) { }
Console.WriteLine("PASS: complete workspace snapshot, contract rejection, and read-only demo.");

using (var interrupted = new CancellationTokenSource())
{
    var inFlight = clientDemo.SnapshotAsync(interrupted.Token);
    interrupted.Cancel();
    try
    {
        await inFlight;
        throw new Exception("An interrupted backend process completed successfully.");
    }
    catch (OperationCanceledException) { }
}
Console.WriteLine("PASS: in-flight backend cancellation terminates the child and readers.");

var workspace = Directory.CreateTempSubdirectory("marketpulse-windows-bridge-check-");
try
{
    var client = new BackendClient(args[0], dataDirectory: Path.Combine(workspace.FullName, "data"),
        configPath: Path.Combine(workspace.FullName, "config.toml"));
    // Spaces, Unicode, shell syntax and a leading hyphen must reach Click unchanged.
    const string accountName = "--Fictional épargne $(echo nope) & account";
    await client.RunAsync(["accounts", "add", "--type", "TFSA", "--currency", "CAD", "--track-cash", "--", accountName]);
    var empty = await client.SnapshotAsync();
    var account = empty.GetProperty("accounts")[0];
    if (account.GetProperty("name").GetString() != accountName)
        throw new Exception("User-entered account text was changed by subprocess argument handling.");
    var accountId = account.GetProperty("id").ToString();
    await client.RunAsync(["deposit", "--account", accountId, "--currency", "CAD", "--", "1234.56"]);
    var funded = await client.SnapshotAsync();
    if (funded.GetProperty("status").GetProperty("net_worth").GetDecimal() != 1234.56m ||
        funded.GetProperty("activity")[0].GetProperty("direction").GetInt32() != 1)
        throw new Exception("Scratch deposit or the activity sign was decoded incorrectly.");

    var csvPath = Path.Combine(workspace.FullName, "fictional import.csv");
    await File.WriteAllTextAsync(csvPath, "date,type,amount,currency,note\n2026-01-15,deposit,25.50,CAD,Fictional import\n");
    using var preview = JsonDocument.Parse(await client.RunAsync(
        ["desktop", "import", "--account", accountId, "--profile", "generic", "--dry-run", "--", csvPath]));
    if (preview.RootElement.GetProperty("added").GetInt32() != 1)
        throw new Exception("Expected one fictional CSV row in the preview.");
    var afterPreview = await client.SnapshotAsync();
    if (afterPreview.GetProperty("activity").GetArrayLength() != 1)
        throw new Exception("CSV preview changed the scratch ledger.");
    using var imported = JsonDocument.Parse(await client.RunAsync(
        ["desktop", "import", "--account", accountId, "--profile", "generic", "--expect-fingerprint",
            preview.RootElement.GetProperty("fingerprint").GetString()!, "--", csvPath]));
    if (imported.RootElement.GetProperty("added").GetInt32() != 1)
        throw new Exception("CSV import did not match its preview.");
    var afterImport = await client.SnapshotAsync();
    if (afterImport.GetProperty("activity").GetArrayLength() != 2)
        throw new Exception("The imported fictional row is missing from Activity.");
    await client.RunAsync(["accounts", "edit", "--archive", "--", accountId]);
    var archived = await client.SnapshotAsync();
    if (archived.GetProperty("accounts").GetArrayLength() != 0 ||
        archived.GetProperty("activity").GetArrayLength() != 0 ||
        archived.GetProperty("status").GetProperty("net_worth").GetDecimal() != 0)
        throw new Exception("Archived scratch account leaked into workspaces or totals.");

    try
    {
        await client.RunAsync(["not-a-command"]);
        throw new Exception("An engine failure was accepted as success.");
    }
    catch (BackendRejectedException) { }
    using var requestCanceled = new CancellationTokenSource();
    requestCanceled.Cancel();
    try
    {
        await client.SnapshotAsync(requestCanceled.Token);
        throw new Exception("A canceled workspace request completed.");
    }
    catch (OperationCanceledException) { }
    Console.WriteLine("PASS: isolated scratch ledger, literal Unicode arguments, deposit, signed activity, CSV preview/import, archived accounts, engine errors, and cancellation.");
}
finally
{
    workspace.Delete(recursive: true);
}
