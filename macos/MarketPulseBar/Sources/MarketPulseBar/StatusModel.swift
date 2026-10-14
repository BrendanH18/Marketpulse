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
  @Published var importName = ""
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
  private var portfolioController: PortfolioWindowController?
  var menuBarOnly: Bool { Bundle.main.object(forInfoDictionaryKey: "LSUIElement") as? Bool ?? false }

  /// Shows the portfolio window, creating it on first use.
  func showPortfolio() {
    let controller = portfolioController ?? PortfolioWindowController(model: self)
    portfolioController = controller
    controller.present()
  }

  private var timer: Timer?
  private var reloadGeneration = 0
  // A background refresh doesn't block edits: the edit's own reload supersedes it.
  var canEdit: Bool { !demo && !saving && desktop != nil }

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
    reloadGeneration += 1
    let generation = reloadGeneration
    loading = true
    defer { if generation == reloadGeneration { loading = false } }
    let decoder = JSONDecoder()
    decoder.keyDecodingStrategy = .convertFromSnakeCase
    let desktopError: String
    do {
      let data = try await CLI.run(["desktop", "snapshot"] + (demo ? ["--demo"] : ["--fresh"]))
      let payload = try decoder.decode(DesktopPayload.self, from: data)
      guard payload.version == 1 else {
        throw CLIError.failed("Unsupported desktop bridge version. Reinstall the app.")
      }
      // An older refresh that finishes late must not overwrite data reloaded after an edit.
      guard generation == reloadGeneration else { return }
      desktop = payload
      status = payload.status
      errorMessage = nil
      lastUpdated = Date()
      return
    } catch let error as DecodingError {
      desktopError = "Unexpected portfolio data (\(error)). Update MarketPulse and reinstall the app."
    } catch {
      desktopError = error.localizedDescription
    }
    // The menu bar must not depend on the desktop bridge: fall back to the stable
    // `status --json` API. Never in the demo, which must not touch the real ledger.
    guard !demo else {
      if generation == reloadGeneration { errorMessage = desktopError }
      return
    }
    do {
      let fallback = try decoder.decode(
        StatusPayload.self, from: try await CLI.run(["status", "--json"]))
      guard generation == reloadGeneration else { return }
      status = fallback
      lastUpdated = Date()
      errorMessage = "The portfolio window couldn't refresh: \(desktopError)"
    } catch {
      guard generation == reloadGeneration else { return }
      errorMessage = desktopError
    }
  }

  @discardableResult
  func perform(_ args: [String], success: String) async -> Bool {
    await perform(args) { _ in success }
  }

  /// Runs a write command, then reloads. `success` builds the confirmation from the command's output.
  private func perform(_ args: [String], success: (Data) -> String) async -> Bool {
    guard !demo && !saving else { return false }
    saving = true
    defer { saving = false }
    do {
      let output = try await CLI.run(args)
      message = success(output)
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
    // Preview and import read the same private copy, so edits to the original file
    // after previewing can't change what gets imported.
    let pinned = FileManager.default.temporaryDirectory
      .appendingPathComponent("marketpulse-import-\(UUID().uuidString).csv")
    do {
      try FileManager.default.copyItem(at: url, to: pinned)
    } catch {
      errorMessage = "Couldn't read \(url.lastPathComponent): \(error.localizedDescription)"
      return
    }
    closeImport()
    importURL = pinned
    importName = url.lastPathComponent
    showImport = true
  }

  func closeImport() {
    if let importURL { try? FileManager.default.removeItem(at: importURL) }
    importURL = nil
    importPreview = nil
    importAccount = ""
    showImport = false
  }

  private var importArguments: [String] {
    importAccount.isEmpty ? [] : ["--account", importAccount]
  }

  func previewImport() async {
    guard !demo && !saving, let url = importURL else { return }
    saving = true
    importPreview = nil
    defer { saving = false }
    do {
      let data = try await CLI.run(["desktop", "import", "--dry-run"] + importArguments + ["--", url.path])
      let decoder = JSONDecoder()
      decoder.keyDecodingStrategy = .convertFromSnakeCase
      importPreview = try decoder.decode(ImportPreview.self, from: data)
      errorMessage = nil
    } catch { errorMessage = error.localizedDescription }
  }

  func commitImport() async {
    guard let url = importURL, let preview = importPreview, preview.added > 0 else { return }
    // The backend writes nothing, and fails, if the ledger or the file changed since this preview.
    let args =
      ["desktop", "import", "--expect-fingerprint", preview.fingerprint] + importArguments + [
        "--", url.path,
      ]
    let imported = await perform(args) { data in
      let decoder = JSONDecoder()
      decoder.keyDecodingStrategy = .convertFromSnakeCase
      let added = (try? decoder.decode(ImportPreview.self, from: data))?.added ?? preview.added
      return "Imported \(added) entries. A safety backup was created first."
    }
    // On failure the error stays on screen, and the stale preview must be redone.
    if imported { closeImport() } else { importPreview = nil }
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
