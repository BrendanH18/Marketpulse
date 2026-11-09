using System.Globalization;
using System.Text.Json;
using Avalonia;
using Avalonia.Controls;
using Avalonia.Interactivity;
using Avalonia.Layout;
using Avalonia.Media;
using Avalonia.Platform.Storage;
using Avalonia.Threading;

namespace MarketPulse.Demo;

public partial class MainWindow : Window
{
    private readonly CancellationTokenSource _lifetime = new();
    private readonly BackendClient _client = Program.Client;
    private Task _operation = Task.CompletedTask;
    private JsonElement? _snapshot;
    private bool _stopping;
    private bool _loaded;
    private bool _privacyInitialized;
    private bool _settingPrivacy;
    private readonly DispatcherTimer _refreshTimer = new() { Interval = TimeSpan.FromMinutes(5) };
    private readonly List<Button> _writeButtons = [];
    public event Action<string>? StatusChanged;
    public bool Privacy => PrivacyToggle.IsChecked == true;
    public string TrayStatus { get; private set; } = "MarketPulse · loading";
    private static readonly CultureInfo Invariant = CultureInfo.InvariantCulture;

    public MainWindow()
    {
        InitializeComponent();
        Subtitle.Text = _client.IsDemo ? "Fictional portfolio · read-only offline demo" : "Your portfolio, on your computer";
        _refreshTimer.Tick += async (_, _) => await RefreshAsync();
        Opened += async (_, _) => { if (!_loaded) { _loaded = true; await RefreshAsync(); _refreshTimer.Start(); } };
    }

    public Task RefreshAsync()
    {
        if (_stopping || !_operation.IsCompleted) return Task.CompletedTask;
        return _operation = RefreshCoreAsync();
    }

    public async Task StopAsync()
    {
        if (_stopping) return;
        _stopping = true;
        _refreshTimer.Stop();
        _lifetime.Cancel();
        try { await _operation; } catch (Exception) { /* Exit still completes if an in-flight write fails. */ }
        _lifetime.Dispose();
    }

    private void Busy(bool busy)
    {
        RefreshButton.IsEnabled = !busy;
        foreach (var button in _writeButtons) button.IsEnabled = !busy && !_client.IsDemo;
    }

    private async Task LoadAsync()
    {
        _snapshot = await _client.SnapshotAsync(_lifetime.Token);
        if (!_privacyInitialized)
        {
            _privacyInitialized = true;
            _settingPrivacy = true;
            PrivacyToggle.IsChecked = Flag(Get(_snapshot.Value, "settings"), "privacy");
            _settingPrivacy = false;
        }
        Render();
        SetStatus(_client.IsDemo ? "Fictional data · offline demo" : $"Updated {DateTime.Now:t} · close the window to keep MarketPulse in the tray.");
    }

    private async Task RefreshCoreAsync()
    {
        Busy(true);
        SetStatus("Refreshing portfolio…");
        try { await LoadAsync(); }
        catch (OperationCanceledException) { if (!_stopping) Failed("The refresh took too long. Try again."); }
        catch (Exception error) { if (!_stopping) Failed(error.Message); }
        finally { Busy(false); }
    }

    private void Failed(string message)
    {
        _snapshot = null;
        Render();
        SetStatus(Privacy ? "Couldn't refresh. Turn privacy off to see details." : $"Couldn't refresh: {message}");
    }

    private Task MutateAsync(IReadOnlyList<string> arguments)
    {
        if (_client.IsDemo) throw new InvalidOperationException("The fictional demo is read-only.");
        if (_stopping || !_operation.IsCompleted) throw new InvalidOperationException("Wait for the current operation to finish.");
        return _operation = MutateCoreAsync(arguments);
    }

    private async Task MutateCoreAsync(IReadOnlyList<string> arguments)
    {
        Busy(true);
        try
        {
            await _client.RunAsync(arguments, _lifetime.Token);
            // A successful write stays successful even if the following quote refresh fails.
            try { await LoadAsync(); }
            catch (Exception error) { Failed($"The change was saved, but refreshing failed: {error.Message}"); }
        }
        finally { Busy(false); }
    }

    private Task<string> PreviewAsync(IReadOnlyList<string> arguments)
    {
        if (_stopping || !_operation.IsCompleted)
            throw new InvalidOperationException("Wait for the current operation to finish.");
        var request = PreviewCoreAsync(arguments);
        _operation = request;
        return request;
    }

