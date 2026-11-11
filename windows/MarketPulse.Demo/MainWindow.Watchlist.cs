using System.Text.Json;
using Avalonia;
using Avalonia.Controls;
using Avalonia.Layout;
using Avalonia.Interactivity;

namespace MarketPulse.Demo;

public partial class MainWindow
{
    private string _alertStateFilter = "All";
    private readonly List<(Button Button, bool Available)> _watchlistButtons = [];
    private bool _alertRearmUncertain;

    private void Watchlist(JsonElement root)
    {
        Heading("Watchlist & alerts");
        WatchlistActions(("Add symbol", () => WatchSymbolAsync(false), true),
            ("Remove symbol", () => WatchSymbolAsync(true), true), ("Add alert", AlertAsync, true));
        var quotes = Rows(Get(root, "status"), "watchlist").ToDictionary(row => Text(row, "symbol"));
        // Membership includes symbols for which the engine could not obtain a quote.
        var saved = Get(root, "watchlist_symbols");
        var symbols = saved.ValueKind == JsonValueKind.Array
            ? saved.EnumerateArray().Select(value => value.GetString()!).ToArray()
            : quotes.Keys.ToArray();
        for (var index = 0; index < symbols.Length; index++)
        {
            var symbol = symbols[index];
            var position = index;
            if (quotes.TryGetValue(symbol, out var quote))
                Card(symbol + " · " + Text(quote, "name"), Money(quote, "price") + " " + Text(quote, "currency") + " · " + Number(quote, "change_pct") + "%");
            else Card(symbol, "Price unavailable. This symbol is still saved on your watchlist.");
            WatchlistActions(("Move up", () => MoveWatchSymbolAsync(symbol, position), position > 0 && saved.ValueKind == JsonValueKind.Array),
                ("Move down", () => MoveWatchSymbolAsync(symbol, position + 2), position < symbols.Length - 1 && saved.ValueKind == JsonValueKind.Array),
                ("Remove symbol", () => ConfirmWatchlistAsync("Remove from watchlist?", "This does not change your holdings.", ["watch", "rm", "--", symbol]), true));
        }
        if (saved.ValueKind != JsonValueKind.Array && symbols.Length > 0)
            Paragraph("Update the bundled engine to reorder all saved symbols, including those without prices.");
        if (symbols.Length == 0) Paragraph("Your watchlist is empty. Add a symbol to follow its price.");
        Section("Price alerts");
        Paragraph("Alerts are checked on refresh and while the app stays running. Windows toast notifications are not yet available; triggered alerts show their saved trigger time here. Automation shows alerts fired during the latest refresh.");
        Paragraph("Armed alerts can fire on a matching fresh price. Paused alerts cannot fire. Triggered alerts rearm automatically when a fresh price no longer meets their condition. Editing and resuming do not reset trigger history themselves; the following refresh evaluates enabled alerts normally.");
        var filter = new ComboBox
        {
            ItemsSource = new[] { "All", "Armed", "Paused", "Triggered" },
            SelectedItem = _alertStateFilter,
            HorizontalAlignment = HorizontalAlignment.Stretch,
        };
        Workspace.Children.Add(new Label { Content = "Alert state", Target = filter });
        Workspace.Children.Add(filter);
        filter.SelectionChanged += (_, _) =>
        {
            _alertStateFilter = Pick(filter);
            Render();
        };
        var alerts = Rows(root, "alerts").Where(row => _alertStateFilter == "All" || AlertState(row) == _alertStateFilter).ToArray();
        foreach (var row in alerts)
        {
            Card(Text(row, "description"), AlertState(row),
                Text(row, "triggered_at") is { Length: > 0 } triggered ? "Triggered " + triggered : "Not triggered",
                Text(row, "note"));
            WatchlistActions(("Edit alert", () => EditAlertAsync(row), true),
                (Flag(row, "active") ? "Pause alert" : "Resume alert", () => SetAlertActiveAsync(row), true),
                ("Rearm alert…", () => RearmAlertAsync(row), true),
                ("Remove alert", () => ConfirmWatchlistAsync("Remove alert?", Text(row, "description"), ["alerts", "rm", "--", Text(row, "id")]), true));
        }
        if (alerts.Length == 0)
            Paragraph(_alertStateFilter == "All" ? "No price alerts yet. Add an alert to get started." : "No " + _alertStateFilter.ToLowerInvariant() + " alerts match this filter.");
    }

    private static string AlertState(JsonElement row) => !Flag(row, "active") ? "Paused"
        : Text(row, "triggered_at").Length > 0 ? "Triggered" : "Armed";

    private void WatchlistBusy(bool busy)
    {
        foreach (var (button, available) in _watchlistButtons)
            button.IsEnabled = available && !busy && !_client.IsDemo && !Privacy;
    }

    private void WatchlistActions(params (string Label, Func<Task> Action, bool Available)[] actions)
    {
        var panel = new WrapPanel { Orientation = Orientation.Horizontal };
        foreach (var action in actions)
        {
            var button = new Button { Content = action.Label, Margin = new Thickness(0, 0, 10, 6) };
            button.Click += async (_, _) =>
            {
                try { RequireWatchlistWrite(); await action.Action(); }
                catch (Exception error) { SetStatus(Privacy ? "Turn Privacy off to manage your watchlist and alerts." : error.Message); }
            };
            _watchlistButtons.Add((button, action.Available));
            panel.Children.Add(button);
        }
        Workspace.Children.Add(panel);
        WatchlistBusy(!_operation.IsCompleted);
    }

