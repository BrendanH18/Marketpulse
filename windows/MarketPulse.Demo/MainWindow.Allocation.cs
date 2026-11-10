using System.Globalization;
using System.Text.Json;
using Avalonia.Controls;

namespace MarketPulse.Demo;

public partial class MainWindow
{
    private void HoldingAssetDetails(JsonElement root, JsonElement holding)
    {
        Paragraph("Asset class: " + Text(holding, "asset_class"));
        var symbol = Text(holding, "symbol");
        var asset = Rows(root, "assets").FirstOrDefault(a => Text(a, "symbol") == symbol);
        if (Text(asset, "kind") == "fixed_income")
            Paragraph(Number(asset, "rate") + "% " + Text(asset, "compounding") + " · " + Text(asset, "currency") +
                " · " + Text(asset, "start_date") + " to " + Text(asset, "maturity_date") + " · valued by accrual");
        if (Text(asset, "kind") == "manual")
        {
            Paragraph("Valued by you · " + Text(asset, "valued_on", "No valuation date"));
            Actions(("Record a valuation", () => ValueAssetAsync(asset)));
        }
        Actions(("Change asset class", () => ClassifyAssetAsync(holding)));
    }

    private void Allocation(JsonElement root)
    {
        Heading("Allocation");
        var currency = Text(Get(root, "status"), "base");
        Paragraph("Values and suggested adjustments are in " + currency + ". Targets apply to your whole portfolio by asset class.");
        foreach (var row in Rows(root, "allocation"))
            Card(Text(row, "label"), Money(row, "value") + " " + currency + " · " + Number(row, "weight") + "% of portfolio");
        if (!Rows(root, "allocation").Any()) Paragraph("No valued holdings or cash yet. Add an asset or record a transaction to get started.");
        Actions((Rows(root, "targets").Any() ? "Change targets" : "Set targets", TargetsAsync));
        if (Rows(root, "targets").Any())
        {
            Actions(("Clear targets", () => ConfirmAsync("Clear allocation targets?",
                "This removes your target percentages. Holdings and transactions are kept.",
                ["allocation", "--quiet", "--clear-targets"])));
            Section("Targets and drift");
            foreach (var row in Rows(root, "rebalance"))
            {
                var delta = Decimal(row, "delta");
                var suggestion = delta is > 0 ? "Add " : delta is < 0 ? "Reduce by " : delta == 0 ? "No adjustment" : "Adjustment unavailable";
                if (delta is > 0 or < 0)
                    suggestion += Math.Abs(delta.Value).ToString("N2", CultureInfo.CurrentCulture) + " " + currency;
                Card(Text(row, "label"), "Now " + Number(row, "weight") + "% · Target " + Number(row, "target") + "%",
                    "Drift " + Number(row, "drift") + " percentage points", suggestion);
            }
        }
        else Paragraph("Set target percentages to see how your portfolio differs from your preferred mix.");
        Paragraph("Suggestions only. MarketPulse does not trade. Missing prices or exchange rates can leave investments out of these values; review any warnings below.");
    }

    private async Task TargetsAsync()
    {
        if (_snapshot is not { } snapshot || Privacy || _client.IsDemo) return;
        var dialog = new EntryDialog("Allocation targets", "Save targets");
        dialog.Explain("Enter a percentage from 0 to 100 for each asset class. Leave a field blank for no target. The total cannot exceed 100%. Saving replaces the previous targets.");
        var targets = Rows(snapshot, "targets").ToDictionary(x => Text(x, "bucket"));
        var inputs = new Dictionary<string, TextBox>();
        foreach (var key in AssetClasses)
            inputs[key] = dialog.Text(AssetClassLabel(key) + " (%)",
                targets.TryGetValue(key, out var row) ? InputNumber(row, "weight") : "");
        dialog.Submit = () =>
        {
            var arguments = new List<string> { "allocation", "--quiet", "--clear-targets" };
            decimal total = 0;
            foreach (var (key, input) in inputs)
            {
                if (Value(input).Length == 0) continue;
                var value = Numeric(input, AssetClassLabel(key));
                var weight = decimal.Parse(value, Invariant);
                if (weight < 0 || weight > 100)
                    throw new InvalidOperationException("Each target must be between 0 and 100%.");
                total += weight;
                arguments.AddRange(["--target", key + "=" + value]);
            }
            if (total > 100) throw new InvalidOperationException("Targets cannot add up to more than 100%.");
            return MutateAsync(arguments);
        };
        await dialog.ShowDialog(this);
    }
}
