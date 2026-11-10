using System.Reflection;
using System.Text.Json;
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
var python = Path.GetFullPath(args[0]);
var scratch = Directory.CreateTempSubdirectory("marketpulse-backup-ui-");
var screenshots = args.Length == 2 ? Path.GetFullPath(args[1]) : null;
if (screenshots is not null) Directory.CreateDirectory(screenshots);
const BindingFlags flags = BindingFlags.Instance | BindingFlags.NonPublic;
var program = typeof(MainWindow).Assembly.GetType("MarketPulse.Demo.Program")!;
var clientField = program.GetField("<Client>k__BackingField", BindingFlags.Static | BindingFlags.NonPublic)!;
MainWindow? window = null;
AppBuilder.Configure<App>().UseHeadless(new AvaloniaHeadlessPlatformOptions { UseHeadlessDrawing = false })
    .UseSkia().SetupWithoutStarting();
try
{
    var client = new BackendClient(python, dataDirectory: Path.Combine(scratch.FullName, "data"),
        configPath: Path.Combine(scratch.FullName, "config.toml"));
    Pump(client.RunAsync(["accounts", "add", "--type", "NONREG", "--currency", "CAD", "--track-cash", "--", "Fictional cash"]));
    Deposit("1000");
    clientField.SetValue(null, client);
    window = new MainWindow();
    window.Show();
    WaitOperation();
    ShowAutomation();
    Dispatcher.UIThread.RunJobs();
    var previousBackups = Snapshot().GetProperty("storage").GetProperty("backups").GetArrayLength();
    Click(window, "Back up now");
    WaitOperation();
    var saved = Snapshot();
    Require(saved.GetProperty("storage").GetProperty("backups").GetArrayLength() == previousBackups + 1, "Backup button did not refresh the list.");
    var manual = saved.GetProperty("storage").GetProperty("backups").EnumerateArray()
        .Single(row => row.GetProperty("reason").GetString() == "manual");
    Require(Body(window).Contains(manual.GetProperty("name").GetString()!), "Created backup is not rendered.");
    Capture(window, "backups.png");
    Console.WriteLine("PASS: Back up now button creates and renders backup metadata through the real Python engine.");

    var originalRevision = Revision();
    var dialog = OpenRestore(manual);
    Require(Body(dialog).Contains("configuration stays unchanged") && Body(dialog).Contains("pre-restore copy"), "Restore consequences missing.");
    Capture(dialog, "confirmation.png");
    Click(dialog, "Restore backup");
    Require(Body(dialog).Contains("Confirm that you want"), "Unchecked restore did not show a confirmation error.");
    Click(dialog, "Cancel");
    var afterCancel = client.SnapshotAsync();
    Pump(afterCancel);
    Require(afterCancel.Result.GetProperty("ledger_revision").GetString() == originalRevision, "Cancel changed the ledger.");
    Console.WriteLine("PASS: confirmation identifies the backup and safeguards; unchecked submit and Cancel do not restore.");

    dialog = OpenRestore(manual);
    Deposit("2500");
    Acknowledge(dialog);
    Click(dialog, "Restore backup");
    try { WaitOperation(); throw new Exception("An external edit was accepted by the restore preflight."); }
    catch (InvalidOperationException error) when (error.Message.Contains("changed while confirming")) { }
    Require(Body(dialog).Contains("changed while confirming"), "Stale restore confirmation was accepted.");
    Click(dialog, "Cancel");
    Pump(window.RefreshAsync());
    Require(Balance() == 3500m, "Stale confirmation replaced the newer ledger.");
    Console.WriteLine("PASS: a CLI edit without a window refresh invalidates an open restore confirmation.");

    dialog = OpenRestore(manual);
    var beforeMetadata = Revision();
    Pump(client.RunAsync(["asset", "classify", "--", "QA-METADATA", "equity"]));
    Acknowledge(dialog);
    Click(dialog, "Restore backup");
    try { WaitOperation(); throw new Exception("External asset metadata was overwritten by restore."); }
    catch (InvalidOperationException error) when (error.Message.Contains("changed while confirming")) { }
    Click(dialog, "Cancel");
    Pump(window.RefreshAsync());
    Require(Revision() == beforeMetadata && Snapshot().GetProperty("assets").EnumerateArray()
        .Any(asset => asset.GetProperty("symbol").GetString() == "QA-METADATA" && asset.GetProperty("asset_class").GetString() == "equity"),
        "Metadata-only edit was lost or changed the Tax ledger revision.");
    Console.WriteLine("PASS: an external metadata-only edit invalidates confirmation without changing the Tax ledger revision.");

    dialog = OpenRestore(manual);
    Acknowledge(dialog);
    Click(dialog, "Restore backup");
    WaitOperation();
    Require(Balance() == 1000m && Snapshot().GetProperty("activity").GetArrayLength() == 1, "Restore did not refresh totals and Activity.");
    var safety = Snapshot().GetProperty("storage").GetProperty("backups").EnumerateArray()
        .Single(row => row.GetProperty("reason").GetString() == "pre-restore");
    dialog = OpenRestore(safety);
    Acknowledge(dialog);
    Click(dialog, "Restore backup");
    WaitOperation();
    Require(Balance() == 3500m && Snapshot().GetProperty("activity").GetArrayLength() == 2, "Safety copy did not recover later entries.");
    Console.WriteLine("PASS: confirmed restore refreshes totals and Activity; restoring the safety copy recovers later entries.");

    // Inject a missing interpreter to exercise an unconfirmed restore outcome without a write.
    var link = Path.Combine(scratch.FullName, OperatingSystem.IsWindows() ? "refresh-python.exe" : "refresh-python");
    if (!OperatingSystem.IsWindows())
    {
        File.CreateSymbolicLink(link, python);
        // Failure-state coverage uses the window's existing client path; it never changes Python itself.
        typeof(BackendClient).GetField("_pythonPath", flags)!.SetValue(client, link);
        File.Delete(link);
        var task = (Task)typeof(MainWindow).GetMethod("BackupOperationCoreAsync", flags)!.Invoke(window, [Path.Combine(scratch.FullName, "missing.db")])!;
        try { Pump(task); throw new Exception("Missing backend restore was accepted."); }
        catch (InvalidOperationException) { }
        Require((bool)typeof(MainWindow).GetField("_restoreUncertain", flags)!.GetValue(window)! &&
            typeof(MainWindow).GetField("_snapshot", flags)!.GetValue(window) is null && Body(window).Contains("could not be confirmed"),
            "Uncertain restore result did not clear the stale state and explain recovery.");
        typeof(BackendClient).GetField("_pythonPath", flags)!.SetValue(client, python);
        Pump(window.RefreshAsync());
        Require(!(bool)typeof(MainWindow).GetField("_restoreUncertain", flags)!.GetValue(window)!, "A successful explicit refresh did not allow deliberate recovery.");
        Console.WriteLine("PASS: injected missing-backend failure clears stale state and requires explicit refresh before restore recovery.");

        var wrapper = Path.Combine(scratch.FullName, "fail-refresh");
        var quotedPython = "'" + python.Replace("'", "'\\''") + "'";
        File.WriteAllText(wrapper, "#!/bin/sh\ncase \"$*\" in *'desktop snapshot'*) echo 'Fictional snapshot failure' >&2; exit 1;; esac\nexec " + quotedPython + " \"$@\"\n");
        File.SetUnixFileMode(wrapper, UnixFileMode.UserRead | UnixFileMode.UserWrite | UnixFileMode.UserExecute);
        typeof(BackendClient).GetField("_pythonPath", flags)!.SetValue(client, wrapper);
        var restore = Path.Combine(saved.GetProperty("storage").GetProperty("backup_dir").GetString()!, manual.GetProperty("name").GetString()!);
        Pump((Task)typeof(MainWindow).GetMethod("BackupOperationCoreAsync", flags)!.Invoke(window, [restore])!);
        Require(typeof(MainWindow).GetField("_snapshot", flags)!.GetValue(window) is null &&
            Body(window).Contains("Backup restored") && Body(window).Contains("Refreshing failed"),
            "A successful restore followed by a failed refresh was reported as a failed restore.");
        typeof(BackendClient).GetField("_pythonPath", flags)!.SetValue(client, python);
        Pump(window.RefreshAsync());
        Require(Balance() == 1000m, "The restore preceding the injected snapshot failure did not save.");
        Console.WriteLine("PASS: real restore plus injected snapshot failure reports restored state and a separate refresh error.");

        // The backend can commit a restore and still exit nonzero (for example, a later crash).
        Deposit("100");
        Pump(window.RefreshAsync());
        File.WriteAllText(wrapper, "#!/bin/sh\n" + quotedPython + " \"$@\"\nresult=$?\ncase \"$*\" in *'backup restore'*) echo 'Fictional crash after restore' >&2; exit 1;; esac\nexit \"$result\"\n");
        typeof(BackendClient).GetField("_pythonPath", flags)!.SetValue(client, wrapper);
        dialog = OpenRestore(manual);
        Acknowledge(dialog);
        Click(dialog, "Restore backup");
        try { WaitOperation(); throw new Exception("The post-commit crash was not reported."); }
        catch (InvalidOperationException error) when (error.Message.Contains("could not be confirmed")) { }
        Require(typeof(MainWindow).GetField("_snapshot", flags)!.GetValue(window) is null &&
            Body(dialog).Contains("could not be confirmed"), "A nonzero post-commit exit left stale state or a blind retry.");
        Click(dialog, "Restore backup");
        Require(Body(dialog).Contains("Refresh your portfolio"), "An uncertain restore allowed a blind retry.");
        Click(dialog, "Cancel");
        typeof(BackendClient).GetField("_pythonPath", flags)!.SetValue(client, python);
        Pump(window.RefreshAsync());
        Require(Balance() == 1000m, "The injected post-commit failure did not exercise an actual committed restore.");
        Console.WriteLine("PASS: a nonzero exit after a committed restore clears stale state and blocks blind retry until refresh.");
    }

    window.FindControl<CheckBox>("PrivacyToggle")!.IsChecked = true;
    WaitOperation();
    Require(!Body(window).Contains(scratch.FullName) && !Body(window).Contains("marketpulse-") &&
        !window.GetVisualDescendants().OfType<Button>().Any(b => b.Content?.ToString() == "Back up now"), "Privacy leaked backup controls or paths.");
    Capture(window, "privacy.png");
    Console.WriteLine("PASS: privacy renders no backup names, paths or write controls.");
    Pump(window.StopAsync());
    window.Close();

    clientField.SetValue(null, new BackendClient(python, demo: true));
    window = new MainWindow();
    window.Show();
    WaitOperation();
    ShowAutomation();
    Dispatcher.UIThread.RunJobs();
    Require(Body(window).Contains("fictional demo is read-only") &&
        !window.GetVisualDescendants().OfType<Button>().Any(b => b.Content?.ToString() is "Back up now" or "Restore this backup…"), "Demo exposed backup writes.");
    Capture(window, "demo.png");
    Console.WriteLine("PASS: demo renders a read-only backup explanation without create or restore controls.");
    Console.WriteLine("Windows desktop and Narrator: UNVERIFIED. Headless button events supplement the real-engine checks.");

    void Deposit(string amount) => Pump(client.RunAsync(["deposit", "--account", "Fictional cash", "--currency", "CAD", "--date", "2024-01-03", "--", amount]));
    JsonElement Snapshot() => (JsonElement)typeof(MainWindow).GetField("_snapshot", flags)!.GetValue(window)!;
    string? Revision() => Snapshot().GetProperty("ledger_revision").GetString();
    decimal Balance() => Snapshot().GetProperty("status").GetProperty("net_worth").GetDecimal();
    Window OpenRestore(JsonElement backup)
    {
        var name = backup.GetProperty("name").GetString()!;
        var body = window.FindControl<StackPanel>("Workspace")!;
        var card = body.Children.OfType<Border>().Single(c => Body(c).Contains(name));
        var panel = (Panel)body.Children[body.Children.IndexOf(card) + 1];
        Click(panel, "Restore this backup…");
        Dispatcher.UIThread.RunJobs();
        return window.OwnedWindows.Single();
    }
    void ShowAutomation()
    {
        var navigation = window.FindControl<ListBox>("Navigation")!;
        navigation.SelectedItem = navigation.Items.Cast<ListBoxItem>().Single(item => item.Content?.ToString() == "Automation");
    }
    void WaitOperation() => Pump((Task)typeof(MainWindow).GetField("_operation", flags)!.GetValue(window)!);
}
finally
{
    if (window is not null) { Pump(window.StopAsync()); window.Close(); }
    scratch.Delete(recursive: true);
}