    private async Task<string> PreviewCoreAsync(IReadOnlyList<string> arguments)
    {
        Busy(true);
        try { return await _client.RunAsync(arguments, _lifetime.Token); }
        finally { Busy(false); }
    }

    private void SetStatus(string text)
    {
        Status.Text = Privacy ? "Privacy is on · portfolio details hidden" : text;
        var status = _snapshot is { } root ? Get(root, "status") : default;
        TrayStatus = Privacy ? "MarketPulse · private" : _snapshot is null ? "MarketPulse · unavailable"
            : $"MarketPulse · {Money(status, "net_worth")} {Text(status, "base")}{(Flag(status, "stale") ? " · stale" : "")}";
        StatusChanged?.Invoke(TrayStatus);
    }

    private async void PrivacyChanged(object? sender, RoutedEventArgs args)
    {
        if (Workspace is null) return;
        Render();
        SetStatus(Privacy ? "Privacy is on" : "Privacy is off");
        if (_settingPrivacy || !_privacyInitialized || _client.IsDemo) return;
        var desired = Privacy;
        PrivacyToggle.IsEnabled = false;
        try
        {
            // Wait for an existing operation without delaying the immediate screen/tray mask.
            try { await _operation; } catch (Exception) { }
            if (_stopping) return;
            await MutateAsync(["config", "set", "--", "privacy", desired ? "true" : "false"]);
        }
        catch (Exception error) { SetStatus("Privacy changed for this session, but saving the setting failed: " + error.Message); }
        finally { PrivacyToggle.IsEnabled = true; }
    }
    private void WorkspaceChanged(object? sender, SelectionChangedEventArgs args) { if (Workspace is not null) Render(); }
    private async void RefreshClicked(object? sender, RoutedEventArgs args) => await RefreshAsync();

    private void Render()
    {
        Workspace.Children.Clear();
        _writeButtons.Clear();
        if (Privacy)
        {
            Heading("Your portfolio is hidden");
            Paragraph("Turn Privacy off to see balances, holdings, activity, and account details.");
            return;
        }
        if (_snapshot is not { } root)
        {
            Heading("Your portfolio");
            Paragraph("Refresh to load your portfolio. No balance is shown until the engine returns a valid snapshot.");
            return;
        }
        var status = Get(root, "status");
        switch (Navigation.SelectedIndex)
        {
            case 1: Holdings(root); break;
            case 2: Activity(root); break;
            case 3: Accounts(root); break;
            case 4: Watchlist(root); break;
            case 5: Income(root); break;
            case 6: Automation(root); break;
            default:
                Heading("Overview");
                Metric("Net worth", Money(status, "net_worth") + " " + Text(status, "base"));
                Metric("Today", Signed(status, "day_change") + " · " + Number(status, "day_change_pct") + "%");
                Metric("Unrealized gain / loss", Signed(status, "unrealized"));
                Metric("Income this year", Money(status, "income_ytd"));
                Actions(("Record transaction", () => RecordAsync()), ("Import CSV", ImportAsync));
                Section("Accounts");
                foreach (var row in Rows(status, "accounts")) Line(Text(row, "name"), Money(row, "value") + " " + Text(status, "base"));
                Section("Allocation");
                foreach (var row in Rows(root, "allocation")) Line(Text(row, "label"), Money(row, "value") + " · " + Number(row, "weight") + "%");
                Section("Value history");
                foreach (var row in Rows(status, "history").TakeLast(12).Reverse()) Line(Text(row, "date"), Money(row, "value"));
                if (!Rows(status, "history").Any()) Paragraph("Daily values appear after complete, fresh valuations.");
                break;
        }
        var warnings = Rows(root, "warnings").Select(x => x.GetString() ?? "").ToArray();
        if (warnings.Length > 0) { Section("Needs attention"); foreach (var warning in warnings) Paragraph(warning); }
        if (Flag(status, "stale")) Paragraph("Prices include cached quotes. Stale prices do not trigger alerts or record daily snapshots.");
        Busy(!_operation.IsCompleted);
    }

