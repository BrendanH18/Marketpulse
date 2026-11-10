using System.Text.Json;
using Avalonia.Controls;
using Avalonia.Layout;
using Avalonia.Platform.Storage;

namespace MarketPulse.Demo;

public partial class MainWindow
{
    private JsonElement? _tax;
    private string? _taxRevision;
    private string? _taxError;
    private string? _taxMessage;
    private int? _taxYear;
    private bool _taxLoading;
    private bool _taxPickingFile;
    private readonly List<Button> _taxButtons = [];
    private Button? _taxExportButton;
    private bool TaxSelected => Navigation.SelectedIndex == 6;

    private void InvalidateTax(string? revision)
    {
        if (!string.IsNullOrEmpty(revision) && revision == _taxRevision) return;
        _taxRevision = revision;
        _tax = null;
        _taxError = null;
        _taxMessage = null;
    }

    // Navigation can happen during a portfolio refresh. Await it, then reconsider the
    // selected workspace instead of losing that request or running two Python processes.
    private async Task EnsureTaxAsync(bool force = false)
    {
        while (!_operation.IsCompleted)
        {
            try { await _operation; } catch (Exception) { }
            if (_stopping) return;
        }
        if (_stopping || !PrivacyToggle.IsEnabled) return;
        _operation = LoadTaxIfNeededAsync(force);
        await _operation;
    }

    private async Task LoadTaxIfNeededAsync(bool force = false)
    {
        if (_stopping || !TaxSelected || Privacy || _snapshot is null || _taxLoading ||
            (!force && (_tax is not null || _taxError is not null))) return;
        _taxLoading = true;
        _tax = null;
        _taxError = null;
        _taxMessage = null;
        Render();
        Busy(true);
        try { _tax = await _client.TaxAsync(_lifetime.Token); }
        catch (Exception error)
        {
            if (!_stopping) _taxError = error is OperationCanceledException
                ? "The tax request was cancelled. Try again." : error.Message;
        }
        finally
        {
            _taxLoading = false;
            if (!_stopping) { Render(); Busy(false); }
        }
    }

    private void TaxBusy(bool busy)
    {
        foreach (var button in _taxButtons) button.IsEnabled = !busy && !_taxLoading && !_taxPickingFile;
        if (_taxExportButton is { } export)
            export.IsEnabled = export.IsEnabled && !_client.IsDemo && !Privacy;
    }

    private void Tax()
    {
        Heading("Tax");
        if (_taxLoading)
        {
            Paragraph("Working out your capital gains…");
            Workspace.Children.Add(new ProgressBar { IsIndeterminate = true });
            return;
        }
        if (_taxError is { } error)
        {
            Section("Couldn't work out your capital gains");
            Paragraph(error);
            TaxAction("Try again", () => EnsureTaxAsync(force: true));
            return;
        }
        if (_tax is not { } report)
        {
            Paragraph("Your tax report will load when the current operation finishes.");
            return;
        }

        var years = Rows(report, "years").OrderByDescending(y => Get(y, "year").GetInt32()).ToArray();
        if (years.Length > 0)
        {
            if (!years.Any(y => Get(y, "year").GetInt32() == _taxYear))
                _taxYear = Get(years[0], "year").GetInt32();
            var picker = new ComboBox
            {
                Name = "TaxYearPicker",
                ItemsSource = years.Select(y => Get(y, "year").GetInt32()).ToArray(),
                SelectedItem = _taxYear,
                HorizontalAlignment = HorizontalAlignment.Left,
                MinWidth = 120,
            };
            Workspace.Children.Add(new Label { Content = "Tax year", Target = picker });
            Workspace.Children.Add(picker);
            picker.SelectionChanged += (_, _) =>
            {
                if (picker.SelectedItem is not int selected || selected == _taxYear) return;
                _taxYear = selected;
                _taxMessage = null;
                Render();
            };
            TaxAction("Recalculate", () => EnsureTaxAsync(force: true));
            _taxExportButton = TaxAction("Export CSV…", ExportTaxAsync);
            if (_client.IsDemo) Paragraph("CSV export is available for your own portfolio. The demo is read-only.");
            else Paragraph("CSV export recalculates the selected year using current exchange-rate availability. Unknown amounts are left blank; review the file and any warnings before using it.");
            TaxYearReport(years.First(y => Get(y, "year").GetInt32() == _taxYear), Text(report, "base_currency"));
        }
        else
        {
            Section("No sales in taxable accounts yet");
            Paragraph("Gains and losses from non-registered accounts appear here, using pooled cost base and each trade day's exchange rate. Gains inside a TFSA, RRSP, or FHSA aren't listed.");
            TaxAction("Recalculate", () => EnsureTaxAsync(force: true));
        }
        if (_taxMessage is { } message) { Section("CSV export"); Paragraph(message); }
        var issues = Rows(report, "issues").ToArray();
        if (issues.Length > 0)
        {
            Section("Needs attention · may change these figures");
            foreach (var issue in issues) Paragraph(Text(issue, "date") + " · " + Text(issue, "message"));
        }
        foreach (var note in Rows(report, "notes")) Paragraph(note.GetString() ?? "");
    }

