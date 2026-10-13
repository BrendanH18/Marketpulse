import AppKit
import Foundation
import SwiftUI
import UniformTypeIdentifiers

@MainActor
final class StatusModel: ObservableObject {
  @Published var status: StatusPayload?
  @Published var desktop: DesktopPayload?
  @Published var errorMessage: String?
  @Published var message: String?
  @Published var loading = false
  @Published var saving = false
  @Published var lastUpdated: Date?
  @Published var showSettings = false
  @Published var symbolDraft = ""
  @Published var loginEnabled = LoginItem.enabled
  @Published var loginError: String?
  @Published var importURL: URL?
  @Published var importPreview: ImportPreview?
  @Published var importAccount = ""
  @Published var showImport = false
  @Published var hotKeyEnabled: Bool {
    didSet {
      if !demo { UserDefaults.standard.set(hotKeyEnabled, forKey: "hotKeyEnabled") }
      configureHotKey()
    }
  }
  @Published var refreshSeconds: Int {
    didSet {
      if !demo { UserDefaults.standard.set(refreshSeconds, forKey: "refreshSeconds") }
      schedule()
    }
  }
  @Published var terminal: String {
    didSet { if !demo { UserDefaults.standard.set(terminal, forKey: "terminal") } }
  }
  let demo = CommandLine.arguments.contains("--demo")
  private var timer: Timer?
  var canEdit: Bool { !demo && !loading && !saving && desktop != nil }

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
  var menuTitle: String { status?.title ?? (errorMessage == nil ? "MarketPulse" : "MarketPulse ⚠︎") }

  func schedule() {
    timer?.invalidate()
    guard !demo else { return }
    timer = Timer.scheduledTimer(
      withTimeInterval: TimeInterval(max(refreshSeconds, 15)), repeats: true
    ) { [weak self] _ in
      Task { @MainActor in self?.refresh() }
    }
  }

  func refreshIfStale() {
    guard let lastUpdated else { return refresh() }
    if Date().timeIntervalSince(lastUpdated) > 20 { refresh() }
  }

  func refresh() {
    guard !loading && !saving && !showImport else { return }
    loading = true
    Task { await reload() }
  }

  private func reload() async {
    loading = true
    defer { loading = false }
    do {
      let data = try await CLI.run(["desktop", "snapshot"] + (demo ? ["--demo"] : ["--fresh"]))
      let decoder = JSONDecoder()
      decoder.keyDecodingStrategy = .convertFromSnakeCase
      let payload = try decoder.decode(DesktopPayload.self, from: data)
      guard payload.version == 1 else {
        throw CLIError.failed("Unsupported desktop bridge version. Reinstall the app.")
      }
      desktop = payload
      status = payload.status
      errorMessage = nil
      lastUpdated = Date()
    } catch let error as DecodingError {
      errorMessage =
        "Unexpected portfolio data (\(error)). Update MarketPulse and reinstall the app."
    } catch {
      errorMessage = error.localizedDescription
    }
  }

  @discardableResult
  func perform(_ args: [String], success: String) async -> Bool {
    guard canEdit else { return false }
    saving = true
    defer { saving = false }
    do {
      _ = try await CLI.run(args)
      message = success
      await reload()
      return true
    } catch {
      errorMessage = error.localizedDescription
      return false
    }
  }

  func setConfig(_ key: String, _ value: String) {
    Task { await perform(["config", "set", key, value], success: "Settings updated") }
  }

  func togglePrivacy() {
    if demo {
      // Demo is read-only, including configuration writes.
      message = "Demo is read-only. Privacy mode is available in your real portfolio."
    } else {
      setConfig("privacy", (status?.privacy ?? false) ? "false" : "true")
    }
  }

  func chooseImport() {
    guard canEdit else { return }
    let panel = NSOpenPanel()
    panel.allowedContentTypes = [.commaSeparatedText, .plainText]
    panel.allowsMultipleSelection = false
    guard panel.runModal() == .OK, let url = panel.url else { return }
    importURL = url
    importPreview = nil
    importAccount = ""
    showImport = true
  }

  func previewImport() async {
    guard !demo && !saving, let url = importURL else { return }
    saving = true
    importPreview = nil
    defer { saving = false }
    do {
      let args =
        ["desktop", "import", url.path, "--dry-run"]
        + (importAccount.isEmpty ? [] : ["--account", importAccount])
      let data = try await CLI.run(args)
      let decoder = JSONDecoder()
      decoder.keyDecodingStrategy = .convertFromSnakeCase
      importPreview = try decoder.decode(ImportPreview.self, from: data)
      errorMessage = nil
    } catch { errorMessage = error.localizedDescription }
  }

  func commitImport() async {
    guard let url = importURL, let preview = importPreview, preview.added > 0 else { return }
    let args =
      ["desktop", "import", url.path] + (importAccount.isEmpty ? [] : ["--account", importAccount])
    if await perform(args, success: "CSV imported. A safety backup was created first.") {
      showImport = false
      importPreview = nil
    }
  }

  func exportLedger() {
    guard canEdit else { return }
    let panel = NSSavePanel()
    panel.nameFieldStringValue = "marketpulse-ledger.csv"
    panel.allowedContentTypes = [.commaSeparatedText]
    guard panel.runModal() == .OK, let url = panel.url else { return }
    Task { await perform(["export", url.path], success: "Ledger exported") }
  }

    func openTUI() {
        guard !demo else { return }
        TerminalLauncher.open(command: CLI.path)
    }

  private func configureHotKey() {
    guard !demo else { return }
    if hotKeyEnabled {
      HotKey.shared.register { [weak self] in self?.openTUI() }
    } else {
      HotKey.shared.unregister()
    }
  }
}
