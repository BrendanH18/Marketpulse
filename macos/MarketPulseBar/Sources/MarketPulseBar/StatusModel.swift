import Foundation
import SwiftUI

@MainActor
final class StatusModel: ObservableObject {
    @Published var status: StatusPayload?
    @Published var errorMessage: String?
    @Published var loading = false
    @Published var lastUpdated: Date?
    @Published var showSettings = false
    @Published var symbolDraft = ""
    @Published var loginEnabled = LoginItem.enabled
    @Published var loginError: String?
    @Published var hotKeyEnabled: Bool {
        didSet {
            UserDefaults.standard.set(hotKeyEnabled, forKey: "hotKeyEnabled")
            configureHotKey()
        }
    }
    @Published var refreshSeconds: Int {
        didSet {
            UserDefaults.standard.set(refreshSeconds, forKey: "refreshSeconds")
            schedule()
        }
    }
    @Published var terminal: String {
        didSet { UserDefaults.standard.set(terminal, forKey: "terminal") }
    }

    private var timer: Timer?

    init() {
        let defaults = UserDefaults.standard
        hotKeyEnabled = defaults.object(forKey: "hotKeyEnabled") as? Bool ?? true
        let seconds = defaults.integer(forKey: "refreshSeconds")
        refreshSeconds = seconds > 0 ? seconds : 60
        terminal = defaults.string(forKey: "terminal") ?? "auto"
        configureHotKey()
        schedule()
        refresh()
    }

    var palette: Palette { Palette(status?.theme) }

    var menuTitle: String {
        if let status { return status.title }
        return errorMessage == nil ? "MarketPulse" : "MarketPulse ⚠︎"
    }

    func schedule() {
        timer?.invalidate()
        timer = Timer.scheduledTimer(withTimeInterval: TimeInterval(max(refreshSeconds, 15)), repeats: true) { [weak self] _ in
            Task { @MainActor in self?.refresh() }
        }
    }

    func refreshIfStale() {
        guard let lastUpdated else { return refresh() }
        if Date().timeIntervalSince(lastUpdated) > 20 { refresh() }
    }

    func refresh() {
        guard !loading else { return }
        loading = true
        Task {
            defer { loading = false }
            do {
                let data = try await CLI.run(["status", "--json"])
                let decoder = JSONDecoder()
                decoder.keyDecodingStrategy = .convertFromSnakeCase
                status = try decoder.decode(StatusPayload.self, from: data)
                errorMessage = nil
                lastUpdated = Date()
            } catch let error as DecodingError {
                errorMessage = "Unexpected status payload (\(error)). Update MarketPulse and reinstall the menu bar app."
            } catch {
                errorMessage = error.localizedDescription
            }
        }
    }

    func setConfig(_ key: String, _ value: String) {
        Task {
            do {
                _ = try await CLI.run(["config", "set", key, value])
            } catch {
                errorMessage = error.localizedDescription
            }
            refresh()
        }
    }

    func togglePrivacy() {
        setConfig("privacy", (status?.privacy ?? false) ? "false" : "true")
    }

    func openTUI() {
        TerminalLauncher.open(command: CLI.path)
    }

    private func configureHotKey() {
        if hotKeyEnabled {
            HotKey.shared.register { [weak self] in self?.openTUI() }
        } else {
            HotKey.shared.unregister()
        }
    }
}