static void Require(bool value, string message) { if (!value) throw new Exception(message); }
static string Body(Visual visual) => string.Join("\n", visual.GetVisualDescendants().OfType<TextBlock>().Select(x => x.Text));
static void Pump(Task task)
{
    var deadline = DateTime.UtcNow.AddSeconds(90);
    while (!task.IsCompleted)
    {
        if (DateTime.UtcNow > deadline) throw new TimeoutException("Headless UI operation did not complete.");
        Dispatcher.UIThread.RunJobs();
        Thread.Sleep(5);
    }
    Dispatcher.UIThread.RunJobs();
    task.GetAwaiter().GetResult();
}
static void Click(Visual visual, string label)
{
    var button = visual.GetVisualDescendants().OfType<Button>().Single(b => b.Content?.ToString() == label);
    Require(button.IsEnabled, label + " is disabled.");
    button.RaiseEvent(new RoutedEventArgs(Button.ClickEvent));
    Dispatcher.UIThread.RunJobs();
}
static void Acknowledge(Window dialog) => dialog.GetVisualDescendants().OfType<CheckBox>().Single().IsChecked = true;
void Capture(Window target, string name)
{
    if (screenshots is null) return;
    AvaloniaHeadlessPlatform.ForceRenderTimerTick(3);
    Dispatcher.UIThread.RunJobs();
    using var frame = target.GetLastRenderedFrame() ?? throw new Exception("No rendered frame.");
#pragma warning disable CS0618 // Headless returns an owned bitmap suitable for this diagnostic capture.
    frame.Save(Path.Combine(screenshots, name));
#pragma warning restore CS0618
}
