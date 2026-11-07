using System.Globalization;
using Avalonia.Controls;
using Avalonia.Interactivity;

namespace MarketPulse.Demo;

public partial class MainWindow : Window
{
    private readonly CancellationTokenSource _lifetime = new();
    private Task _refreshTask = Task.CompletedTask;
    private bool _stopping;
    private bool _loaded;

    public MainWindow()
    {
        InitializeComponent();
        Opened += async (_, _) =>
        {
            if (_loaded)
                return;
            _loaded = true;
            await RefreshAsync();
        };
    }

    public Task RefreshAsync()
    {
        if (_stopping || !_refreshTask.IsCompleted)
            return _refreshTask;
        return _refreshTask = RefreshCoreAsync();
    }

    internal async Task StopAsync()
    {
        _stopping = true;
        _lifetime.Cancel();
        await _refreshTask;
        _lifetime.Dispose();
    }

    private async Task RefreshCoreAsync()
    {
        RefreshButton.IsEnabled = false;
        Status.Text = "Loading fictional portfolio…";
        try
        {
            var snapshot = await DemoBackend.LoadAsync(Program.PythonPath, _lifetime.Token);
            NetWorth.Text = $"{snapshot.NetWorth.ToString("N2", CultureInfo.CurrentCulture)} {snapshot.Currency}";
            Status.Text = "Fictional data · offline demo";
        }
        catch (OperationCanceledException)
        {
            NetWorth.Text = "—";
            Status.Text = "The demo took too long to load. Try refreshing.";
        }
        catch (Exception error)
        {
            NetWorth.Text = "—";
            Status.Text = $"Couldn't load the demo: {error.Message}";
        }
        finally
        {
            RefreshButton.IsEnabled = true;
        }
    }

    private async void RefreshClicked(object? sender, RoutedEventArgs args) => await RefreshAsync();
}
