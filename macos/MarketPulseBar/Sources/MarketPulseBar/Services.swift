import AppKit
import Carbon.HIToolbox
import Foundation
import ServiceManagement

enum CLIError: LocalizedError {
    case failed(String)
    case launch(String)

    var errorDescription: String? {
        switch self {
        case .failed(let message): return message.trimmingCharacters(in: .whitespacesAndNewlines)
        case .launch(let message): return "Couldn't run marketpulse: \(message)"
        }
    }
}

/// Runs the MarketPulse CLI. GUI apps don't inherit the shell PATH, so the
/// installer stores the absolute CLI path in user defaults.
enum CLI {
    static var path: String {
        UserDefaults.standard.string(forKey: "cliPath") ?? "marketpulse"
    }

    static func run(_ args: [String]) async throws -> Data {
        try await withCheckedThrowingContinuation { continuation in
            DispatchQueue.global(qos: .userInitiated).async {
                let process = Process()
                let exe = path
                if exe.hasPrefix("/") {
                    process.executableURL = URL(fileURLWithPath: exe)
                    process.arguments = args
                } else {
                    process.executableURL = URL(fileURLWithPath: "/usr/bin/env")
                    process.arguments = [exe] + args
                }
                var env = ProcessInfo.processInfo.environment
                let extra = ["/opt/homebrew/bin", "/usr/local/bin", NSHomeDirectory() + "/.local/bin"]
                env["PATH"] = (extra + [env["PATH"] ?? "/usr/bin:/bin"]).joined(separator: ":")
                env["NO_COLOR"] = "1"
                if let dir = UserDefaults.standard.string(forKey: "dataDir") {
                    env["MARKETPULSE_DATA"] = dir
                }
                process.environment = env
                let stdout = Pipe()
                let stderr = Pipe()
                process.standardOutput = stdout
                process.standardError = stderr
                var errData = Data()
                let errGroup = DispatchGroup()
                errGroup.enter()
                DispatchQueue.global().async {
                    errData = stderr.fileHandleForReading.readDataToEndOfFile()
                    errGroup.leave()
                }
                do {
                    try process.run()
                } catch {
                    continuation.resume(throwing: CLIError.launch(error.localizedDescription))
                    return
                }
                let data = stdout.fileHandleForReading.readDataToEndOfFile()
                process.waitUntilExit()
                errGroup.wait()
                if process.terminationStatus == 0 {
                    continuation.resume(returning: data)
                } else {
                    let message = String(data: errData, encoding: .utf8) ?? "exit \(process.terminationStatus)"
                    continuation.resume(throwing: CLIError.failed(message))
                }
            }
        }
    }
}

/// Opens the MarketPulse TUI in the user's terminal of choice.
enum TerminalLauncher {
    static let choices = ["auto", "ghostty", "iterm", "kitty", "wezterm", "terminal"]

    static func open(command: String) {
        let choice = UserDefaults.standard.string(forKey: "terminal") ?? "auto"
        switch choice == "auto" ? detect() : choice {
        case "ghostty":
            launch("/usr/bin/open", ["-na", "Ghostty", "--args", "-e", command])
        case "kitty":
            launch("/usr/bin/open", ["-na", "kitty", "--args", command])
        case "wezterm":
            launch("/usr/bin/open", ["-na", "WezTerm", "--args", "start", "--", command])
        case "iterm":
            appleScript("""
            tell application "iTerm"
                activate
                create window with default profile command "\(escape(command))"
            end tell
            """)
        default:
            appleScript("""
            tell application "Terminal"
                activate
                do script "\(escape(command))"
            end tell
            """)
        }
    }

    static func detect() -> String {
        let candidates = [
            ("com.mitchellh.ghostty", "ghostty"),
            ("com.googlecode.iterm2", "iterm"),
            ("net.kovidgoyal.kitty", "kitty"),
            ("com.github.wez.wezterm", "wezterm"),
        ]
        for (bundleID, name) in candidates where NSWorkspace.shared.urlForApplication(withBundleIdentifier: bundleID) != nil {
            return name
        }
        return "terminal"
    }

    private static func escape(_ s: String) -> String {
        s.replacingOccurrences(of: "\\", with: "\\\\").replacingOccurrences(of: "\"", with: "\\\"")
    }

    private static func launch(_ exe: String, _ args: [String]) {
        let p = Process()
        p.executableURL = URL(fileURLWithPath: exe)
        p.arguments = args
        try? p.run()
    }

    private static func appleScript(_ source: String) {
        launch("/usr/bin/osascript", ["-e", source])
    }
}

/// System-wide ⌥⌘M via Carbon (no Accessibility permission required).
final class HotKey {
    static let shared = HotKey()
    private var hotKeyRef: EventHotKeyRef?
    private var handlerRef: EventHandlerRef?
    private var action: (() -> Void)?

    func register(action: @escaping () -> Void) {
        unregister()
        self.action = action
        var spec = EventTypeSpec(eventClass: OSType(kEventClassKeyboard), eventKind: UInt32(kEventHotKeyPressed))
        InstallEventHandler(
            GetApplicationEventTarget(),
            { _, _, userData in
                guard let userData else { return noErr }
                let hotKey = Unmanaged<HotKey>.fromOpaque(userData).takeUnretainedValue()
                DispatchQueue.main.async { hotKey.action?() }
                return noErr
            },
            1,
            &spec,
            Unmanaged.passUnretained(self).toOpaque(),
            &handlerRef
        )
        let id = EventHotKeyID(signature: OSType(0x4D50_4B42), id: 1)  // "MPKB"
        RegisterEventHotKey(UInt32(kVK_ANSI_M), UInt32(cmdKey | optionKey), id, GetApplicationEventTarget(), 0, &hotKeyRef)
    }

    func unregister() {
        if let hotKeyRef { UnregisterEventHotKey(hotKeyRef) }
        if let handlerRef { RemoveEventHandler(handlerRef) }
        hotKeyRef = nil
        handlerRef = nil
    }
}

enum LoginItem {
    static var enabled: Bool {
        SMAppService.mainApp.status == .enabled
    }

    static func set(_ on: Bool) throws {
        if on {
            try SMAppService.mainApp.register()
        } else {
            try SMAppService.mainApp.unregister()
        }
    }
}