    private void Holdings(JsonElement root)
    {
        Heading("Holdings");
        Paragraph("Values and gains use your portfolio's base currency; prices use each holding's currency.");
        foreach (var row in Rows(root, "positions"))
            Card(Text(row, "symbol") + " · " + Text(row, "account"), Text(row, "name"),
                "Quantity " + Number(row, "quantity") + " · Price " + Money(row, "price") + " " + Text(row, "currency"),
                "Value " + Money(row, "value") + " · Book " + Money(row, "book") + " · Gain " + Signed(row, "gain") + " (" + Number(row, "gain_pct") + "%)",
                Flag(row, "stale") ? "Cached price · " + Text(row, "quote_source") : Text(row, "quote_source"));
        if (!Rows(root, "positions").Any()) Paragraph("No holdings yet. Record a transaction or import a CSV to get started.");
        Actions(("Record transaction", () => RecordAsync()));
    }

    private void Activity(JsonElement root)
    {
        Heading("Activity");
        Actions(("Record transaction", () => RecordAsync()), ("Import CSV", ImportAsync));
        var accounts = AccountNames(root);
        foreach (var row in Rows(root, "activity"))
        {
            var direction = Decimal(row, "direction");
            var value = (direction < 0 ? "−" : direction > 0 ? "+" : "") + Money(row, "value");
            var id = Text(row, "account_id");
            Card(Text(row, "date") + " · " + Text(row, "type") + " · " + Text(row, "symbol"),
                accounts.GetValueOrDefault(id, "Account") + (accounts.ContainsKey(Text(row, "target_account_id")) ? " → " + accounts[Text(row, "target_account_id")] : ""),
                value + " " + Text(row, "currency") + " · Quantity " + Number(row, "quantity"), Text(row, "note"));
            Actions(("Edit", () => RecordAsync(row)), ("Delete", () => DeleteTransactionAsync(row)));
        }
        if (!Rows(root, "activity").Any()) Paragraph("No transactions yet.");
    }

    private void Accounts(JsonElement root)
    {
        Heading("Accounts");
        Actions(("Add account", () => AccountAsync()));
        foreach (var row in Rows(root, "accounts"))
        {
            Card(Text(row, "name"), Text(row, "type") + " · " + Text(row, "currency") + " · " + Text(row, "institution"),
                Flag(row, "track_cash") ? "Cash tracking enabled" : "Fully invested account");
            Actions(("Edit account", () => AccountAsync(row)), ("Archive", () => ArchiveAsync(row)));
        }
        Section("Contribution room");
        foreach (var row in Rows(root, "room"))
            Card(Text(row, "account_type") + " · " + Text(row, "as_of_year"), "Remaining " + Money(row, "remaining"), "Contributions " + Money(row, "contributions"));
        Actions(("Set contribution room", RoomAsync));
    }

    private void Watchlist(JsonElement root)
    {
        Heading("Watchlist & alerts");
        Actions(("Add symbol", () => WatchSymbolAsync(false)), ("Remove symbol", () => WatchSymbolAsync(true)), ("Add alert", AlertAsync));
        foreach (var row in Rows(Get(root, "status"), "watchlist"))
        {
            Card(Text(row, "symbol") + " · " + Text(row, "name"), Money(row, "price") + " " + Text(row, "currency") + " · " + Number(row, "change_pct") + "%");
            Actions(("Remove symbol", () => ConfirmAsync("Remove from watchlist?", "This does not change your holdings.", ["watch", "rm", "--", Text(row, "symbol")])));
        }
        Section("Price alerts");
        Paragraph("Alerts are checked on refresh and while the app stays running. Windows toast notifications are not yet available; fired alerts are listed under Automation.");
        foreach (var row in Rows(root, "alerts"))
        {
            Card(Text(row, "description"), Flag(row, "active") ? "Active" : "Inactive", Text(row, "note"));
            Actions(("Remove alert", () => ConfirmAsync("Remove alert?", Text(row, "description"), ["alerts", "rm", "--", Text(row, "id")])));
        }
    }

    private void Income(JsonElement root)
    {
        Heading("Income");
        Metric("Year to date", Money(Get(root, "status"), "income_ytd") + " " + Text(Get(root, "status"), "base"));
        foreach (var row in Rows(root, "income_months")) Line(Text(row, "date"), Money(row, "value"));
        if (!Rows(root, "income_months").Any()) Paragraph("Recorded dividends and interest will appear here by month.");
    }

