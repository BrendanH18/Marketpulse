using System.Text;
using System.Text.Json;
using MarketPulse.Demo;

internal static class BackupChecks
{
    public static async Task RunAsync(string python)
    {
        var scratch = Directory.CreateTempSubdirectory("marketpulse-windows-backup-check-");
        try
        {
            var data = Path.Combine(scratch.FullName, "--Fictional épargne $(echo nope) & data");
            var config = Path.Combine(scratch.FullName, "fictional settings.toml");
            await File.WriteAllTextAsync(config, "# Fictional backup fixture\nmarket_strip = []\ntheme = \"tokyo-night\"\n");
            var client = new BackendClient(python, dataDirectory: data, configPath: config);
            const string account = "Fictional cash";
            await client.RunAsync(["accounts", "add", "--type", "NONREG", "--currency", "CAD", "--track-cash", "--", account]);
            await client.RunAsync(["deposit", "--account", account, "--currency", "CAD", "--date", "2024-01-02", "--", "1000"]);
            var initial = await client.SnapshotAsync();
            AssertBalance(initial, 1000m, 1);
            var existing = Backups(initial).Select(row => row.GetProperty("name").GetString()).ToHashSet();

            // Discover the new backup from structured bridge metadata; CLI stdout remains opaque.
            await client.CreateBackupAsync();
            var backedUp = await client.SnapshotAsync();
            var manual = Backups(backedUp).Single(row => !existing.Contains(row.GetProperty("name").GetString()) &&
                row.GetProperty("reason").GetString() == "manual");
            if (manual.GetProperty("size").GetInt64() <= 0 ||
                !DateTime.TryParse(manual.GetProperty("taken_at").GetString(), out _))
                throw new Exception("The created backup is missing its size or creation time.");
            var source = BackupPath(backedUp, manual);
            var sourceBytes = await File.ReadAllBytesAsync(source);
            Console.WriteLine("PASS: create backup and list name, reason, size, and time from snapshot storage metadata.");

            await client.RunAsync(["deposit", "--account", account, "--currency", "CAD", "--date", "2024-01-03", "--", "2500"]);
            var later = await client.SnapshotAsync();
            AssertBalance(later, 3500m, 2);
            var keptConfig = Encoding.UTF8.GetBytes("# Keep these settings through restore: épargne\nmarket_strip = []\ntheme = \"dracula\"\nrefresh_seconds = 60\n");
            await File.WriteAllBytesAsync(config, keptConfig);
            await client.RestoreBackupAsync(source);
            var restored = await client.SnapshotAsync();
            AssertBalance(restored, 1000m, 1);
            var restoredRevision = restored.GetProperty("ledger_revision").GetString();
            if (restoredRevision == initial.GetProperty("ledger_revision").GetString() ||
                restoredRevision == later.GetProperty("ledger_revision").GetString())
                throw new Exception("Restoring a backup did not invalidate the previous ledger revisions.");
            var actualConfig = await File.ReadAllBytesAsync(config);
            var actualSource = await File.ReadAllBytesAsync(source);
            if (!keptConfig.SequenceEqual(actualConfig) || !sourceBytes.SequenceEqual(actualSource))
                throw new Exception("Restore changed the configuration or the source backup.");
            var safety = Backups(restored).Single(row => row.GetProperty("reason").GetString() == "pre-restore");
            Console.WriteLine("PASS: restore replaces later entries, preserves configuration and backup bytes, and changes ledger revision.");

            await client.RestoreBackupAsync(BackupPath(restored, safety));
            var recovered = await client.SnapshotAsync();
            AssertBalance(recovered, 3500m, 2);
            if (recovered.GetProperty("ledger_revision").GetString() == restoredRevision)
                throw new Exception("Restoring the pre-restore copy reused the previous ledger revision.");
            actualConfig = await File.ReadAllBytesAsync(config);
            if (!keptConfig.SequenceEqual(actualConfig))
                throw new Exception("Recovering the pre-restore copy changed configuration bytes.");
            Console.WriteLine("PASS: the automatic pre-restore backup recovers the later ledger state.");

            var invalid = Path.Combine(scratch.FullName, "invalid backup.db");
            await File.WriteAllTextAsync(invalid, "Fictional invalid database", Encoding.UTF8);
            foreach (var path in new[] { invalid, Path.Combine(scratch.FullName, "missing backup.db"), Path.Combine(data, "marketpulse.db") })
            {
                try
                {
                    await client.RestoreBackupAsync(path);
                    throw new Exception("An invalid, missing, or current-ledger backup was restored.");
                }
                catch (BackendRejectedException) { }
                AssertUnchanged(recovered, await client.SnapshotAsync());
            }
            Console.WriteLine("PASS: invalid, missing, and ledger-itself restore requests fail without changing ledger state.");

            var demo = new BackendClient(python, demo: true, dataDirectory: data, configPath: config);
            foreach (var action in new Func<Task<string>>[] { () => demo.CreateBackupAsync(), () => demo.RestoreBackupAsync(source) })
            {
                try { await action(); throw new Exception("A backup write was allowed in the read-only demo."); }
                catch (InvalidOperationException error) when (error.Message.Contains("read-only")) { }
            }
            using var canceled = new CancellationTokenSource();
            canceled.Cancel();
            foreach (var action in new Func<Task<string>>[]
            {
                () => client.CreateBackupAsync(canceled.Token),
                () => client.RestoreBackupAsync(source, canceled.Token),
            })
            {
                try { await action(); throw new Exception("A canceled backup request completed."); }
                catch (OperationCanceledException) { }
            }
            AssertUnchanged(recovered, await client.SnapshotAsync());
            Console.WriteLine("PASS: read-only demo and canceled backup operations leave ledger and backup list unchanged.");
        }
        finally
        {
            scratch.Delete(recursive: true);
        }
    }

    private static IEnumerable<JsonElement> Backups(JsonElement snapshot) =>
        snapshot.GetProperty("storage").GetProperty("backups").EnumerateArray();

    private static string BackupPath(JsonElement snapshot, JsonElement backup) => Path.Combine(
        snapshot.GetProperty("storage").GetProperty("backup_dir").GetString()!, backup.GetProperty("name").GetString()!);

    private static void AssertBalance(JsonElement snapshot, decimal balance, int entries)
    {
        if (snapshot.GetProperty("status").GetProperty("net_worth").GetDecimal() != balance ||
            snapshot.GetProperty("activity").GetArrayLength() != entries)
            throw new Exception("The fictional restored ledger has the wrong balance or activity entries.");
    }

    private static void AssertUnchanged(JsonElement expected, JsonElement actual)
    {
        if (expected.GetProperty("ledger_revision").GetString() != actual.GetProperty("ledger_revision").GetString() ||
            !JsonElement.DeepEquals(expected.GetProperty("activity"), actual.GetProperty("activity")) ||
            !JsonElement.DeepEquals(expected.GetProperty("accounts"), actual.GetProperty("accounts")) ||
            !JsonElement.DeepEquals(expected.GetProperty("storage").GetProperty("backups"), actual.GetProperty("storage").GetProperty("backups")))
            throw new Exception("A rejected or canceled restore changed the ledger or backup list.");
    }
}
