using System.Reflection;
using System.Diagnostics;
using System.Text.Json;
using System.Text.Json.Nodes;
using Avalonia;
using Avalonia.Controls;
using Avalonia.Controls.Primitives;
using Avalonia.Headless;
using Avalonia.Interactivity;
using Avalonia.Skia;
using Avalonia.Threading;
using Avalonia.VisualTree;
using MarketPulse.Demo;

if (args.Length is < 1 or > 2) throw new ArgumentException("Pass Python path and optional screenshot output directory.");
var screenshots = args.Length == 2 ? Path.GetFullPath(args[1]) : null;
if (screenshots is not null) Directory.CreateDirectory(screenshots);
var python = Path.GetFullPath(args[0]);
// Render injected fictional rows without requesting market quotes. Real persistence is covered by BridgeCheck.
var fixture = JsonNode.Parse((await new BackendClient(python, demo: true).SnapshotAsync()).GetRawText())!.AsObject();
fixture["watchlist_symbols"] = new JsonArray("QA-FIRST", "QA-MISSING", "QA-LAST");
fixture["status"]!["watchlist"] = new JsonArray(
    new JsonObject { ["symbol"] = "QA-FIRST", ["name"] = "Fictional first", ["price"] = 10, ["currency"] = "CAD", ["change_pct"] = 1 },
    new JsonObject { ["symbol"] = "QA-LAST", ["name"] = "Fictional last", ["price"] = 20, ["currency"] = "CAD", ["change_pct"] = -1 });
fixture["alerts"] = new JsonArray(Alert(1, "QA-ARMED", true, ""), Alert(2, "QA-PAUSED", false, "2026-01-15T12:34:56Z"),
    Alert(3, "QA-TRIGGERED", true, "2026-01-15T12:34:56Z"));