    private void RequireWatchlistWrite()
    {
        if (Privacy) throw new InvalidOperationException("Turn Privacy off to manage your watchlist and alerts.");
        if (_client.IsDemo) throw new InvalidOperationException("The fictional demo is read-only.");
        if (_snapshot is null) throw new InvalidOperationException("Refresh your portfolio before making changes.");
        if (_stopping || !_operation.IsCompleted) throw new InvalidOperationException("Wait for the current operation to finish.");
    }

    private async Task ShowWatchlistDialogAsync(EntryDialog dialog)
    {
        void Mask(object? sender, RoutedEventArgs args)
        {
            if (!Privacy) return;
            dialog.Title = "Portfolio details hidden";
            var close = new Button { Content = "Close", IsCancel = true };
            close.Click += (_, _) => dialog.Close();
            var masked = new StackPanel { Margin = new Thickness(24), Spacing = 16 };
            masked.Children.Add(new TextBlock { Text = "Privacy is on. Close this dialog and turn Privacy off to make changes.", TextWrapping = Avalonia.Media.TextWrapping.Wrap });
            masked.Children.Add(close);
            dialog.Content = masked;
        }
        PrivacyToggle.IsCheckedChanged += Mask;
        try { await dialog.ShowDialog(this); }
        finally { PrivacyToggle.IsCheckedChanged -= Mask; }
    }

    private async Task ConfirmWatchlistAsync(string title, string explanation, IReadOnlyList<string> arguments)
    {
        RequireWatchlistWrite();
        var dialog = new EntryDialog(title, "Confirm");
        dialog.Explain(explanation);
        dialog.Submit = () =>
        {
            RequireWatchlistWrite();
            return MutateAsync(arguments);
        };
        await ShowWatchlistDialogAsync(dialog);
    }

    private Task MoveWatchSymbolAsync(string symbol, int position)
    {
        RequireWatchlistWrite();
        return MutateAsync(["watch", "move", "--to", position.ToString(Invariant), "--", symbol]);
    }

    private async Task WatchSymbolAsync(bool remove)
    {
        RequireWatchlistWrite();
        var dialog = new EntryDialog(remove ? "Remove from watchlist" : "Add to watchlist");
        var symbol = dialog.Text("Symbol", "", "XEQT.TO");
        dialog.Submit = () =>
        {
            RequireWatchlistWrite();
            return MutateAsync(["watch", remove ? "rm" : "add", "--", Required(symbol, "Symbol")]);
        };
        await ShowWatchlistDialogAsync(dialog);
    }

    private async Task AlertAsync()
    {
        RequireWatchlistWrite();
        var dialog = new EntryDialog("Add price alert");
        var symbol = dialog.Text("Symbol", "", "XEQT.TO");
        var condition = dialog.Choice("Condition", ["above", "below", "up_pct", "down_pct"]);
        var threshold = dialog.Text("Threshold (price or percent)");
        var note = dialog.Text("Note");
        dialog.Submit = () =>
        {
            RequireWatchlistWrite();
            return MutateAsync(["alerts", "add", "--note", Value(note), "--", Required(symbol, "Symbol"), Pick(condition), PositiveAlertThreshold(threshold)]);
        };
        await ShowWatchlistDialogAsync(dialog);
    }

    private async Task EditAlertAsync(JsonElement row)
    {
        RequireWatchlistWrite();
        var dialog = new EntryDialog("Edit price alert");
        dialog.Explain(Text(row, "description") + ". Editing does not reset trigger history. The following refresh evaluates enabled alerts normally, including automatic rearming.");
        var threshold = dialog.Text("Threshold (price or percent)", InputNumber(row, "threshold"));
        var note = dialog.Text("Note", Text(row, "note"));
        dialog.Submit = () =>
        {
            RequireWatchlistWrite();
            return MutateAsync(["alerts", "edit", "--threshold", PositiveAlertThreshold(threshold), "--note", Value(note), "--", Text(row, "id")]);
        };
        await ShowWatchlistDialogAsync(dialog);
    }

    private static string PositiveAlertThreshold(TextBox input)
    {
        var value = Numeric(input, "Threshold");
        if (decimal.Parse(value, Invariant) <= 0) throw new InvalidOperationException("Threshold must be greater than zero.");
        return value;
    }

    private Task SetAlertActiveAsync(JsonElement row)
    {
        RequireWatchlistWrite();
        return MutateAsync(["alerts", Flag(row, "active") ? "pause" : "resume", "--", Text(row, "id")]);
    }

    private async Task RearmAlertAsync(JsonElement row)
    {
        RequireWatchlistWrite();
        var dialog = new EntryDialog("Rearm alert?", "Rearm alert");
        dialog.Explain(Text(row, "description") + ". This activates the alert and clears its trigger history. The next matching fresh price can fire again. Cancel keeps the alert unchanged.");
        dialog.Submit = async () =>
        {
            RequireWatchlistWrite();
            if (_alertRearmUncertain)
                throw new InvalidOperationException("A previous rearm did not return a confirmed result. Cancel, refresh and inspect the alert before rearming again.");
            try { await MutateAsync(["alerts", "rearm", "--", Text(row, "id")]); }
            catch (Exception error) when (error is TimeoutException or OperationCanceledException)
            {
                _alertRearmUncertain = true;
                throw new InvalidOperationException("Rearm was interrupted and may have completed. Cancel, refresh and inspect the alert before trying again.", error);
            }
        };
        await ShowWatchlistDialogAsync(dialog);
    }
}
