using System.Globalization;
using System.Text.Json;
using System.Text.Json.Nodes;
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
foreach (var field in new[] { "assets", "allocation", "targets", "rebalance" })
{
    var incomplete = demo.GetRawText().Replace($"\"{field}\":", $"\"missing_{field}\":");
    try { BackendClient.DecodeSnapshot(incomplete, expectDemo: true); }
    catch (InvalidDataException) { continue; }
    throw new Exception($"A workspace snapshot missing its {field} array was accepted.");
}
try
{
    await clientDemo.RunAsync(["accounts", "add", "--", "Forbidden demo write"]);
    throw new Exception("A write in read-only demo mode was accepted.");
}
catch (InvalidOperationException error) when (error.Message.Contains("read-only")) { }
Console.WriteLine("PASS: complete workspace snapshot, contract rejection, and read-only demo.");

var demoTax = await clientDemo.TaxAsync();
if (!demoTax.GetProperty("demo").GetBoolean() || demoTax.GetProperty("years").GetArrayLength() == 0 ||
    !demoTax.GetProperty("years").EnumerateArray().Any(y => y.GetProperty("superficial").GetInt32() > 0))
    throw new Exception("The demo tax report is missing its fictional dispositions or superficial loss.");
foreach (var change in new Action<JsonObject>[]
{
    root => root["version"] = 2,
    root => root["demo"] = false,
    root => root.Remove("base_currency"),
    root => root["years"] = new JsonObject(),
    root => root["years"]![0]!.AsObject().Remove("net_gain"),
    root => root["years"]![0]!["rows"]![0]!.AsObject().Remove("complete"),
    root => root["years"]![0]!["rows"]![0]!["proceeds"] = null,
})
{
    var malformed = JsonNode.Parse(demoTax.GetRawText())!.AsObject();
    change(malformed);
    try { BackendClient.DecodeTax(malformed.ToJsonString(), expectDemo: true); }
    catch (InvalidDataException) { continue; }
    throw new Exception("An incomplete or incompatible tax report was accepted.");
}
var missingFx = JsonNode.Parse(demoTax.GetRawText())!.AsObject();
var incompleteRow = missingFx["years"]![0]!["rows"]![0]!;
incompleteRow["complete"] = false;
incompleteRow["fx"] = null;
foreach (var field in new[] { "proceeds", "acb", "gain", "denied", "allowed_gain" }) incompleteRow[field] = null;
var decodedMissingFx = BackendClient.DecodeTax(missingFx.ToJsonString(), expectDemo: true);
if (decodedMissingFx.GetProperty("years")[0].GetProperty("rows")[0].GetProperty("proceeds").ValueKind != JsonValueKind.Null)
    throw new Exception("An unknown tax amount was converted to zero.");
