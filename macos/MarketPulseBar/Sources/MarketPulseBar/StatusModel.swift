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
  @Published var symbolDraft = ""
  /// Why the last change in the Settings window wasn't saved.
  @Published var settingsError: String?
  /// Config values being saved, shown until the reload brings the saved ones.
  @Published private var pendingConfig: [String: String] = [:]
  @Published var appearance: AppAppearance {
    didSet {
      if !demo { UserDefaults.standard.set(appearance.rawValue, forKey: AppAppearance.key) }
      appearance.apply()
    }
  }
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
  /// Settings › General › Check for updates automatically. Off means no request at all.
  @Published var checkForUpdates: Bool {
    didSet {
      guard checkForUpdates != oldValue else { return }
      if !demo { UserDefaults.standard.set(checkForUpdates, forKey: Self.checkForUpdatesKey) }
      updateCheckResult = nil
      if checkForUpdates { checkForUpdatesIfDue() }
    }
  }
  /// A newer release, from the last check. Kept between launches, so a check a day is enough.
  @Published private(set) var availableUpdate: UpdateAvailable?
  /// The version whose banner the user closed; a newer one shows again.
  @Published private var dismissedUpdate: String?
  @Published private(set) var checkingForUpdates = false
  @Published private(set) var lastUpdateCheck: Date?
  /// The outcome of Check Now, shown in Settings. Automatic checks fail silently.
  @Published private(set) var updateCheckResult: String?
  /// The fictional read-only demo is showing instead of the user's ledger.
  @Published private(set) var demo: Bool
  /// Launched with `--demo` (screenshots, QA): the demo for the whole session, with no way out
  /// to the real ledger.
  let demoOnly = CommandLine.arguments.contains("--demo")
  /// The real ledger's folder, kept while the demo shows its temporary one.
  @Published private(set) var dataDir: String?
  enum WelcomeRequest { case firstRun, help }
  /// Asks the portfolio window to show the welcome sheet. It stays pending while another sheet
  /// is open; the window clears it once the welcome is showing.
  @Published var welcomeRequest: WelcomeRequest?
  /// Asks the portfolio window to switch workspace (Settings › Data › Show Backups).
  @Published var workspaceRequest: Workspace?
  /// The Tax workspace's report. Loaded when the workspace opens, not on every refresh: it
  /// needs historical FX rates.
  @Published private(set) var tax: TaxPayload?
  @Published private(set) var taxLoading = false
  @Published private(set) var taxError: String?
  /// Identifies everything the tax report depends on in the last payload; see `ledgerKey`.
  @Published private(set) var taxKey: Int?
  /// The `taxKey` the shown (or loading) report was built from.
  private var taxLoadedKey: Int?
  private var taxGeneration = 0
  private var portfolioController: PortfolioWindowController?
  private var settingsController: SettingsWindowController?
  var menuBarOnly: Bool { Bundle.main.object(forInfoDictionaryKey: "LSUIElement") as? Bool ?? false }

  /// Shows the portfolio window, creating it on first use.
  func showPortfolio() {
    let controller = portfolioController ?? PortfolioWindowController(model: self)
    portfolioController = controller
    controller.present()
  }

  /// `tab` picks a tab (0 is General); nil keeps the last one shown.
  func showSettingsWindow(tab: Int? = nil) {
    let controller = settingsController ?? SettingsWindowController(model: self)
    settingsController = controller
    controller.present(tab: tab)
  }

  func showWorkspace(_ workspace: Workspace) {
    showPortfolio()
    workspaceRequest = workspace
  }

  private var timer: Timer?
  private var reloadGeneration = 0
  /// Real-ledger reloads still running, superseded ones included: dropping a result doesn't stop
  /// the backend from finishing its refresh.
  @Published private var realReloads = 0
  /// Entering the demo waits for every real refresh, which may still record snapshots, take
  /// backups or fire alerts after the window has switched.
  var canEnterDemo: Bool { !demo && !saving && !loading && !showImport && realReloads == 0 }
  // A background refresh doesn't block edits: the edit's own reload supersedes it.
  var canEdit: Bool { !demo && !saving && desktop != nil }

  init() {
    demo = demoOnly
    let defaults = UserDefaults.standard
    hotKeyEnabled = defaults.object(forKey: "hotKeyEnabled") as? Bool ?? true
    let seconds = defaults.integer(forKey: "refreshSeconds")
    refreshSeconds = seconds > 0 ? seconds : 60
    terminal = defaults.string(forKey: "terminal") ?? "auto"
    appearance = AppAppearance.saved
    checkForUpdates = defaults.object(forKey: Self.checkForUpdatesKey) as? Bool ?? true
    lastUpdateCheck = defaults.object(forKey: Self.lastUpdateCheckKey) as? Date
    dismissedUpdate = defaults.string(forKey: Self.dismissedUpdateKey)
    if Self.updatesSupported, let saved = defaults.data(forKey: Self.availableUpdateKey),
      let update = try? JSONDecoder().decode(UpdateAvailable.self, from: saved)
    {
      // Dropped once this app is that version or newer.
      availableUpdate = UpdateCheck.decide(
        current: UpdateCheck.currentVersion, latestTag: update.tag, notesURL: update.notesURL,
        prerelease: false, draft: false)
    }
    configureHotKey()
    schedule()
    refresh()
    checkForUpdatesIfDue()
  }

  var palette: Palette { Palette(status?.theme) }
  var menuTitle: String {
    let title = status?.title ?? (errorMessage == nil ? "MarketPulse" : "MarketPulse ⚠︎")
    // Fictional numbers in the menu bar must never pass for the user's own.
    return demo ? "Demo \(title)" : title
  }

  func schedule() {
    timer?.invalidate()
    guard !demo else { return }
    timer = Timer.scheduledTimer(
      withTimeInterval: TimeInterval(max(refreshSeconds, 15)), repeats: true
    ) { [weak self] _ in
      Task { @MainActor in
        self?.refresh()
        self?.checkForUpdatesIfDue()
      }
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
    // Entering or leaving the demo mid-reload starts a newer reload; this one keeps its ledger.
    let demo = self.demo
    loading = true
    if !demo { realReloads += 1 }
    defer {
      if !demo { realReloads -= 1 }
      if generation == reloadGeneration { loading = false }
    }
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
      taxKey = Self.ledgerKey(payload)
      errorMessage = nil
      lastUpdated = Date()
      if !demo, let folder = payload.storage?.dataDir { dataDir = folder }
      if !demo && payload.ledgerEmpty && !UserDefaults.standard.bool(forKey: Self.welcomeShownKey) {
        welcomeRequest = welcomeRequest ?? .firstRun
      } else if welcomeRequest == .firstRun {
        // The ledger has something in it now, so a first-run offer still waiting is moot.
        welcomeRequest = nil
      }
      return
    } catch let error as DecodingError {
      desktopError = "Unexpected portfolio data (\(error)). Update MarketPulse and reinstall the app."
    } catch {
      desktopError = error.localizedDescription
    }
    // The menu bar must not depend on the desktop bridge: fall back to the stable
    // `status --json` API. Never in the demo, which must not touch the real ledger.
    // A superseded reload stops here: after entering the demo, it must not query the real ledger.
    guard generation == reloadGeneration else { return }
    guard !demo else {
      errorMessage = desktopError
      return
    }
    do {
      let fallback = try decoder.decode(
        StatusPayload.self, from: try await CLI.run(["status", "--json"]))
      guard generation == reloadGeneration else { return }
      status = fallback
      // The window keeps its last payload; it must still honour the current privacy setting.
      applyPrivacy(fallback.privacy)
      lastUpdated = Date()
      errorMessage = "The portfolio window couldn't refresh: \(desktopError)"
    } catch {
      guard generation == reloadGeneration else { return }
      errorMessage = desktopError
    }
  }

  // MARK: Updates

  static let checkForUpdatesKey = "checkForUpdates"
  static let lastUpdateCheckKey = "lastUpdateCheck"
  static let availableUpdateKey = "availableUpdate"
  static let dismissedUpdateKey = "dismissedUpdate"
  /// QA only: a file with a fictional GitHub release, read instead of the network.
  static let updateFeed = ProcessInfo.processInfo.environment["MARKETPULSE_UPDATE_FEED"].flatMap {
    $0.isEmpty ? nil : $0
  }
  /// Release builds check GitHub. A checkout install (`MarketPulse Bar.app`) updates from its
  /// checkout instead, and the release's install command would install a second app.
  static var updatesSupported: Bool {
    Bundle.main.bundleIdentifier == "dev.marketpulse.app" || updateFeed != nil
  }

  var showUpdateBanner: Bool {
    guard let availableUpdate, checkForUpdates && !demo else { return false }
    return availableUpdate.tag != dismissedUpdate
  }

  /// At most once a day; never when turned off, in the demo, or in a checkout install.
  func checkForUpdatesIfDue() {
    guard UpdateCheck.isDue(lastCheck: lastUpdateCheck) else { return }
    runUpdateCheck(manual: false)
  }

  /// Settings › Check Now and the app menu's Check for Updates.
  func checkForUpdatesNow() {
    runUpdateCheck(manual: true)
  }

  private func runUpdateCheck(manual: Bool) {
    guard Self.updatesSupported && checkForUpdates && !demo && !checkingForUpdates else { return }
    checkingForUpdates = true
    updateCheckResult = nil
    Task {
      let latest = await Self.latestRelease()
      checkingForUpdates = false
      // Turned off, or the demo entered, while the request ran.
      guard checkForUpdates && !demo else { return }
      // A failed check (offline, rate limited) counts too: it tries again tomorrow.
      let now = Date()
      lastUpdateCheck = now
      UserDefaults.standard.set(now, forKey: Self.lastUpdateCheckKey)
      guard let latest else {
        if manual { updateCheckResult = "Couldn't reach GitHub. Check your connection and try again later." }
        return
      }
      let update = UpdateCheck.decide(current: UpdateCheck.currentVersion, latest: latest)
      availableUpdate = update
      if let update, let data = try? JSONEncoder().encode(update) {
        UserDefaults.standard.set(data, forKey: Self.availableUpdateKey)
      } else {
        UserDefaults.standard.removeObject(forKey: Self.availableUpdateKey)
      }
      if manual {
        // Asked for, so show it again even if its banner was closed.
        if update != nil { setDismissedUpdate(nil) }
        updateCheckResult = update.map { "MarketPulse \($0.version) is available." } ?? "MarketPulse is up to date."
      }
    }
  }

  private static func latestRelease() async -> LatestRelease? {
    guard let updateFeed else { return await UpdateCheck.fetchLatest() }
    return (try? Data(contentsOf: URL(fileURLWithPath: updateFeed))).flatMap {
      try? JSONDecoder().decode(LatestRelease.self, from: $0)
    }
  }

  func openReleaseNotes() {
    if let update = availableUpdate, let url = URL(string: update.notesURL) { NSWorkspace.shared.open(url) }
  }

  /// The release's one-line install command, to paste into Terminal. Never run for the user.
  func copyInstallCommand() {
    guard let update = availableUpdate else { return }
    var command = update.installCommand
    // The script installs to ~/Applications; a DMG copy lives in /Applications. Replace that one
    // rather than leaving two.
    if Bundle.main.bundleURL.deletingLastPathComponent().path == "/Applications" {
      command += command.contains(" -s -- ") ? " --dir /Applications" : " -s -- --dir /Applications"
    }
    NSPasteboard.general.clearContents()
    NSPasteboard.general.setString(command, forType: .string)
    message =
      "Install command for MarketPulse \(update.version) copied. Paste it into Terminal and press Return. Your portfolio isn't changed."
  }

  func dismissUpdate() { setDismissedUpdate(availableUpdate?.tag) }

  private func setDismissedUpdate(_ tag: String?) {
    dismissedUpdate = tag
    UserDefaults.standard.set(tag, forKey: Self.dismissedUpdateKey)
  }

  // MARK: Welcome and demo

  static let welcomeShownKey = "welcomeShown"

  /// The Help menu's way back to the welcome, whatever the ledger holds.
  func showWelcome() {
    showPortfolio()
    welcomeRequest = .help
  }

  /// Called when the window shows the welcome, so a new ledger offers it only once.
  func markWelcomeShown() {
    if !demo { UserDefaults.standard.set(true, forKey: Self.welcomeShownKey) }
  }

  /// Shows the fictional portfolio in place of the user's. The demo has its own temporary
  /// ledger in the backend: nothing is read from or written to the real one until `leaveDemo`.
  func enterDemo() {
    guard canEnterDemo else { return }
    demo = true
    switchLedger()
  }

  func leaveDemo() {
    Task { await leaveDemoAndReload() }
  }

  /// Returns once the real portfolio has reloaded, so a follow-up edit (say, an import) can run.
  func leaveDemoAndReload() async {
    guard demo && !demoOnly && !saving else { return }
    demo = false
    switchLedger()
    // reload() clears `loading` when this generation finishes, whether it succeeded or failed.
    while loading { try? await Task.sleep(nanoseconds: 50_000_000) }
  }

  private func switchLedger() {
    // Clear first, so neither portfolio is ever shown under the other's label.
    desktop = nil
    status = nil
    errorMessage = nil
    message = nil
    lastUpdated = nil
    clearTax()
    schedule()
    // Invalidate in-flight reloads now, not when the queued one starts, so none of them can
    // still act on the ledger being left.
    reloadGeneration += 1
    loading = true
    Task { await reload() }
  }

  @discardableResult
  func perform(_ args: [String], success: String) async -> Bool {
    await perform(args) { _ in success }
  }

  func recordTransaction(_ request: TransactionSaveRequest) async -> TransactionSaveResult {
    guard !demo && !saving else { return .unknown("Another save is in progress.") }
    saving = true
    defer { saving = false }
    let result = await request.submit(using: CLI.run)
    switch result {
    case .recorded, .recovered:
      errorMessage = nil
      message = result == .recovered
        ? "Transaction recorded. Its confirmation failed." : "Transaction recorded"
      await reload()
    case .notRecorded(let error), .unknown(let error):
      errorMessage = error
    }
    return result
  }

  /// Runs a write command, then reloads. `afterWrite` runs as soon as the command succeeds,
  /// before the reload; `success` builds the confirmation from the command's output.
  private func perform(
    _ args: [String], afterWrite: () -> Void = {}, success: (Data) -> String
  ) async -> Bool {
    guard !demo && !saving else { return false }
    saving = true
    defer { saving = false }
    do {
      let output = try await CLI.run(args)
      afterWrite()
      message = success(output)
      await reload()
      return true
    } catch {
      errorMessage = error.localizedDescription
      return false
    }
  }

  /// Replaces the ledger with a backup; the backend saves the current one as a pre-restore
  /// backup first and refuses a damaged or newer file without changing anything.
  func restoreBackup(_ backup: BackupInfo) async {
    guard !demo && !saving, let folder = desktop?.storage?.backupDir else { return }
    saving = true
    defer { saving = false }
    // A refresh still running could record today's snapshot, valued from the ledger being
    // replaced, into the restored one. `saving` keeps new refreshes from starting meanwhile.
    while realReloads > 0 { try? await Task.sleep(nanoseconds: 50_000_000) }
    let path = URL(fileURLWithPath: folder).appendingPathComponent(backup.name).path
    do {
      _ = try await CLI.run(["backup", "restore", "--yes", "--", path])
      errorMessage = nil
      message =
        "Restored the backup from \(backup.when). Your previous portfolio was saved as a backup first."
      await reload()
    } catch {
      errorMessage = error.localizedDescription
    }
  }

  /// Saves an engine setting with `marketpulse config set`, then reloads so it takes effect.
  /// The value goes after `--`: it may be text the user typed.
  func setConfig(_ key: String, _ value: String) {
    guard !demo && !saving else { return }
    pendingConfig[key] = value
    Task {
      let saved = await perform(["config", "set", key, "--", value], success: "Settings updated")
      settingsError = saved ? nil : errorMessage
      pendingConfig[key] = nil
    }
  }

  /// Brings an archived account back (Settings › Data, the only place archived accounts are listed).
  func unarchiveAccount(_ account: ArchivedAccount) {
    guard !demo && !saving else { return }
    Task {
      let saved = await perform(
        ["accounts", "edit", "--unarchive"] + account.revisionArguments + ["--", String(account.id)],
        success: "\(account.name) is back in your portfolio")
      settingsError = saved ? nil : errorMessage
    }
  }

  /// A setting as the Settings window shows it: the value being saved, else the engine's.
  func configValue(_ key: String, _ path: KeyPath<SettingsInfo, String>) -> String {
    pendingConfig[key] ?? desktop?.settings?[keyPath: path] ?? ""
  }

  func configBinding(_ key: String, _ path: KeyPath<SettingsInfo, String>) -> Binding<String> {
    Binding(
      get: { self.configValue(key, path) },
      set: { if $0 != self.configValue(key, path) { self.setConfig(key, $0) } })
  }

  func setLoginItem(_ on: Bool) {
    guard !demo else { return }
    do {
      try LoginItem.set(on)
      loginError = nil
    } catch {
      loginError = error.localizedDescription
    }
    loginEnabled = LoginItem.enabled
  }

  func togglePrivacy() {
    if demo {
      // Demo is read-only, including configuration writes.
      message = "Demo is read-only. Privacy mode is available in your real portfolio."
      return
    }
    let enable = !(status?.privacy ?? false)
    Task {
      // Applied as soon as the setting is saved, not after the refresh (which may fail), so
      // cached amounts never stay on screen.
      await perform(
        ["config", "set", "privacy", enable ? "true" : "false"], afterWrite: { self.applyPrivacy(enable) }
      ) { _ in "Settings updated" }
    }
  }

  /// Every view reads privacy from `status` or `desktop.status`. Keeping both identical means
  /// the toolbar can never say "hidden" while a cached payload still shows amounts.
  private func applyPrivacy(_ enabled: Bool) {
    // The menu bar title was formatted by the backend and may be an amount; hide it outright
    // until the next refresh brings a correctly masked one.
    if enabled, status?.privacy == false {
      status?.title = Format.mask
      desktop?.status.title = Format.mask
    }
    status?.privacy = enabled
    desktop?.status.privacy = enabled
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

  // MARK: Tax

  /// Changes when anything the tax report reads changes: an entry, an account (archiving
  /// included), contribution room, the base currency, or a restore (which changes every
  /// revision). A timer refresh that changes none of them keeps the loaded report.
  /// `ledgerRevision` also covers archived accounts' entries and the inclusion rate, which
  /// the rest of the payload doesn't show.
  private static func ledgerKey(_ payload: DesktopPayload) -> Int {
    var hasher = Hasher()
    hasher.combine(payload.demo)
    hasher.combine(payload.ledgerRevision)
    hasher.combine(payload.status.base)
    for t in payload.activity {
      hasher.combine(t.id)
      hasher.combine(t.revision)
    }
    for a in payload.accounts {
      hasher.combine(a.id)
      hasher.combine(a.revision)
    }
    for a in payload.archivedAccounts ?? [] {
      hasher.combine(a.id)
      hasher.combine(a.revision)
    }
    for r in payload.room {
      hasher.combine(r.accountType)
      hasher.combine(r.asOfYear)
      hasher.combine(r.startingRoom)
    }
    return hasher.finalize()
  }

  /// Loads the tax report unless the one shown already matches the portfolio. `force`
  /// recalculates anyway (say, after FX rates were unavailable).
  func loadTax(force: Bool = false) {
    guard let key = taxKey, force || key != taxLoadedKey else { return }
    taxLoadedKey = key
    taxGeneration += 1
    let generation = taxGeneration
    let demo = self.demo
    taxLoading = true
    taxError = nil
    Task {
      do {
        let data = try await CLI.run(["desktop", "tax"] + (demo ? ["--demo"] : []))
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        let payload = try decoder.decode(TaxPayload.self, from: data)
        guard payload.version == 1 else {
          throw CLIError.failed("Unsupported tax report version. Reinstall the app.")
        }
        guard generation == taxGeneration else { return }
        tax = payload
      } catch {
        // Entered or left the demo, or a newer load started: this result is for another ledger.
        guard generation == taxGeneration else { return }
        taxError =
          error is DecodingError
          ? "Unexpected tax report (\(error)). Update MarketPulse and reinstall the app."
          : error.localizedDescription
        // So the next change, or Try Again, loads it again.
        taxLoadedKey = nil
      }
      if generation == taxGeneration { taxLoading = false }
    }
  }

  private func clearTax() {
    taxGeneration += 1
    tax = nil
    taxKey = nil
    taxLoadedKey = nil
    taxError = nil
    taxLoading = false
  }

  /// One year's dispositions as CSV for an accountant (`marketpulse desktop tax-csv`). Reads
  /// the ledger only. Not in the demo, whose ledger the CLI can't reach.
  func exportTax(year: Int) {
    guard !demo && desktop != nil else { return }
    let panel = NSSavePanel()
    panel.nameFieldStringValue = "marketpulse-capital-gains-\(year).csv"
    panel.allowedContentTypes = [.commaSeparatedText]
    guard panel.runModal() == .OK, let url = panel.url else { return }
    Task {
      do {
        let data = try await CLI.run(["desktop", "tax-csv", "--year", String(year), "--", url.path])
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        let result = try decoder.decode(TaxExportResult.self, from: data)
        errorMessage = nil
        message = result.message(year: year, file: url.lastPathComponent)
        // The export found other issues than the shown report: it's out of date.
        if result.issues != tax?.issues { loadTax(force: true) }
      } catch {
        errorMessage = error.localizedDescription
      }
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
