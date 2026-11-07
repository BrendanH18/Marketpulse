using Avalonia;

namespace MarketPulse.Demo;

internal static class Program
{
    internal static string PythonPath { get; private set; } = Path.Combine(
        AppContext.BaseDirectory, "MarketPulse-backend", "python", "python.exe");

    [STAThread]
    public static int Main(string[] args)
    {
        try
        {
            var checkBridge = false;
            for (var index = 0; index < args.Length; index++)
            {
                if (args[index] == "--python" && index + 1 < args.Length)
                    PythonPath = Path.GetFullPath(args[++index]);
                else if (args[index] == "--check-bridge")
                    checkBridge = true;
                else
                    throw new ArgumentException("Usage: MarketPulse.Demo [--python PATH] [--check-bridge]");
            }

            if (checkBridge)
            {
                using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(30));
                var snapshot = DemoBackend.LoadAsync(PythonPath, timeout.Token).GetAwaiter().GetResult();
                Console.WriteLine($"PASS: demo bridge, net worth {snapshot.NetWorth} {snapshot.Currency}.");
                return 0;
            }

            return BuildAvaloniaApp().StartWithClassicDesktopLifetime(args);
        }
        catch (Exception error)
        {
            Console.Error.WriteLine(error.Message);
            return 1;
        }
    }

    public static AppBuilder BuildAvaloniaApp() => AppBuilder.Configure<App>().UsePlatformDetect();
}