    private void Automation(JsonElement root)
    {
        Heading("Automation");
        var row = Get(root, "automation");
        Line("Last refresh", Text(row, "last_run"));
        Line("Daily snapshot", Text(row, "snapshot_date"));
        Line("Latest backup", Text(row, "backup"));
        Line("Cached prices", Text(row, "stale_count"));
        Paragraph("Refresh runs valuation, eligible daily snapshots, price-alert checks, and safety backups. These also run every five minutes while MarketPulse stays open.");
        Actions(("Back up now", () => ConfirmAsync("Back up your ledger?", "Create a backup in your configured backup folder.", ["backup", "now"])));
        foreach (var key in new[] { "fired", "errors", "quote_errors" })
        {
            Section(key == "fired" ? "Fired alerts" : key == "errors" ? "Maintenance errors" : "Quote errors");
            foreach (var item in Rows(row, key)) Paragraph(item.GetString() ?? "");
        }
    }

    private async Task AccountAsync(JsonElement? editing = null)
    {
        var row = editing ?? default;
        var dialog = new EntryDialog(editing is null ? "Add account" : "Edit account");
        var name = dialog.Text("Account name", Text(row, "name"));
        var type = dialog.Choice("Account type", ["TFSA", "RRSP", "FHSA", "RESP", "LIRA", "RRIF", "NONREG", "MARGIN", "CRYPTO", "CASH", "OTHER"], Text(row, "type"));
        var currency = dialog.Text("Currency", Text(row, "currency", "CAD"));
        var institution = dialog.Text("Institution", Text(row, "institution"));
        var cash = dialog.Check("Track a cash balance", Flag(row, "track_cash"));
        dialog.Submit = () =>
        {
            var values = new List<string> { "accounts", editing is null ? "add" : "edit", "--type", Pick(type), "--currency", Value(currency), "--institution", Value(institution) };
            if (editing is null) { if (cash.IsChecked == true) values.Add("--track-cash"); values.AddRange(["--", Required(name, "Account name")]); }
            else values.AddRange(["--name", Required(name, "Account name"), cash.IsChecked == true ? "--track-cash" : "--no-track-cash", "--revision", Text(row, "revision"), "--", Text(row, "id")]);
            return MutateAsync(values);
        };
        await dialog.ShowDialog(this);
    }

    private Task ArchiveAsync(JsonElement row) => ConfirmAsync("Archive account?", "This account and its activity will be hidden, and its holdings and cash will leave your totals. The ledger is preserved.",
        ["accounts", "edit", "--archive", "--revision", Text(row, "revision"), "--", Text(row, "id")]);

    private Task DeleteTransactionAsync(JsonElement row) => ConfirmAsync("Delete transaction?", "The engine refuses deletion if a later transaction depends on this entry. This action removes the entry from your ledger.",
        ["txn", "delete", "--yes", "--revision", Text(row, "revision"), "--", Text(row, "id")]);

    private async Task RoomAsync()
    {
        var dialog = new EntryDialog("Set contribution room");
        dialog.Explain("Enter the room reported by CRA as of January 1. MarketPulse calculates usage from your ledger.");
        var type = dialog.Choice("Account type", ["TFSA", "RRSP", "FHSA", "RESP"]);
        var year = dialog.Text("Year", DateTime.Today.Year.ToString(Invariant));
        var amount = dialog.Text("CRA reported room", "", "0.00");
        dialog.Submit = () => MutateAsync(["accounts", "room", "--", Pick(type), Required(year, "Year"), Numeric(amount, "Room")]);
        await dialog.ShowDialog(this);
    }

    private async Task WatchSymbolAsync(bool remove)
    {
        var dialog = new EntryDialog(remove ? "Remove from watchlist" : "Add to watchlist");
        var symbol = dialog.Text("Symbol", "", "XEQT.TO");
        dialog.Submit = () => MutateAsync(["watch", remove ? "rm" : "add", "--", Required(symbol, "Symbol")]);
        await dialog.ShowDialog(this);
    }

    private async Task AlertAsync()
    {
        var dialog = new EntryDialog("Add price alert");
        var symbol = dialog.Text("Symbol", "", "XEQT.TO");
        var condition = dialog.Choice("Condition", ["above", "below", "up_pct", "down_pct"]);
        var threshold = dialog.Text("Threshold (price or percent)");
        var note = dialog.Text("Note");
        dialog.Submit = () => MutateAsync(["alerts", "add", "--note", Value(note), "--", Required(symbol, "Symbol"), Pick(condition), Numeric(threshold, "Threshold")]);
        await dialog.ShowDialog(this);
    }