const BindingFlags flags = BindingFlags.Instance | BindingFlags.NonPublic;
var program = typeof(MainWindow).Assembly.GetType("MarketPulse.Demo.Program")!;
var clientField = program.GetField("<Client>k__BackingField", BindingFlags.Static | BindingFlags.NonPublic)!;
AppBuilder.Configure<App>().UseHeadless(new AvaloniaHeadlessPlatformOptions { UseHeadlessDrawing = false }).UseSkia().SetupWithoutStarting();
var scratch = Directory.CreateTempSubdirectory("marketpulse-watchlist-ui-");
MainWindow? window = null;
try
{
    // A missing interpreter makes any accidental write fail safely without network/data access.
    window = Open(new BackendClient(Path.Combine(Path.GetTempPath(), "marketpulse-missing-" + Guid.NewGuid(), "python")));
    Capture(window, "watchlist.png");
    var cards = Workspace().Children.OfType<Border>().ToArray();
    Require(cards.Length == 6 && Body(cards[1]).Contains("QA-MISSING"), "Unpriced symbol was lost or saved order changed.");
    var up = Buttons(window, "Move up");
    var down = Buttons(window, "Move down");
    Require(up.Length == 3 && !up[0].IsEnabled && up[1].IsEnabled && !down[^1].IsEnabled, "Watchlist boundary controls are incorrect.");
    typeof(MainWindow).GetMethod("Busy", flags)!.Invoke(window, [true]);
    Require(Buttons(window, "Edit alert").All(b => !b.IsEnabled) && up.All(b => !b.IsEnabled), "Writes remained enabled during a backend operation.");
    typeof(MainWindow).GetMethod("Busy", flags)!.Invoke(window, [false]);
    Require(!up[0].IsEnabled && !down[^1].IsEnabled && up[1].IsEnabled, "Busy completion re-enabled an unavailable boundary move.");
    Console.WriteLine("PASS: injected saved watchlist renders unpriced symbols in order; move boundaries remain disabled across busy transitions.");

    foreach (var (state, expected) in new[] { ("Armed", "QA-ARMED"), ("Paused", "QA-PAUSED"), ("Triggered", "QA-TRIGGERED") })
    {
        Filter(state);
        ScrollAlerts();
        Capture(window, "alerts-" + state.ToLowerInvariant() + ".png");
        var alertCards = Workspace().Children.OfType<Border>().Where(card => Body(card).Contains("QA-ARMED") || Body(card).Contains("QA-PAUSED") || Body(card).Contains("QA-TRIGGERED")).ToArray();
        Require(alertCards.Length == 1 && Body(alertCards[0]).Contains(expected), "Alert filter has incorrect state precedence: " + state);
        Render();
        Require(FilterBox().SelectedItem?.ToString() == state, "Filter selection was lost on refresh render.");
    }
    Filter("Armed");
    Click(window, "Edit alert");
    var dialog = window.OwnedWindows.Single();
    Capture(dialog, "edit-alert.png");
    var fields = dialog.GetVisualDescendants().OfType<TextBox>().ToArray();
    fields[0].Text = "not a number";
    Click(dialog, "Save");
    Require(Body(dialog).Contains("number") && window.OwnedWindows.Contains(dialog), "Invalid threshold did not remain in the form with an error.");
    Click(dialog, "Cancel");
    Filter("Triggered");
    Click(window, "Rearm alert…");
    dialog = window.OwnedWindows.Single();
    Capture(dialog, "rearm-alert.png");
    Require(Body(dialog).Contains("trigger") && Body(dialog).Contains("fresh"), "Rearm confirmation omits trigger-history consequences.");
    Click(dialog, "Cancel");
    Require(Workspace().Children.OfType<Border>().Any(card => Body(card).Contains("QA-TRIGGERED")), "Cancel changed the displayed alert.");
    Console.WriteLine("PASS: armed/paused/triggered filters preserve selection, invalid edit remains visible, and explicit rearm confirmation cancels safely.");

    Filter("All");
    fixture["alerts"] = new JsonArray();
    SetSnapshot();
    Filter("Triggered");
    Require(Body(window).Contains("alerts match this filter"), "Empty filtered result has no explanation.");
    fixture["alerts"] = new JsonArray(Alert(1, "QA-PRIVATE", true, ""));
    SetSnapshot();
    typeof(MainWindow).GetField("_settingPrivacy", flags)!.SetValue(window, true);
    window.FindControl<CheckBox>("PrivacyToggle")!.IsChecked = true;
    Dispatcher.UIThread.RunJobs();
    Capture(window, "privacy.png");
    Require(!Body(window).Contains("QA-PRIVATE") && !Body(window).Contains("QA-FIRST") && Buttons(window, "Edit alert").Length == 0,
        "Privacy exposed symbols, notes, or editing controls.");
    Pump(window.StopAsync()); window.Close();
    window = Open(new BackendClient(python, demo: true));
    Require(Buttons(window, "Edit alert").All(b => !b.IsEnabled) && Buttons(window, "Move down").All(b => !b.IsEnabled), "Demo enabled mutations.");
    Console.WriteLine("PASS: empty state, privacy masking, and read-only demo controls on injected fictional snapshots.");
    Pump(window.StopAsync()); window.Close();

    var offlinePython = OfflinePython();
    var realClient = new BackendClient(offlinePython, dataDirectory: Path.Combine(scratch.FullName, "data"), configPath: Path.Combine(scratch.FullName, "config.toml"));
    File.WriteAllText(Path.Combine(scratch.FullName, "config.toml"), "market_strip = []\n");
    var defaultsTask = realClient.RunAsync(["watch", "list", "--json"]); Pump(defaultsTask);
    using var defaults = JsonDocument.Parse(defaultsTask.Result);
    Pump(realClient.RunAsync(new[] { "watch", "rm", "--" }.Concat(defaults.RootElement.EnumerateArray().Select(item => item.GetString()!)).ToArray()));
    Pump(realClient.RunAsync(["watch", "add", "--", "XEQT.TO", "QA-MISSING", "VFV.TO"]));
    Pump(realClient.RunAsync(["alerts", "add", "--note", "Fictional old note", "--", "XEQT.TO", "above", "100"]));
    var initial = realClient.SnapshotAsync(); Pump(initial);
    fixture = JsonNode.Parse(initial.Result.GetRawText())!.AsObject();
    window = Open(realClient);
    Click(RowActions("XEQT.TO"), "Move down"); WaitOperation();
    Require(SavedOrder().SequenceEqual(new[] { "QA-MISSING", "XEQT.TO", "VFV.TO" }), "Move down button did not persist and refresh saved order.");
    Click(RowActions("XEQT.TO"), "Move up"); WaitOperation();
    Require(SavedOrder().SequenceEqual(new[] { "XEQT.TO", "QA-MISSING", "VFV.TO" }), "Move up button did not persist and refresh saved order.");
    Click(window, "Pause alert"); WaitOperation();
    Require(CurrentAlert().GetProperty("active").GetBoolean() == false, "Pause button did not persist the alert state.");
    Click(window, "Edit alert"); dialog = window.OwnedWindows.Single();
    fields = dialog.GetVisualDescendants().OfType<TextBox>().ToArray();
    fields[0].Text = "200"; fields[1].Text = "--Fictional épargne $(echo nope) & note";
    Click(dialog, "Save"); WaitOperation();
    Require(CurrentAlert().GetProperty("threshold").GetDecimal() == 200m && CurrentAlert().GetProperty("note").GetString() == fields[1].Text &&
        !CurrentAlert().GetProperty("active").GetBoolean(), "Edit dialog did not persist literal note/threshold or changed paused state.");
    Click(window, "Resume alert"); WaitOperation();
    Require(CurrentAlert().GetProperty("active").GetBoolean(), "Resume button did not persist active state.");
    Click(window, "Rearm alert…"); dialog = window.OwnedWindows.Single();
    Click(dialog, "Rearm alert"); WaitOperation();
    Require(CurrentAlert().GetProperty("active").GetBoolean() && CurrentAlert().GetProperty("triggered_at").GetString() == "", "Rearm button did not activate and clear history.");
    Capture(window, "real-engine-alerts.png");
    // An already-open edit form must immediately mask private text.
    Click(window, "Edit alert"); dialog = window.OwnedWindows.Single();
    typeof(MainWindow).GetField("_settingPrivacy", flags)!.SetValue(window, true);
    window.FindControl<CheckBox>("PrivacyToggle")!.IsChecked = true;
    Dispatcher.UIThread.RunJobs();
    Require(!Body(dialog).Contains("XEQT.TO") && !dialog.GetVisualDescendants().OfType<TextBox>().Any(), "Open edit form exposed private fields after privacy was enabled.");
    Capture(dialog, "private-dialog.png");
    Click(dialog, "Close");
    Console.WriteLine("PASS: actual move up/down, pause/edit/resume/rearm controls persist through real CLI writes and refreshed snapshots using an isolated offline DemoMarket; open-dialog privacy masks fields.");
}
finally
{
    if (window is not null) { Pump(window.StopAsync()); window.Close(); }
    scratch.Delete(recursive: true);
}

