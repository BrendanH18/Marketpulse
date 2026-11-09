using Avalonia;

namespace MarketPulse.Demo;

internal static class Program
{
    internal static string PythonPath { get; private set; } = Path.Combine(
        AppContext.BaseDirectory, "MarketPulse-backend", "python", "python.exe");
    internal static BackendClient Client { get; private set; } = null!;

    [STAThread]
    public static int Main(string[] args)
    {
        try
        {
            var checkBridge = false;
            var demo = false;
            string? dataDirectory = null;
            string? configPath = null;
            for (var index = 0; index < args.Length; index++)
            {
                if (args[index] == "--python" && index + 1 < args.Length)
                    PythonPath = Path.GetFullPath(args[++index]);
                else if (args[index] == "--check-bridge")
                    checkBridge = true;
                else if (args[index] == "--demo")
                    demo = true;
                else if (args[index] == "--data-dir" && index + 1 < args.Length)
                    dataDirectory = Path.GetFullPath(args[++index]);
                else if (args[index] == "--config" && index + 1 < args.Length)
                    configPath = Path.GetFullPath(args[++index]);
                else
                    throw new ArgumentException("Usage: MarketPulse [--python PATH] [--demo] [--data-dir PATH --config PATH] [--check-bridge]");
            }

            // An explicit scratch launch must isolate both settings and financial data.
            if ((dataDirectory is null) != (configPath is null))
                throw new ArgumentException("Supply both --data-dir and --config for an isolated portfolio.");
            Client = new BackendClient(PythonPath, demo, dataDirectory, configPath);
            if (checkBridge)
            {
                using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(30));
                // Bundle checks always use fictional data, even without --demo.
                var snapshot = new BackendClient(PythonPath, demo: true).SnapshotAsync(timeout.Token).GetAwaiter().GetResult();
                Console.WriteLine($"PASS: desktop bridge version {snapshot.GetProperty("version").GetInt32()}, fictional snapshot.");
                return 0;
            }

            return BuildAvaloniaApp().StartWithClassicDesktopLifetime([]);
        }
        catch (Exception error)
        {
            Console.Error.WriteLine(error.Message);
            return 1;
        }
    }

    public static AppBuilder BuildAvaloniaApp() => AppBuilder.Configure<App>().UsePlatformDetect();
}