    private async Task ConfirmAsync(string title, string explanation, IReadOnlyList<string> arguments)
    {
        var dialog = new EntryDialog(title, "Confirm");
        dialog.Explain(explanation);
        dialog.Submit = () => MutateAsync(arguments);
        await dialog.ShowDialog(this);
    }

    private async Task RecordAsync(JsonElement? editing = null)
    {
        if (_snapshot is not { } snapshot) return;
        var accounts = Rows(snapshot, "accounts").ToArray();
        if (accounts.Length == 0) { await AccountAsync(); return; }
        var row = editing ?? default;
        var kind = Text(row, "type", "BUY");
        var editable = new[] { "BUY", "SELL", "DEPOSIT", "WITHDRAWAL", "DIVIDEND", "INTEREST", "FEE" };
        if (editing is not null && !editable.Contains(kind))
        {
            var explanation = new EntryDialog("Edit this transaction", "Done");
            explanation.Explain("Transfers, splits, DRIPs, returns of capital, and valuations can be deleted and recorded again. Their type cannot be changed.");
            explanation.Submit = () => Task.CompletedTask;
            await explanation.ShowDialog(this); return;
        }
        var dialog = new EntryDialog(editing is null ? "Record transaction" : "Edit transaction");
        var type = dialog.Choice("Transaction type", editing is null ? ["BUY", "SELL", "DEPOSIT", "WITHDRAWAL", "DIVIDEND", "INTEREST", "FEE", "DRIP", "TRANSFER", "SPLIT", "ROC"] : [kind], kind);
        var accountItems = accounts.Select(a => Text(a, "id") + " · " + Text(a, "name")).ToArray();
        var selected = accountItems.FirstOrDefault(x => x.StartsWith(Text(row, "account_id") + " · ", StringComparison.Ordinal));
        var account = dialog.Choice("Account (source for transfers)", accountItems, selected);
        var target = dialog.Choice("Destination account (transfers only)", accountItems);
        var date = dialog.Text("Date (YYYY-MM-DD)", Text(row, "date", DateTime.Today.ToString("yyyy-MM-dd", Invariant)));
        var symbol = dialog.Text("Symbol", Text(row, "symbol"));
        var quantity = dialog.Text("Quantity (trades, DRIPs, transfers)", InputNumber(row, "quantity"));
        var price = dialog.Text("Unit price (trades, DRIPs, transfers)", InputNumber(row, "price"));
        var amount = dialog.Text("Amount (cash events, return of capital)", InputNumber(row, "amount"));
        var ratio = dialog.Text("Split ratio (new shares per old share)", "2");
        var fees = dialog.Text("Fees (buy / sell)", InputNumber(row, "fees", "0"));
        var currency = dialog.Text("Currency", Text(row, "currency", "CAD"));
        var note = dialog.Text("Note", Text(row, "note"));
        dialog.Explain("Enter explicit prices and currency. Transfers between registered and taxable accounts require their market price for tax. Only fields used by the chosen type are saved.");
        List<string>? intent = null;
        dialog.Submit = () =>
        {
            if (intent is null)
            {
                var selectedType = Pick(type);
                var command = selectedType == "WITHDRAWAL" ? "withdraw" : selectedType.ToLowerInvariant();
                var accountId = Pick(account).Split(" · ")[0];
                var values = new List<string>();
                var common = new[] { "--date", Required(date, "Date"), "--note", Value(note) };
                if (editing is not null)
                {
                    values.AddRange(["txn", "edit", "--account", accountId, "--revision", Text(row, "revision")]);
                    values.AddRange(common);
                    values.AddRange(["--currency", Required(currency, "Currency")]);
                    if (selectedType is "BUY" or "SELL" or "DIVIDEND") values.AddRange(["--symbol", Required(symbol, "Symbol")]);
                    if (selectedType is "BUY" or "SELL") values.AddRange(["--quantity", Numeric(quantity, "Quantity"), "--price", Numeric(price, "Price"), "--fees", Numeric(fees, "Fees")]);
                    else values.AddRange(["--amount", Numeric(amount, "Amount")]);
                    values.AddRange(["--", Text(row, "id")]);
                }
                else
                {
                    values.AddRange([command, "--request-id", Guid.NewGuid().ToString()]);
                    values.AddRange(common);
                    if (selectedType == "TRANSFER") values.AddRange(["--from", accountId, "--to", Pick(target).Split(" · ")[0], "--price", Numeric(price, "Market price")]);
                    else values.AddRange(["--account", accountId]);
                    if (selectedType != "SPLIT") values.AddRange(["--currency", Required(currency, "Currency")]);
                    if (selectedType is "BUY" or "SELL") values.AddRange(["--fees", Numeric(fees, "Fees")]);
                    values.Add("--");
                    if (selectedType is "BUY" or "SELL" or "DRIP" or "TRANSFER" or "SPLIT" or "ROC" or "DIVIDEND") values.Add(Required(symbol, "Symbol"));
                    if (selectedType is "BUY" or "SELL" or "DRIP") values.AddRange([Numeric(quantity, "Quantity"), Numeric(price, "Price")]);
                    else if (selectedType == "TRANSFER") values.Add(Numeric(quantity, "Quantity"));
                    else if (selectedType == "SPLIT") values.Add(Numeric(ratio, "Split ratio"));
                    else values.Add(Numeric(amount, "Amount"));
                }
                intent = values;
                dialog.Freeze();
                dialog.Explain("Retry submits this same entry safely. Close and reopen to start a different entry.");
            }
            return MutateAsync(intent);
        };
        await dialog.ShowDialog(this);
    }

