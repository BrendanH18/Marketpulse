using Avalonia;
using Avalonia.Controls;
using Avalonia.Controls.ApplicationLifetimes;
using Avalonia.Markup.Xaml;

namespace MarketPulse.Demo;

public partial class App : Application
{
    private MainWindow? _window;
    private IClassicDesktopStyleApplicationLifetime? _desktop;
    private bool _exiting;

    public override void Initialize() => AvaloniaXamlLoader.Load(this);

    public override void OnFrameworkInitializationCompleted()
    {
        if (ApplicationLifetime is IClassicDesktopStyleApplicationLifetime desktop)
        {
            _desktop = desktop;
            desktop.ShutdownMode = ShutdownMode.OnExplicitShutdown;
            _window = new MainWindow();
            _window.Closing += (_, args) =>
            {
                if (_exiting || args.CloseReason is WindowCloseReason.OSShutdown or WindowCloseReason.ApplicationShutdown)
                    return;
                args.Cancel = true;
                _window.Hide();
            };
            desktop.MainWindow = _window;
        }

        base.OnFrameworkInitializationCompleted();
    }

    private void OpenWindow(object? sender, EventArgs args)
    {
        if (_window is null)
            return;
        _window.Show();
        _window.WindowState = WindowState.Normal;
        _window.Activate();
    }

    private async void RefreshDemo(object? sender, EventArgs args)
    {
        OpenWindow(sender, args);
        if (_window is not null)
            await _window.RefreshAsync();
    }

    private async void ExitDemo(object? sender, EventArgs args)
    {
        if (_exiting)
            return;
        _exiting = true;
        if (_window is not null)
            await _window.StopAsync();
        _desktop?.Shutdown();
    }
}
