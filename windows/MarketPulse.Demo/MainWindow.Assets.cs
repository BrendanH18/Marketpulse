using System.Globalization;
using System.Text.Json;
using Avalonia.Controls;

namespace MarketPulse.Demo;

public partial class MainWindow
{
    private static readonly string[] AssetClasses =
        ["equity", "etf", "fund", "crypto", "fixed_income", "cash", "real_estate", "commodity", "alternative", "other"];

    private static string AssetClassLabel(string key) => key == "etf" ? "ETF" :
        Invariant.TextInfo.ToTitleCase(key.Replace('_', ' '));

    private async Task AddFixedAssetAsync()
    {
        var accounts = await AssetAccountsAsync();
        if (accounts.Length == 0) return;
        var dialog = new EntryDialog("Add a GIC or bond", "Add asset");
        dialog.Explain("Its value accrues interest up to maturity. The principal is recorded as a purchase on the start date.");
        var account = AssetAccountChoice(dialog, accounts);
        var symbol = dialog.Text("Symbol", "", "GIC-2028");
        var name = dialog.Text("Name (optional)");
        var principal = dialog.Text("Principal");
        var rate = dialog.Text("Annual rate (%)");
        var start = dialog.Text("Start date (YYYY-MM-DD)", DateTime.Today.ToString("yyyy-MM-dd", Invariant));
        var maturity = dialog.Text("Maturity date (YYYY-MM-DD)", DateTime.Today.AddYears(1).ToString("yyyy-MM-dd", Invariant));
        var compounding = dialog.Choice("Compounding", ["annual", "semiannual", "quarterly", "monthly", "simple"], "annual");
        var currency = AssetCurrencyInput(dialog, accounts, account);
        ConfigureAssetSave(dialog, () =>
        {
            var code = NewAssetSymbol(symbol);
            var first = AssetDate(start, "Start date");
            var last = AssetDate(maturity, "Maturity date", allowFuture: true);
            if (string.CompareOrdinal(last, first) <= 0)
                throw new InvalidOperationException("The maturity date must be after the start date.");
            return ["asset", "fixed", "--account", AssetAccountId(account), "--name", Value(name),
                "--start", first, "--maturity", last, "--rate", AssetNumber(rate, "Annual rate", allowZero: true),
                "--compounding", Pick(compounding), "--currency", AssetCurrency(currency),
                "--", code, AssetNumber(principal, "Principal")];
        });
        await dialog.ShowDialog(this);
    }

    private async Task AddManualAssetAsync()
    {
        var accounts = await AssetAccountsAsync();
        if (accounts.Length == 0) return;
        var dialog = new EntryDialog("Add an asset you value yourself", "Add asset");
        dialog.Explain("Add property, private shares, a pension or another asset the market cannot price. Update its value when it changes.");
        var account = AssetAccountChoice(dialog, accounts);
        var symbol = dialog.Text("Symbol", "", "COTTAGE");
        var name = dialog.Text("Name (optional)");
        var amount = dialog.Text("Value");
        var assetClass = dialog.Choice("Asset class", AssetClasses.Select(AssetClassLabel), AssetClassLabel("real_estate"));
        var date = dialog.Text("Acquisition date (YYYY-MM-DD)", DateTime.Today.ToString("yyyy-MM-dd", Invariant));
        var currency = AssetCurrencyInput(dialog, accounts, account);
        ConfigureAssetSave(dialog, () => ["asset", "manual", "--account", AssetAccountId(account),
            "--name", Value(name), "--class", AssetClassKey(assetClass), "--date", AssetDate(date, "Acquisition date"),
            "--currency", AssetCurrency(currency), "--", NewAssetSymbol(symbol), AssetNumber(amount, "Value")]);
        await dialog.ShowDialog(this);
    }

    private async Task ValueAssetAsync(JsonElement asset)
    {
        EnsureAssetEditing();
        if (Text(asset, "kind") != "manual")
            throw new InvalidOperationException("Only an asset valued by you can receive a manual valuation.");
        var symbol = Text(asset, "symbol");
        var held = _snapshot is { } root ? Rows(root, "positions").FirstOrDefault(p => Text(p, "symbol") == symbol) : default;
        if (held.ValueKind != JsonValueKind.Object)
            throw new InvalidOperationException("Refresh Holdings before recording a valuation for this asset.");
        var currency = Text(held, "currency");
        var dialog = new EntryDialog("Record a valuation", "Save valuation");
        dialog.Explain($"{symbol} · {Text(asset, "name")}\nThe new value is per unit in {currency}. This symbol's latest valuation applies wherever it is held.");
        var amount = dialog.Text($"New value per unit ({currency})", InputNumber(held, "price"));
        var date = dialog.Text("Valuation date (YYYY-MM-DD)", DateTime.Today.ToString("yyyy-MM-dd", Invariant));
        ConfigureAssetSave(dialog, () => ["asset", "value", "--date", AssetDate(date, "Valuation date"),
            "--", symbol, AssetNumber(amount, "Value", allowZero: true)]);
        await dialog.ShowDialog(this);
    }