    private async Task ImportAsync()
    {
        var files = await StorageProvider.OpenFilePickerAsync(new FilePickerOpenOptions
        {
            Title = "Import transactions", AllowMultiple = false,
            FileTypeFilter = [new FilePickerFileType("CSV files") { Patterns = ["*.csv"] }]
        });
        var path = files.FirstOrDefault()?.TryGetLocalPath();
        if (path is null || _snapshot is not { } root) return;
        var dialog = new EntryDialog("Import CSV", "Preview / import");
        dialog.Explain(Path.GetFileName(path));
        var profile = dialog.Choice("CSV profile", ["auto", "questrade", "wealthsimple", "generic"]);
        var accountRows = Rows(root, "accounts").ToArray();
        var accounts = new[] { "Use CSV account column" }.Concat(accountRows.Select(a => Text(a, "id") + " · " + Text(a, "name")));
        var account = dialog.Choice("Account for rows without one", accounts);
        var report = dialog.Text("Preview result");
        report.IsReadOnly = true;
        report.AcceptsReturn = true;
        report.MinHeight = 140;
        string? fingerprint = null;
        string? previewKey = null;
        var confirmed = dialog.Check("I reviewed the preview and want to import these rows");
        void Invalidate() { fingerprint = null; previewKey = null; report.Text = "Preview again after changing the profile or account."; confirmed.IsChecked = false; }
        profile.SelectionChanged += (_, _) => Invalidate();
        account.SelectionChanged += (_, _) => Invalidate();
        dialog.Submit = async () =>
        {
            var args = new List<string> { "desktop", "import", "--profile", Pick(profile) };
            if (account.SelectedIndex > 0) args.AddRange(["--account", Pick(account).Split(" · ")[0]]);
            var key = string.Join("\n", args);
            if (fingerprint is null || previewKey != key)
            {
                args.AddRange(["--dry-run", "--", path]);
                using var result = JsonDocument.Parse(await PreviewAsync(args));
                fingerprint = Text(result.RootElement, "fingerprint");
                if (fingerprint.Length == 0) throw new InvalidDataException("Preview did not return a fingerprint.");
                previewKey = key;
                report.Text = $"Would add {Text(result.RootElement, "added")} transactions; {Text(result.RootElement, "duplicates")} duplicates skipped.\n"
                    + string.Join("\n", Rows(result.RootElement, "issues").Select(x => "Line " + Text(x, "line") + ": " + Text(x, "reason")));
                throw new InvalidOperationException("Preview ready. Review the result, select the confirmation box, then choose Preview / import again.");
            }
            if (confirmed.IsChecked != true) throw new InvalidOperationException("Review the preview and confirm before importing.");
            args.AddRange(["--expect-fingerprint", fingerprint, "--", path]);
            try { await MutateAsync(args); }
            catch { Invalidate(); throw; }
        };
        await dialog.ShowDialog(this);
    }

