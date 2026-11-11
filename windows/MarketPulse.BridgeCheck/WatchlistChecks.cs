using System.Diagnostics;
using System.Text.Json;
using MarketPulse.Demo;

internal static class WatchlistChecks
{
    internal static async Task RunAsync(string python)
    {
        var scratch = Directory.CreateTempSubdirectory("marketpulse-watchlist-check-");
        try
        {
            var data = Path.Combine(scratch.FullName, "fictional data");
            var config = Path.Combine(scratch.FullName, "fictional config.toml");
            var client = new BackendClient(python, dataDirectory: data, configPath: config);
            var defaults = await Saved(client);
            if (defaults.Length > 0) await client.RunAsync(new[] { "watch", "rm", "--" }.Concat(defaults).ToArray());
            await client.RunAsync(["watch", "add", "--", "QA-FIRST", "QA-SECOND", "QA-THIRD"]);
            await client.RunAsync(["watch", "move", "--to", "1", "--", "QA-THIRD"]);
            // A new client/process must read the persisted order, not a UI-only sort.
            var reopened = new BackendClient(python, dataDirectory: data, configPath: config);
            Require((await Saved(reopened)).SequenceEqual(new[] { "QA-THIRD", "QA-FIRST", "QA-SECOND" }), "Watchlist move did not persist.");
            await client.RunAsync(["watch", "move", "--to", "3", "--", "QA-THIRD"]);
            Require((await Saved(reopened)).SequenceEqual(new[] { "QA-FIRST", "QA-SECOND", "QA-THIRD" }), "Moving down changed saved order incorrectly.");
            try { await client.RunAsync(["watch", "move", "--to", "4", "--", "QA-FIRST"]); throw new Exception("Invalid watchlist position accepted."); }
            catch (BackendRejectedException) { }
            Require((await Saved(reopened)).SequenceEqual(new[] { "QA-FIRST", "QA-SECOND", "QA-THIRD" }), "Rejected move changed saved order.");
            Console.WriteLine("PASS: watchlist moves in both directions persist across clients; rejected positions preserve order (offline).");

            await client.RunAsync(["alerts", "add", "--note", "Fictional initial note", "--", "QA-ALERT", "above", "100"]);
            using var list = JsonDocument.Parse(await client.RunAsync(["alerts", "list", "--json"]));
            var id = list.RootElement[0].GetProperty("id").ToString();
            const string triggered = "2026-01-15T12:34:56+00:00";
            // Seed only trigger history; lifecycle changes themselves run through the real CLI.
            using (var seed = new Process())
            {
                seed.StartInfo = new ProcessStartInfo(python) { UseShellExecute = false };
                foreach (var argument in new[] { "-I", "-c", "import sqlite3,sys; c=sqlite3.connect(sys.argv[1]); c.execute('UPDATE alerts SET triggered_at=? WHERE id=?',(sys.argv[2],sys.argv[3])); c.commit(); c.close()", Path.Combine(data, "marketpulse.db"), triggered, id })
                    seed.StartInfo.ArgumentList.Add(argument);
                seed.Start();
                await seed.WaitForExitAsync();
                Require(seed.ExitCode == 0, "Could not seed fictional trigger history.");
            }
            await client.RunAsync(["alerts", "pause", "--", id]);
            const string note = "--Fictional épargne $(echo nope) & note";
            await client.RunAsync(["alerts", "edit", "--threshold", "123.45", "--note", note, "--", id]);
            var edited = await Alert(reopened, id);
            Require(edited.GetProperty("threshold").GetDecimal() == 123.45m && edited.GetProperty("note").GetString() == note &&
                edited.GetProperty("state").GetString() == "paused" && edited.GetProperty("triggered_at").GetString() == triggered,
                "Editing did not preserve paused state/history or literal Unicode note.");
            await client.RunAsync(["alerts", "resume", "--", id]);
            var resumed = await Alert(reopened, id);
            Require(resumed.GetProperty("state").GetString() == "triggered" && resumed.GetProperty("triggered_at").GetString() == triggered,
                "Resume cleared trigger history and could duplicate notifications.");
            using var filtered = JsonDocument.Parse(await reopened.RunAsync(["alerts", "list", "--state", "triggered", "--json"]));
            Require(filtered.RootElement.GetArrayLength() == 1, "Triggered state filter lost the resumed alert.");
            await client.RunAsync(["alerts", "rearm", "--", id]);
            var rearmed = await Alert(reopened, id);
            Require(rearmed.GetProperty("active").GetBoolean() && rearmed.GetProperty("state").GetString() == "armed" &&
                rearmed.GetProperty("triggered_at").GetString() == "", "Explicit rearm did not clear history and activate the alert.");
            await client.RunAsync(["alerts", "edit", "--note", "", "--", id]);
            Require((await Alert(reopened, id)).GetProperty("note").GetString() == "", "Empty note did not clear the saved note.");
            try { await client.RunAsync(["alerts", "edit", "--threshold", "0", "--", id]); throw new Exception("Invalid alert threshold accepted."); }
            catch (BackendRejectedException) { }
            Require((await Alert(reopened, id)).GetProperty("threshold").GetDecimal() == 123.45m, "Rejected edit changed the threshold.");
            Console.WriteLine("PASS: literal alert edits, pause/resume history preservation, explicit rearm, note clearing, state filtering, and rejected edits persist through real offline CLI calls.");
        }
        finally { scratch.Delete(recursive: true); }
    }

    private static async Task<string[]> Saved(BackendClient client)
    {
        using var document = JsonDocument.Parse(await client.RunAsync(["watch", "list", "--json"]));
        return document.RootElement.EnumerateArray().Select(item => item.GetString()!).ToArray();
    }
    private static async Task<JsonElement> Alert(BackendClient client, string id)
    {
        using var document = JsonDocument.Parse(await client.RunAsync(["alerts", "show", "--json", "--", id]));
        return document.RootElement.Clone();
    }
    private static void Require(bool condition, string message) { if (!condition) throw new Exception(message); }
}