var demoExport = Path.Combine(Path.GetTempPath(), "marketpulse-forbidden-demo-" + Guid.NewGuid() + ".csv");
try
{
    await clientDemo.ExportTaxCsvAsync(2024, demoExport);
    throw new Exception("A CSV export was allowed in the read-only demo.");
}
catch (InvalidOperationException error) when (error.Message.Contains("read-only")) { }
if (File.Exists(demoExport)) throw new Exception("The read-only demo wrote a CSV file.");
Console.WriteLine("PASS: real Python tax demo, superficial-loss details, incompatible/missing-field rejection, explicit unknown FX amounts, and demo export disabled.");

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

    const string taxableName = "Fictional épargne taxable";
    await client.RunAsync(["accounts", "add", "--type", "NONREG", "--currency", "CAD", "--", taxableName]);
    var withTaxable = await client.SnapshotAsync();
    var taxableId = withTaxable.GetProperty("accounts").EnumerateArray()
        .Single(a => a.GetProperty("name").GetString() == taxableName).GetProperty("id").ToString();
    if ((await client.TaxAsync()).GetProperty("years").GetArrayLength() != 0)
        throw new Exception("A portfolio without taxable dispositions should return an empty tax report.");
    // Explicit CAD prices keep every tax request offline; don't request a market snapshot after these trades.
    foreach (var trade in new[]
    {
        ("buy", "2022-01-01", "FICT.TO", "10", "10"),
        ("sell", "2023-01-01", "FICT.TO", "5", "12"),
        ("buy", "2023-01-01", "LOSS.TO", "10", "20"),
        ("sell", "2023-01-10", "LOSS.TO", "10", "10"),
        ("buy", "2023-01-20", "LOSS.TO", "5", "10"),
        ("sell", "2024-01-01", "FICT.TO", "5", "15"),
    })
        await client.RunAsync([trade.Item1, "--account", taxableId, "--date", trade.Item2, "--currency", "CAD", "--",
            trade.Item3, trade.Item4, trade.Item5]);
    await client.RunAsync(["accounts", "edit", "--archive", "--", taxableId]);
    var tax = await client.TaxAsync();
    var taxYears = tax.GetProperty("years").EnumerateArray().ToArray();
    var year2023 = taxYears.Single(y => y.GetProperty("year").GetInt32() == 2023);
    var year2024 = taxYears.Single(y => y.GetProperty("year").GetInt32() == 2024);
    if (taxYears.Length != 2 || year2023.GetProperty("net_gain").GetDecimal() != -40m ||
        year2023.GetProperty("denied").GetDecimal() != 50m || year2024.GetProperty("net_gain").GetDecimal() != 25m)
        throw new Exception("The engine's multi-year CAD tax amounts changed while decoding.");
    var taxRows = year2023.GetProperty("rows").EnumerateArray().ToArray();
    var loss = taxRows.Single(r => r.GetProperty("symbol").GetString() == "LOSS.TO");
    if (!loss.GetProperty("superficial").GetBoolean() || loss.GetProperty("denied").GetDecimal() != 50m ||
        loss.GetProperty("acquired_in_window").GetDecimal() != 15m || loss.GetProperty("held_after_window").GetDecimal() != 5m)
        throw new Exception("The superficial-loss explanation changed while decoding.");
    if (taxYears.SelectMany(y => y.GetProperty("rows").EnumerateArray())
        .Any(r => !r.GetProperty("archived").GetBoolean() || r.GetProperty("account").ValueKind != JsonValueKind.Null))
        throw new Exception("Archived taxable entries were dropped or leaked their account name.");
    var exportPath = Path.Combine(workspace.FullName, "--gains épargne & literal.csv");
    var exported = await client.ExportTaxCsvAsync(2023, exportPath);
    var csv = await File.ReadAllLinesAsync(exportPath);
    if (exported.GetProperty("exported").GetInt32() != taxRows.Length || csv.Length != taxRows.Length + 1 ||
        !csv[0].Contains("Proceeds (CAD)") || csv.Skip(1).Any(line => !line.StartsWith("2023,")))
        throw new Exception("The selected-year tax CSV did not match the report rows.");
    // The fictional fixture contains no commas in its text fields, so simple splitting is sufficient here.
    foreach (var line in csv.Skip(1))
    {
        var fields = line.Split(',');
        var reportRow = taxRows.Single(r => r.GetProperty("symbol").GetString() == fields[4]);
        foreach (var (column, field) in new[] { (8, "proceeds"), (9, "acb"), (10, "gain"), (11, "denied"), (12, "allowed_gain") })
            if (decimal.Parse(fields[column], CultureInfo.InvariantCulture) != reportRow.GetProperty(field).GetDecimal())
                throw new Exception("An exported tax amount differs from the selected-year report.");
        if (fields[2] != taxableName) throw new Exception("UTF-8 account text was not preserved by the engine's accountant CSV.");
    }
    foreach (var (year, path) in new[] { (1900, Path.Combine(workspace.FullName, "no-year.csv")),
        (2023, Path.Combine(workspace.FullName, "missing folder", "gains.csv")) })
    {
        try { await client.ExportTaxCsvAsync(year, path); }
        catch (BackendRejectedException) { continue; }
        throw new Exception("A failed tax export was accepted as success.");
    }
    try { await client.TaxAsync(requestCanceled.Token); throw new Exception("A canceled tax request completed."); }
    catch (OperationCanceledException) { }
    var canceledExport = Path.Combine(workspace.FullName, "canceled.csv");
    try { await client.ExportTaxCsvAsync(2023, canceledExport, requestCanceled.Token); throw new Exception("A canceled tax export completed."); }
    catch (OperationCanceledException) { }
    if (File.Exists(canceledExport)) throw new Exception("An already-canceled export wrote a file.");
    try
    {
        await new BackendClient(Path.Combine(workspace.FullName, "missing-python.exe"),
            dataDirectory: workspace.FullName, configPath: Path.Combine(workspace.FullName, "missing.toml")).TaxAsync();
        throw new Exception("A tax request with a missing backend succeeded.");
    }
    catch (FileNotFoundException) { }
    Console.WriteLine("PASS: real Python multi-year CAD tax report, superficial-loss working, anonymized archived activity, selected-year UTF-8 CSV parity, export/backend errors, and canceled tax requests/exports.");
}
finally
{
    workspace.Delete(recursive: true);
}

await AssetChecks.RunAsync(args[0]);