    private void Heading(string text) => Workspace.Children.Add(new TextBlock { Text = text, FontSize = 28, FontWeight = FontWeight.SemiBold });
    private void Section(string text) => Workspace.Children.Add(new TextBlock { Text = text, FontSize = 18, FontWeight = FontWeight.SemiBold, Margin = new Thickness(0, 10, 0, 0) });
    private void Paragraph(string text) { if (text.Length > 0) Workspace.Children.Add(new TextBlock { Text = text, TextWrapping = TextWrapping.Wrap }); }
    private void Metric(string label, string value) => Card(label, value);
    private void Line(string label, string value)
    {
        var grid = new Grid { ColumnDefinitions = new ColumnDefinitions("*,Auto"), ColumnSpacing = 16 };
        grid.Children.Add(new TextBlock { Text = label, TextWrapping = TextWrapping.Wrap });
        var amount = new TextBlock { Text = value }; Grid.SetColumn(amount, 1); grid.Children.Add(amount);
        Workspace.Children.Add(grid);
    }
    private void Card(string title, params string[] lines)
    {
        var panel = new StackPanel { Spacing = 5 };
        panel.Children.Add(new TextBlock { Text = title, FontWeight = FontWeight.SemiBold, TextWrapping = TextWrapping.Wrap });
        foreach (var line in lines.Where(x => x.Length > 0)) panel.Children.Add(new TextBlock { Text = line, TextWrapping = TextWrapping.Wrap });
        Workspace.Children.Add(new Border { Child = panel, Padding = new Thickness(16), BorderThickness = new Thickness(1), BorderBrush = new SolidColorBrush(Color.Parse("#66808080")), CornerRadius = new CornerRadius(8) });
    }
    private void Actions(params (string Label, Func<Task> Action)[] actions)
    {
        var panel = new WrapPanel { Orientation = Orientation.Horizontal };
        foreach (var action in actions)
        {
            var button = new Button { Content = action.Label, Margin = new Thickness(0, 0, 10, 6), IsEnabled = !_client.IsDemo };
            button.Click += async (_, _) =>
            {
                try { await action.Action(); }
                catch (Exception error) { SetStatus(error.Message); }
            };
            _writeButtons.Add(button);
            panel.Children.Add(button);
        }
        Workspace.Children.Add(panel);
    }

    private static JsonElement Get(JsonElement row, string key) => row.ValueKind == JsonValueKind.Object && row.TryGetProperty(key, out var value) ? value : default;
    private static IEnumerable<JsonElement> Rows(JsonElement row, string key) { var value = Get(row, key); return value.ValueKind == JsonValueKind.Array ? value.EnumerateArray().ToArray() : []; }
    private static string Text(JsonElement row, string key, string fallback = "") { var value = Get(row, key); return value.ValueKind is JsonValueKind.Undefined or JsonValueKind.Null ? fallback : value.ToString(); }
    private static bool Flag(JsonElement row, string key) => Get(row, key).ValueKind == JsonValueKind.True;
    private static decimal? Decimal(JsonElement row, string key) { var value = Get(row, key); return value.ValueKind == JsonValueKind.Number && value.TryGetDecimal(out var amount) ? amount : null; }
    private static string Money(JsonElement row, string key) => Decimal(row, key)?.ToString("N2", CultureInfo.CurrentCulture) ?? "—";
    private static string Number(JsonElement row, string key) => Decimal(row, key)?.ToString("0.####", CultureInfo.CurrentCulture) ?? "—";
    private static string InputNumber(JsonElement row, string key, string fallback = "") => Decimal(row, key)?.ToString(CultureInfo.CurrentCulture) ?? fallback;
    private static string Signed(JsonElement row, string key) => Decimal(row, key) is { } amount ? (amount > 0 ? "+" : amount < 0 ? "−" : "") + Math.Abs(amount).ToString("N2", CultureInfo.CurrentCulture) : "—";
    private static Dictionary<string, string> AccountNames(JsonElement root) => Rows(root, "accounts").ToDictionary(x => Text(x, "id"), x => Text(x, "name"));
    private static string Value(TextBox box) => (box.Text ?? "").Trim();
    private static string Required(TextBox box, string name) => Value(box).Length > 0 ? Value(box) : throw new InvalidOperationException(name + " is required.");
    private static string Pick(ComboBox box) => box.SelectedItem?.ToString() ?? "";
    private static string Numeric(TextBox box, string name) => decimal.TryParse(Value(box), NumberStyles.Number, CultureInfo.CurrentCulture, out var number) ? number.ToString(Invariant) : throw new InvalidOperationException(name + " must be a number.");
}
