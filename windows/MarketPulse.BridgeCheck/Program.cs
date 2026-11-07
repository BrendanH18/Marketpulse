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