MainWindow Open(BackendClient client)
{
    clientField.SetValue(null, client);
    var target = new MainWindow();
    typeof(MainWindow).GetField("_loaded", flags)!.SetValue(target, true);
    typeof(MainWindow).GetField("_snapshot", flags)!.SetValue(target, JsonSerializer.SerializeToElement(fixture));
    target.Show();
    target.FindControl<ListBox>("Navigation")!.SelectedIndex = 4;
    Dispatcher.UIThread.RunJobs();
    return target;
}
void SetSnapshot() { typeof(MainWindow).GetField("_snapshot", flags)!.SetValue(window, JsonSerializer.SerializeToElement(fixture)); Render(); }
void Render() { typeof(MainWindow).GetMethod("Render", flags)!.Invoke(window, null); Dispatcher.UIThread.RunJobs(); }
StackPanel Workspace() => window!.FindControl<StackPanel>("Workspace")!;
ComboBox FilterBox() => Workspace().GetVisualDescendants().OfType<ComboBox>().Single();
void Filter(string value) { FilterBox().SelectedItem = value; Dispatcher.UIThread.RunJobs(); }
static JsonObject Alert(int id, string symbol, bool active, string triggered) => new()
{
    ["id"] = id, ["symbol"] = symbol, ["condition"] = "above", ["threshold"] = 100,
    ["description"] = symbol + " above 100", ["note"] = "Fictional note", ["active"] = active, ["triggered_at"] = triggered,
};
static Button[] Buttons(Visual visual, string label) => visual.GetVisualDescendants().OfType<Button>().Where(b => b.Content?.ToString() == label).ToArray();
static string Body(Visual visual) => string.Join("\n", visual.GetVisualDescendants().OfType<TextBlock>().Select(x => x.Text));
static void Click(Visual visual, string label)
{
    var button = Buttons(visual, label).Single();
    Require(button.IsEnabled, label + " is disabled.");
    button.RaiseEvent(new RoutedEventArgs(Button.ClickEvent));
    Dispatcher.UIThread.RunJobs();
}
static void Pump(Task task)
{
    var deadline = DateTime.UtcNow.AddSeconds(90);
    while (!task.IsCompleted)
    {
        if (DateTime.UtcNow > deadline) throw new TimeoutException("Headless operation did not finish.");
        Dispatcher.UIThread.RunJobs(); Thread.Sleep(5);
    }
    Dispatcher.UIThread.RunJobs(); task.GetAwaiter().GetResult();
}
static void Require(bool condition, string message) { if (!condition) throw new Exception(message); }