    private async Task ClassifyAssetAsync(JsonElement holding)
    {
        EnsureAssetEditing();
        var symbol = Text(holding, "symbol");
        var saved = _snapshot is { } root ? Rows(root, "assets").FirstOrDefault(a => Text(a, "symbol") == symbol) : default;
        var current = Text(saved, "asset_class");
        if (!AssetClasses.Contains(current))
            current = AssetClasses.FirstOrDefault(key => AssetClassLabel(key) == Text(holding, "asset_class")) ?? "other";
        var dialog = new EntryDialog("Change asset class");
        dialog.Explain($"Which class {symbol} counts toward in Allocation and your targets, in every account.");
        var assetClass = dialog.Choice("Asset class", AssetClasses.Select(AssetClassLabel), AssetClassLabel(current));
        dialog.Submit = () =>
        {
            EnsureAssetEditing();
            return MutateAsync(["asset", "classify", "--", symbol, AssetClassKey(assetClass)]);
        };
        await dialog.ShowDialog(this);
    }

    private async Task<JsonElement[]> AssetAccountsAsync()
    {
        EnsureAssetEditing();
        var accounts = _snapshot is { } root ? Rows(root, "accounts").ToArray() : [];
        if (accounts.Length > 0) return accounts;
        await AccountAsync();
        return [];
    }

    private static ComboBox AssetAccountChoice(EntryDialog dialog, JsonElement[] accounts) =>
        dialog.Choice("Account", accounts.Select(a => Text(a, "id") + " · " + Text(a, "name")));

    private static string AssetAccountId(ComboBox account)
    {
        var selected = Pick(account).Split(" · ")[0];
        return selected.Length > 0 ? selected : throw new InvalidOperationException("Choose an account.");
    }

    private static TextBox AssetCurrencyInput(EntryDialog dialog, JsonElement[] accounts, ComboBox account)
    {
        string DefaultCurrency() => Text(accounts.First(a => Text(a, "id") == AssetAccountId(account)), "currency");
        var currency = dialog.Text("Currency", DefaultCurrency());
        account.SelectionChanged += (_, _) => currency.Text = DefaultCurrency();
        return currency;
    }

    private static string AssetClassKey(ComboBox choice) => AssetClasses.FirstOrDefault(key => AssetClassLabel(key) == Pick(choice))
        ?? throw new InvalidOperationException("Choose an asset class.");

    private string NewAssetSymbol(TextBox input)
    {
        var symbol = Required(input, "Symbol").ToUpperInvariant();
        if (_snapshot is { } root && new[] { "assets", "positions", "activity" }
            .Any(key => Rows(root, key).Any(row => Text(row, "symbol").Equals(symbol, StringComparison.OrdinalIgnoreCase))))
            throw new InvalidOperationException($"{symbol} is already in your portfolio. Choose another symbol.");
        return symbol;
    }

    private static string AssetCurrency(TextBox input)
    {
        var currency = Required(input, "Currency").ToUpperInvariant();
        if (currency.Length != 3 || currency.Any(c => c is < 'A' or > 'Z'))
            throw new InvalidOperationException("Currency must be a three-letter code, such as CAD or USD.");
        return currency;
    }

    private static string AssetNumber(TextBox input, string name, bool allowZero = false)
    {
        var number = Numeric(input, name);
        var value = decimal.Parse(number, Invariant);
        if (allowZero ? value < 0 : value <= 0)
            throw new InvalidOperationException(name + (allowZero ? " cannot be negative." : " must be greater than zero."));
        return number;
    }

    private static string AssetDate(TextBox input, string name, bool allowFuture = false)
    {
        var value = Required(input, name);
        if (!DateOnly.TryParseExact(value, "yyyy-MM-dd", Invariant, DateTimeStyles.None, out var date))
            throw new InvalidOperationException(name + " must use YYYY-MM-DD.");
        if (!allowFuture && date > DateOnly.FromDateTime(DateTime.Today))
            throw new InvalidOperationException(name + " cannot be in the future.");
        return date.ToString("yyyy-MM-dd", Invariant);
    }

    private void EnsureAssetEditing()
    {
        if (_client.IsDemo) throw new InvalidOperationException("The fictional demo is read-only.");
        if (Privacy) throw new InvalidOperationException("Turn Privacy off to change your assets.");
        if (_stopping || !_operation.IsCompleted)
            throw new InvalidOperationException("Wait for the current operation to finish.");
    }

    private void ConfigureAssetSave(EntryDialog dialog, Func<List<string>> arguments)
    {
        List<string>? intent = null;
        var uncertain = false;
        dialog.Submit = async () =>
        {
            EnsureAssetEditing();
            if (intent is null)
            {
                intent = arguments();
                intent.InsertRange(2, ["--request-id", Guid.NewGuid().ToString()]);
            }
            try { await MutateAsync(intent); }
            catch (BackendRejectedException) { if (!uncertain) intent = null; throw; }
            catch (InvalidOperationException) { if (!uncertain) intent = null; throw; }
            catch (FileNotFoundException) { if (!uncertain) intent = null; throw; }
            catch
            {
                if (!uncertain)
                {
                    uncertain = true;
                    dialog.Freeze();
                    dialog.Explain("The save outcome is unknown. Retry submits this same entry safely. Close and reopen to start a different entry.");
                }
                throw;
            }
        };
    }
}
