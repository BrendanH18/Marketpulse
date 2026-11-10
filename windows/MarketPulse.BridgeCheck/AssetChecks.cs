using System.Globalization;
using System.Text.Json;
using MarketPulse.Demo;

internal static class AssetChecks
{
    internal static async Task RunAsync(string pythonPath)
    {
        var scratch = Directory.CreateTempSubdirectory("marketpulse-windows-asset-check-");
        try
        {
            var client = new BackendClient(pythonPath, dataDirectory: Path.Combine(scratch.FullName, "data"),
                configPath: Path.Combine(scratch.FullName, "config.toml"));
            // Fully invested, CAD-only custom holdings need neither quote nor FX requests.
            await client.RunAsync(["accounts", "add", "--type", "NONREG", "--currency", "CAD", "--", "Fictional assets"]);
            var initial = await client.SnapshotAsync();
            var accountId = initial.GetProperty("accounts")[0].GetProperty("id").ToString();
            var today = DateTime.Today.ToString("yyyy-MM-dd", CultureInfo.InvariantCulture);
            var start = DateTime.Today.AddDays(-365).ToString("yyyy-MM-dd", CultureInfo.InvariantCulture);
            const string symbol = "--ART-ÉPARGNE";
            const string name = "Fictional art $(echo nope) & épargne";
            string[] manual = ["asset", "manual", "--new-symbol", "--account", accountId, "--currency", "CAD", "--date", today,
                "--class", "alternative", "--name", name, "--request-id", Guid.NewGuid().ToString(), "--", symbol, "3500"];
            await client.RunAsync(manual);
            await client.RunAsync(manual);
            string[] fixedIncome = ["asset", "fixed", "--new-symbol", "--account", accountId, "--currency", "CAD", "--rate", "4",
                "--start", start, "--maturity", today, "--compounding", "annual", "--name", "Fictional GIC",
                "--request-id", Guid.NewGuid().ToString(), "--", "GIC-QA", "10000"];
            await client.RunAsync(fixedIncome);
            await client.RunAsync(fixedIncome);
            var created = await client.SnapshotAsync();
            var art = Row(created, "assets", "symbol", symbol);
            var gic = Row(created, "assets", "symbol", "GIC-QA");
            Require(created.GetProperty("activity").GetArrayLength() == 2 &&
                art.GetProperty("name").GetString() == name && art.GetProperty("kind").GetString() == "manual" &&
                art.GetProperty("asset_class").GetString() == "alternative" &&
                art.GetProperty("currency").GetString() == "CAD" &&
                gic.GetProperty("kind").GetString() == "fixed_income" &&
                gic.GetProperty("rate").GetDecimal() == 4m &&
                gic.GetProperty("start_date").GetString() == start &&
                gic.GetProperty("maturity_date").GetString() == today,
                "Custom asset metadata, literal arguments, or retry identity was changed.");
            var gicPosition = Row(created, "positions", "symbol", "GIC-QA");
            Require(gicPosition.GetProperty("currency").GetString() == "CAD" &&
                gicPosition.GetProperty("quantity").GetDecimal() == 1m &&
                gicPosition.GetProperty("price").GetDecimal() == 10400m &&
                gicPosition.GetProperty("value").GetDecimal() == 10400m &&
                gicPosition.GetProperty("book").GetDecimal() == 10000m,
                "The fixed-income position did not preserve the engine's native/base values.");

            string[] valuation = ["asset", "value", "--date", today, "--request-id", Guid.NewGuid().ToString(),
                "--", symbol, "3800"];
            await client.RunAsync(valuation);
            await client.RunAsync(valuation);
            await client.RunAsync(["asset", "classify", "--", symbol, "real_estate"]);
            var valued = await client.SnapshotAsync();
            var artPosition = Row(valued, "positions", "symbol", symbol);
            Require(valued.GetProperty("activity").GetArrayLength() == 3 &&
                artPosition.GetProperty("price").GetDecimal() == 3800m &&
                artPosition.GetProperty("value").GetDecimal() == 3800m &&
                artPosition.GetProperty("book").GetDecimal() == 3500m &&
                artPosition.GetProperty("currency").GetString() == "CAD" &&
                Row(valued, "assets", "symbol", symbol).GetProperty("asset_class").GetString() == "real_estate" &&
                Row(valued, "assets", "symbol", symbol).GetProperty("valued_on").GetString() == today &&
                valued.GetProperty("status").GetProperty("net_worth").GetDecimal() == 14200m,
                "Manual valuation, classification, date, or retry identity was decoded incorrectly.");
            Console.WriteLine("PASS: fictional GIC/manual assets, literal Unicode symbols/names, engine values, valuation/classification, and retry-safe writes.");

            await client.RunAsync(["allocation", "--quiet", "--clear-targets", "--target", "fixed_income=50", "--target", "real_estate=50"]);
            var allocated = await client.SnapshotAsync();
            Require(allocated.GetProperty("targets").GetArrayLength() == 2 &&
                Row(allocated, "targets", "bucket", "fixed_income").GetProperty("weight").GetDecimal() == 50m &&
                Row(allocated, "targets", "bucket", "real_estate").GetProperty("weight").GetDecimal() == 50m &&
                Row(allocated, "allocation", "key", "real_estate").GetProperty("value").GetDecimal() == 3800m &&
                Row(allocated, "rebalance", "bucket", "real_estate").GetProperty("delta").GetDecimal() == 3300m &&
                Row(allocated, "rebalance", "bucket", "fixed_income").GetProperty("delta").GetDecimal() == -3300m &&
                Row(allocated, "rebalance", "bucket", "real_estate").GetProperty("drift").GetDecimal() < 0m &&
                Row(allocated, "rebalance", "bucket", "fixed_income").GetProperty("drift").GetDecimal() > 0m,
                "Allocation targets or engine rebalancing fields were decoded incorrectly.");
            try
            {
                await client.RunAsync(["allocation", "--quiet", "--clear-targets", "--target", "fixed_income=70", "--target", "real_estate=40"]);
                throw new Exception("Targets above 100% were accepted.");
            }
            catch (BackendRejectedException) { }
            var rejected = await client.SnapshotAsync();
            Require(rejected.GetProperty("targets").GetRawText() == allocated.GetProperty("targets").GetRawText(),
                "A rejected allocation update changed existing targets.");
            await client.RunAsync(["allocation", "--quiet", "--clear-targets"]);
            var cleared = await client.SnapshotAsync();
            Require(cleared.GetProperty("targets").GetArrayLength() == 0 &&
                cleared.GetProperty("rebalance").GetArrayLength() == 0,
                "Cleared targets or suggestions remained in the snapshot.");
            await client.RunAsync(["accounts", "edit", "--archive", "--", accountId]);
            var archived = await client.SnapshotAsync();
            Require(archived.GetProperty("positions").GetArrayLength() == 0 &&
                archived.GetProperty("allocation").GetArrayLength() == 0 &&
                archived.GetProperty("status").GetProperty("net_worth").GetDecimal() == 0m,
                "Archived custom assets leaked into holdings or allocation.");
            Console.WriteLine("PASS: allocation/rebalance fields, rejected target preservation, clearing targets, and archived-asset exclusion.");
        }
        finally
        {
            scratch.Delete(recursive: true);
        }
    }

    private static JsonElement Row(JsonElement snapshot, string collection, string key, string value) =>
        snapshot.GetProperty(collection).EnumerateArray().Single(row => row.GetProperty(key).GetString() == value);

    private static void Require(bool condition, string message)
    {
        if (!condition) throw new Exception(message);
    }
}