void ScrollAlerts()
{
    var scroll = window!.GetVisualDescendants().OfType<ScrollViewer>().Single(view => ReferenceEquals(view.Content, Workspace()));
    scroll.Offset = new Vector(0, scroll.ScrollBarMaximum.Y);
    Dispatcher.UIThread.RunJobs();
}
void Capture(Window target, string name)
{
    if (screenshots is null) return;
    AvaloniaHeadlessPlatform.ForceRenderTimerTick(3);
    Dispatcher.UIThread.RunJobs();
    using var frame = target.GetLastRenderedFrame() ?? throw new Exception("No rendered frame.");
#pragma warning disable CS0618
    frame.Save(Path.Combine(screenshots, name));
#pragma warning restore CS0618
}

void WaitOperation() => Pump((Task)typeof(MainWindow).GetField("_operation", flags)!.GetValue(window)!);
JsonElement Snapshot() => (JsonElement)typeof(MainWindow).GetField("_snapshot", flags)!.GetValue(window)!;
JsonElement CurrentAlert() => Snapshot().GetProperty("alerts")[0];
string[] SavedOrder() => Snapshot().GetProperty("watchlist_symbols").EnumerateArray().Select(item => item.GetString()!).ToArray();
Panel RowActions(string symbol)
{
    var body = Workspace();
    var card = body.Children.OfType<Border>().Single(item => (Body(item).StartsWith(symbol + " · ", StringComparison.Ordinal) || Body(item).Split('\n')[0] == symbol));
    return (Panel)body.Children[body.Children.IndexOf(card) + 1];
}
string OfflinePython()
{
    // Scope the test transport to a disposable venv. All writes still use the installed engine.
    const string setup = """
import pathlib, subprocess, sys, venv
root = pathlib.Path(sys.argv[1])
venv.EnvBuilder(with_pip=False, system_site_packages=True).create(root)
python = root / ('Scripts/python.exe' if sys.platform == 'win32' else 'bin/python')
site = pathlib.Path(subprocess.check_output([str(python), '-I', '-c', 'import site; print(site.getsitepackages()[0])'], text=True).strip())
paths = [p for p in sys.path if 'site-packages' in p or pathlib.Path(p).name == 'src']
(site / 'watchlist_offline.pth').write_text('\n'.join(paths) + '\nimport watchlist_offline\n', encoding='utf-8')
(site / 'watchlist_offline.py').write_text('from marketpulse import services\nfrom marketpulse.desktop import DemoMarket\nservices.MarketData = DemoMarket\n', encoding='utf-8')
print(python)
""";
    using var process = new Process { StartInfo = new ProcessStartInfo(python) { UseShellExecute = false, RedirectStandardOutput = true, RedirectStandardError = true } };
    foreach (var argument in new[] { "-I", "-c", setup, Path.Combine(scratch.FullName, "offline python") }) process.StartInfo.ArgumentList.Add(argument);
    process.Start();
    var output = process.StandardOutput.ReadToEnd(); var error = process.StandardError.ReadToEnd();
    process.WaitForExit();
    Require(process.ExitCode == 0, "Could not create isolated offline interpreter: " + error);
    return output.Trim();
}
