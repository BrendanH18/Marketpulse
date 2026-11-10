using System.Text.Json;

namespace MarketPulse.Demo;

public partial class MainWindow
{
    private string? _backupMessage;
    private bool _restoreUncertain;

    private void Backups(JsonElement root)
    {
        Section("Backups and restore");
        Paragraph("Backups contain your ledger, not your configuration. Restoring replaces later entries and saves the current ledger as a pre-restore backup first.");
        if (_backupMessage is not null) Paragraph(_backupMessage);
        if (_client.IsDemo)
        {
            Paragraph("The fictional demo is read-only. Backups and restore are available for your own portfolio.");
            return;
        }
        var storage = Get(root, "storage");
        var folder = Text(storage, "backup_dir");
        if (folder.Length == 0)
        {
            Paragraph("The engine did not return a backup folder. Refresh before managing backups.");
            return;
        }
        Paragraph("Backup folder: " + folder);
        Actions(("Back up now", CreateBackupAsync));
        var backups = Rows(storage, "backups").ToArray();
        if (backups.Length == 0) Paragraph("No backups yet. Back up now to save a copy of your ledger.");
        foreach (var backup in backups)
        {
            Card(Text(backup, "name"), "Taken " + Text(backup, "taken_at", "Unknown time")
                + " · " + BackupReason(Text(backup, "reason")) + " · " + Number(backup, "size") + " bytes");
            Actions(("Restore this backup…", () => ConfirmRestoreBackupAsync(folder, backup)));
        }
    }

    private static string BackupReason(string reason) => reason switch
    {
        "manual" => "Manual backup", "daily" => "Daily backup", "pre-import" => "Before an import",
        "pre-restore" => "Before a restore", _ => reason.StartsWith("pre-v", StringComparison.Ordinal)
            ? "Before a schema upgrade" : reason,
    };

    private Task CreateBackupAsync()
    {
        RequireBackupOperation();
        return _operation = BackupOperationCoreAsync(null);
    }

    private async Task ConfirmRestoreBackupAsync(string folder, JsonElement backup)
    {
        RequireBackupOperation();
        if (_restoreUncertain)
            throw new InvalidOperationException("A previous restore did not return a confirmed result. Refresh and inspect Activity and the pre-restore backups before restoring again.");
        var name = Text(backup, "name");
        if (name.Length == 0 || Path.GetFileName(name) != name)
            throw new InvalidDataException("The engine returned an invalid backup name. Refresh before restoring.");
        var path = Path.GetFullPath(Path.Combine(folder, name));
        var revision = _snapshot is { } root ? Text(root, "ledger_revision") : "";
        var dialog = new EntryDialog("Restore backup?", "Restore backup");
        dialog.Explain("Restore " + name + " (taken " + Text(backup, "taken_at", "Unknown time") + ") from " + folder + "?");
        dialog.Explain("This replaces your ledger, including entries recorded after this backup. Your configuration stays unchanged. The engine checks the backup and creates a pre-restore copy of the current ledger before replacing it. If validation or that safety backup fails, nothing is restored.");
        var confirmed = dialog.Check("I understand that this replaces my current ledger");
        dialog.Submit = async () =>
        {
            RequireBackupOperation();
            if (confirmed.IsChecked != true)
                throw new InvalidOperationException("Confirm that you want to replace the current ledger.");
            await (_operation = RestoreConfirmedBackupCoreAsync(folder, backup, revision, path));
        };
        await dialog.ShowDialog(this);
    }

    private async Task RestoreConfirmedBackupCoreAsync(string folder, JsonElement backup, string revision, string path)
    {
        Busy(true);
        try
        {
            // Another app or the CLI may have edited the ledger since this dialog opened.
            // Keep preflight and restore in the same operation slot; no local save/refresh can overlap.
            var current = await _client.SnapshotAsync(_lifetime.Token);
            if (_stopping || Privacy)
                throw new InvalidOperationException("Restore was not started. Turn Privacy off and select the backup again.");
            if (Text(current, "ledger_revision") != revision ||
                Text(Get(current, "storage"), "backup_dir") != folder ||
                !Rows(Get(current, "storage"), "backups").Any(row => Text(row, "name") == Text(backup, "name") &&
                    Text(row, "taken_at") == Text(backup, "taken_at") && Text(row, "size") == Text(backup, "size")))
                throw new InvalidOperationException("The portfolio or backup list changed while confirming. Cancel, refresh and select the backup again.");
            await BackupOperationCoreAsync(path);
        }
        finally { Busy(false); }
    }

    private void RequireBackupOperation()
    {
        if (_client.IsDemo) throw new InvalidOperationException("The fictional demo is read-only.");
        if (Privacy) throw new InvalidOperationException("Turn Privacy off before managing backups.");
        if (_stopping || !_operation.IsCompleted) throw new InvalidOperationException("Wait for the current operation to finish.");
        if (_snapshot is null) throw new InvalidOperationException("Refresh your portfolio before managing backups.");
    }

    private async Task BackupOperationCoreAsync(string? restorePath)
    {
        Busy(true);
        _backupMessage = null;
        try
        {
            try
            {
                if (restorePath is null) await _client.CreateBackupAsync(_lifetime.Token);
                else await _client.RestoreBackupAsync(restorePath, _lifetime.Token);
            }
            catch (Exception error)
            {
                // A timeout/crash can occur after a successful swap. Do not offer a blind retry.
                if (restorePath is not null)
                {
                    _restoreUncertain = true;
                    _snapshot = null;
                    _backupMessage = "The restore result could not be confirmed. Refresh and inspect Activity and the pre-restore backups before restoring again. " + error.Message;
                }
                else _backupMessage = "Couldn't create backup: " + error.Message;
                if (!_stopping) { Render(); SetStatus(_backupMessage); }
                throw new InvalidOperationException(_backupMessage, error);
            }
            _restoreUncertain = false;
            var success = restorePath is null ? "Backup created in your backup folder."
                : "Backup restored. The previous ledger was saved as a pre-restore backup; configuration was kept.";
            try
            {
                await LoadAsync();
                _backupMessage = success;
            }
            catch (Exception error)
            {
                // The completed write must not be reported as failed or retried on a refresh error.
                _snapshot = null;
                _backupMessage = success + " Refreshing failed: " + error.Message + " Refresh to load the current ledger.";
            }
            if (!_stopping) { Render(); SetStatus(_backupMessage); }
        }
        finally { Busy(false); }
    }
}