    private void TaxYearReport(JsonElement year, string currency)
    {
        Paragraph("Amounts in " + currency + " · pooled cost base · includes taxable activity from archived accounts without their names.");
        Metric("Net capital gain", Signed(year, "net_gain") + " " + currency);
        Metric("Taxable capital gain", Money(year, "taxable") + " " + currency);
        Line("Proceeds", Money(year, "proceeds"));
        Line("Cost base", Money(year, "acb"));
        Line("Denied losses", Money(year, "denied"));
        // Percentage formatting only; the engine owns every financial calculation.
        Paragraph("Inclusion rate: " + (Decimal(year, "inclusion_rate")?.ToString("P2") ?? "—"));
        if (Decimal(year, "missing_fx") > 0)
            Paragraph(Number(year, "missing_fx") + " dispositions are missing an exchange rate and are left out of these totals. Unknown amounts show —. Recalculate when online.");
        Section("Realized gains by security");
        foreach (var security in Rows(year, "securities"))
            Card(Text(security, "symbol") + " · " + Number(security, "dispositions") + " dispositions",
                "Proceeds " + Money(security, "proceeds") + " · Cost base " + Money(security, "acb"),
                "Denied " + Money(security, "denied") + " · Gain / loss " + Signed(security, "net_gain"),
                Decimal(security, "missing_fx") > 0 ? "Incomplete: missing exchange rates; affected amounts are excluded from totals." : "");
        Section("Disposition details");
        foreach (var row in Rows(year, "rows"))
        {
            var account = Flag(row, "archived") ? "Archived account" : Text(row, "account", "Account");
            Card(Text(row, "date") + " · " + Text(row, "symbol") + " · " + account,
                Text(row, "kind") + " · " + Number(row, "quantity") + " units · " + Text(row, "currency") + " at " + Number(row, "fx"),
                "Proceeds " + Money(row, "proceeds") + " · Cost base " + Money(row, "acb"),
                "Gain / loss " + Signed(row, "gain") + " · Denied " + Money(row, "denied") + " · Reported gain / loss " + Signed(row, "allowed_gain"),
                !Flag(row, "complete") ? "Missing exchange rate: amounts are unknown and excluded from totals." : Text(row, "note"),
                TaxLossExplanation(row));
        }
    }

    private static string TaxLossExplanation(JsonElement row)
    {
        if (Text(row, "denied_reason") == "registered")
            return "This loss is denied permanently because the investment moved into a registered account.";
        if (!Flag(row, "superficial")) return "";
        return "Superficial loss: " + Money(row, "denied") + " denied. Sold " + Number(row, "quantity") +
            " units, acquired " + Number(row, "acquired_in_window") + " within 30 days before or after, and held " +
            Number(row, "held_after_window") + " 30 days later." +
            (Flag(row, "window_open") ? " The 30-day window is still open, so these figures can change." : "");
    }

    private Button TaxAction(string label, Func<Task> action)
    {
        var button = new Button { Content = label, HorizontalAlignment = HorizontalAlignment.Left };
        button.Click += async (_, _) =>
        {
            try { await action(); }
            catch (Exception error)
            {
                if (_stopping) return;
                _taxMessage = error.Message;
                Render();
                SetStatus(error.Message);
            }
        };
        _taxButtons.Add(button);
        Workspace.Children.Add(button);
        return button;
    }

    private async Task ExportTaxAsync()
    {
        if (_client.IsDemo || Privacy || _taxYear is not { } year || _tax is null ||
            _taxPickingFile || !_operation.IsCompleted || _stopping) return;
        var revision = _taxRevision;
        _taxMessage = null;
        _taxPickingFile = true;
        Render();
        TaxBusy(false);
        try
        {
            if (!StorageProvider.CanSave) throw new InvalidOperationException("Saving files is unavailable on this desktop.");
            var file = await StorageProvider.SaveFilePickerAsync(new FilePickerSaveOptions
            {
                Title = "Export capital gains",
                SuggestedFileName = $"marketpulse-capital-gains-{year}.csv",
                DefaultExtension = "csv",
                FileTypeChoices = [new FilePickerFileType("CSV files") { Patterns = ["*.csv"] }],
                ShowOverwritePrompt = true,
            });
            if (_stopping || Privacy) return;
            if (file is null) { SetStatus("CSV export cancelled."); return; }
            var path = file.TryGetLocalPath() ?? throw new InvalidOperationException("Choose a file on this computer.");
            while (!_operation.IsCompleted)
            {
                try { await _operation; } catch (Exception) { }
                if (_stopping || Privacy) return;
            }
            if (_tax is null || revision != _taxRevision)
                throw new InvalidOperationException("Your tax report changed. Review it before exporting again.");
            _operation = ExportTaxCoreAsync(year, path);
            await _operation;
        }
        finally
        {
            _taxPickingFile = false;
            if (!_stopping) TaxBusy(!_operation.IsCompleted);
        }
    }

    private async Task ExportTaxCoreAsync(int year, string path)
    {
        Busy(true);
        _taxMessage = "Exporting CSV…";
        Render();
        try
        {
            var result = await _client.ExportTaxCsvAsync(year, path, _lifetime.Token);
            _taxMessage = "Exported " + Number(result, "exported") + " dispositions for " + year + " to " + Path.GetFileName(path) + ".";
            _taxMessage += " The CSV was recalculated; check for blank amounts where exchange rates were unavailable.";
            var missing = _tax is { } report ? Rows(report, "years").FirstOrDefault(y => Get(y, "year").GetInt32() == year) : default;
            if (Decimal(missing, "missing_fx") > 0)
                _taxMessage += " Missing exchange rates leave amounts blank in affected rows; those rows are excluded from the report totals.";
            foreach (var issue in Rows(result, "issues"))
                _taxMessage += "\nNeeds attention: " + Text(issue, "date") + " · " + Text(issue, "message");
        }
        catch (Exception error)
        {
            if (!_stopping) _taxMessage = "CSV export failed: " + error.Message;
        }
        finally
        {
            if (!_stopping) { Render(); SetStatus(_taxMessage ?? "CSV export finished."); Busy(false); }
        }
    }
}
