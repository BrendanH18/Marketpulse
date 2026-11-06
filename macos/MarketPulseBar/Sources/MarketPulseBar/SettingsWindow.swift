import AppKit
import SwiftUI

/// The standard Settings window (⌘,), with a toolbar tab per section. Like the portfolio window
/// it's created on first use and kept, so the menu, the popover's gear and the Automation
/// workspace all bring back the same window.
@MainActor
final class SettingsWindowController: NSWindowController {
  /// The Data tab's index, for links that open it (e.g. to archived accounts).
  static let dataTab = 3

  init(model: StatusModel) {
    let tabs = NSTabViewController()
    tabs.tabStyle = .toolbar
    let sections: [(String, String, AnyView)] = [
      (String(localized: "General"), "gearshape", AnyView(GeneralSettings(model: model))),
      (String(localized: "Appearance"), "circle.lefthalf.filled", AnyView(AppearanceSettings(model: model))),
      (String(localized: "Portfolio"), "chart.pie", AnyView(PortfolioSettings(model: model))),
      (String(localized: "Data"), "externaldrive", AnyView(DataSettings(model: model))),
    ]
    for (label, icon, view) in sections {
      let host = NSHostingController(rootView: view)
      // The tab view controller shows the selected tab's title as the window's.
      host.title = label
      // Each tab sizes the window to its own content.
      host.sizingOptions = [.preferredContentSize]
      let item = NSTabViewItem(viewController: host)
      item.label = label
      item.image = NSImage(systemSymbolName: icon, accessibilityDescription: label)
      tabs.addTabViewItem(item)
    }
    let window = NSWindow(contentViewController: tabs)
    window.styleMask = [.titled, .closable]
    window.isReleasedWhenClosed = false
    window.tabbingMode = .disallowed
    window.center()
    if !model.demo { window.setFrameAutosaveName("MarketPulseSettings") }
    super.init(window: window)
  }

  required init?(coder: NSCoder) { nil }

  func present(tab: Int? = nil) {
    if let tab, let tabs = contentViewController as? NSTabViewController { tabs.selectedTabViewItemIndex = tab }
    showWindow(nil)
    window?.makeKeyAndOrderFront(nil)
    NSApp.activate()
  }
}

/// Every tab: a grouped form, the demo's read-only notice, and the last failed save.
private struct SettingsPage<Content: View>: View {
  @ObservedObject var model: StatusModel
  /// The tab writes the user's settings, so it's read-only in the demo.
  var writes = true
  @ViewBuilder let content: Content

  var body: some View {
    Form {
      if model.demo && writes {
        Label(
          "You're exploring the demo. Settings are read-only until you leave it.", systemImage: "sparkles"
        ).foregroundStyle(.secondary)
      }
      if let error = model.settingsError {
        Label(error, systemImage: "exclamationmark.triangle").foregroundStyle(Studio.red)
          .textSelection(.enabled)
      }
      content.disabled(writes && model.demo)
    }
    .formStyle(.grouped)
    .frame(width: 520)
    .fixedSize(horizontal: false, vertical: true)
  }
}

private struct GeneralSettings: View {
  @ObservedObject var model: StatusModel
  private static let intervals = [30, 60, 120, 300]
  private static let displays = [
    ("day_pct", String(localized: "Day change %")), ("day_change", String(localized: "Day change $")),
    ("net_worth", String(localized: "Net worth")), ("symbol", String(localized: "A symbol's price")),
  ]

  var body: some View {
    SettingsPage(model: model) {
      Section {
        Picker("Refresh quotes every", selection: $model.refreshSeconds) {
          ForEach(Self.intervals, id: \.self) {
            interval($0).tag($0)
          }
        }
        Toggle("Launch at login", isOn: Binding(get: { model.loginEnabled }, set: model.setLoginItem))
        if let error = model.loginError { Text(error).foregroundStyle(Studio.red) }
      } footer: {
        Text("Refreshes, daily snapshots, backups and alerts run while MarketPulse is open, even with the window closed.")
      }
      if StatusModel.updatesSupported {
        Section {
          Toggle("Check for updates automatically", isOn: $model.checkForUpdates)
          HStack {
            Button("Check Now") { model.checkForUpdatesNow() }
              .disabled(!model.checkForUpdates || model.checkingForUpdates)
            if model.checkingForUpdates { ProgressView().controlSize(.small) }
            Spacer()
            Text(updateStatus).foregroundStyle(.secondary)
          }
          if model.checkForUpdates, let update = model.availableUpdate {
            LabeledContent("MarketPulse \(update.version) is available") {
              HStack {
                Button("Release Notes") { model.openReleaseNotes() }
                Button("Copy Install Command") { model.copyInstallCommand() }
              }
            }
          }
        } header: {
          Text("Updates")
        } footer: {
          Text(
            "Once a day, MarketPulse asks GitHub for the version number of its latest release. Nothing about you or your portfolio is sent, and updates are never installed for you: paste the install command into Terminal."
          )
        }
      } else {
        Section("Updates") {
          Text("This copy was built from a MarketPulse checkout. Update the checkout, then run marketpulse desktop install again.")
            .foregroundStyle(.secondary)
        }
      }
      Section("Menu bar") {
        Picker("Show", selection: model.configBinding("menubar_display", \.menubarDisplay)) {
          ForEach(Self.displays, id: \.0) { Text($0.1).tag($0.0) }
        }
        if model.configValue("menubar_display", \.menubarDisplay) == "symbol" {
          LabeledContent("Symbol") {
            HStack {
              TextField("Symbol", text: $model.symbolDraft, prompt: Text(verbatim: "XEQT.TO"))
                .labelsHidden().onSubmit(saveSymbol)
              Button("Set", action: saveSymbol).disabled(symbol.isEmpty || symbol == current)
            }
          }
        }
      }
      // A save reloads the portfolio, and setConfig ignores changes made until it finishes.
      .disabled(model.desktop?.settings == nil || model.saving)
      MarketDataSection(model: model)
      Section("Terminal") {
        Picker("Open the terminal app in", selection: $model.terminal) {
          ForEach(TerminalLauncher.choices, id: \.self) { Text($0 == "iterm" ? "iTerm" : $0.capitalized).tag($0) }
        }
        Toggle("⌥⌘M opens the terminal app from anywhere", isOn: $model.hotKeyEnabled)
      }
    }
    .onAppear {
      model.loginEnabled = LoginItem.enabled
      model.symbolDraft = current
    }
  }

  /// One sentence per interval, so each language can word (and pluralize) its own.
  private func interval(_ seconds: Int) -> Text {
    if seconds < 60 { return Text("\(seconds) seconds") }
    if seconds == 60 { return Text("1 minute") }
    return Text("\(seconds / 60) minutes")
  }

  private var updateStatus: String {
    if let result = model.updateCheckResult { return result }
    guard model.checkForUpdates else { return String(localized: "Off") }
    guard let last = model.lastUpdateCheck else { return String(localized: "Not checked yet") }
    return String(localized: "Last checked \(last.formatted(.relative(presentation: .named)))")
  }

  private var current: String { model.configValue("menubar_symbol", \.menubarSymbol) }
  private var symbol: String { model.symbolDraft.trimmingCharacters(in: .whitespaces).uppercased() }
  private func saveSymbol() {
    guard !symbol.isEmpty && symbol != current else { return }
    model.setConfig("menubar_symbol", symbol)
  }
}

/// The optional fallback quote provider and its API key. The key goes to the CLI on stdin and is
/// never shown again: the engine reports only whether one is saved.
private struct MarketDataSection: View {
  @ObservedObject var model: StatusModel
  @StateObject private var draft = MarketDataDraft()

  var body: some View {
    let settings = model.desktop?.settings
    let available = settings?.quoteProvidersAvailable ?? []
    let saved = settings?.quoteProvider ?? ""
    let keySet = settings?.quoteProviderKeySet ?? false
    let chosen = available.first { $0.name == draft.provider }
    Section {
      if settings?.quoteProvidersAvailable == nil {
        Group {
          if settings == nil {
            Text("Available after the next refresh.")
          } else {
            Text("This version of the MarketPulse engine doesn't support a fallback quote provider.")
          }
        }.foregroundStyle(.secondary)
      } else {
        Picker("Fallback provider", selection: $draft.provider) {
          Text("None").tag("")
          ForEach(available) { Text($0.label).tag($0.name) }
          // A provider saved by a newer engine, or one no longer offered, still shows by name.
          if !saved.isEmpty && !available.contains(where: { $0.name == saved }) {
            Text(model.desktop?.providerLabel(saved) ?? saved).tag(saved)
          }
        }
        if !draft.provider.isEmpty {
          if draft.provider == saved && keySet {
            LabeledContent("API key") {
              Label("Key saved", systemImage: "checkmark.circle").foregroundStyle(Studio.mint)
            }
          }
          LabeledContent(
            draft.provider == saved && keySet ? String(localized: "Replace key") : String(localized: "API key")
          ) {
            HStack {
              SecureField("API key", text: $draft.key, prompt: Text("Paste your key"))
                .labelsHidden().onSubmit(save)
                .accessibilityLabel("\(chosen?.label ?? draft.provider) API key")
              Button("Save", action: save).disabled(trimmedKey.isEmpty)
            }
          }
          if let chosen, let url = chosen.signup {
            Link("Get a \(chosen.label) key", destination: url)
          }
        }
        if !saved.isEmpty || keySet {
          HStack {
            Spacer()
            Button("Remove key") {
              draft.key = ""
              model.clearQuoteProviderKey()
            }
            .accessibilityLabel(removeKeyLabel(saved))
          }
        }
      }
    } header: {
      Text("Market data")
    } footer: {
      Text("Optional. Used only when Yahoo can't be reached. Your key stays in your config file on this Mac.")
    }
    .disabled(settings == nil || model.saving)
    .onAppear { draft.provider = saved }
    // After a save or removal, show what the engine now has.
    .onChange(of: saved) { _, value in draft.provider = value }
    // Choosing None turns the saved fallback off, as Remove key does.
    .onChange(of: draft.provider) { _, value in
      if value.isEmpty && !saved.isEmpty {
        draft.key = ""
        model.clearQuoteProviderKey()
      }
    }
  }

  private func removeKeyLabel(_ saved: String) -> String {
    guard let name = model.desktop?.providerLabel(saved) else {
      return String(localized: "Remove the fallback provider key")
    }
    return String(localized: "Remove the \(name) key")
  }

  private var trimmedKey: String { draft.key.trimmingCharacters(in: .whitespacesAndNewlines) }

  private func save() {
    let provider = draft.provider
    guard !provider.isEmpty, !trimmedKey.isEmpty, !model.saving else { return }
    let key = draft.key
    Task {
      if await model.saveQuoteProviderKey(provider: provider, key: key) { draft.key = "" }
    }
  }
}

private final class MarketDataDraft: ObservableObject {
  /// The provider being set up: the saved one until the user picks another.
  @Published var provider = ""
  /// Typed into the SecureField; cleared once saved. Never written anywhere else.
  @Published var key = ""
}

private struct AppearanceSettings: View {
  @ObservedObject var model: StatusModel

  var body: some View {
    SettingsPage(model: model) {
      Section {
        Picker("Appearance", selection: $model.appearance) {
          ForEach(AppAppearance.allCases) { Text($0.label).tag($0) }
        }.pickerStyle(.segmented)
      } footer: {
        Text(
          "System follows your Mac's Light or Dark setting. The menu bar panel keeps the colours of your MarketPulse terminal theme."
        )
      }
    }
  }
}

private struct PortfolioSettings: View {
  @ObservedObject var model: StatusModel
  private static let currencies = ["CAD", "USD", "EUR", "GBP"]

  var body: some View {
    let settings = model.desktop?.settings
    SettingsPage(model: model) {
      Section {
        Picker("Show totals in", selection: model.configBinding("base_currency", \.baseCurrency)) {
          let base = model.configValue("base_currency", \.baseCurrency)
          ForEach(Self.currencies.contains(base) || base.isEmpty ? Self.currencies : [base] + Self.currencies, id: \.self) {
            Text($0).tag($0)
          }
        }
      } footer: {
        Text("Each account keeps its own currency. Totals and charts are converted to this one.")
      }
      Section {
        Picker("Default account", selection: defaultAccount) {
          Text("None").tag(0)
          ForEach(model.desktop?.accounts ?? []) { Text($0.name).tag($0.id) }
        }
        if let settings, !settings.defaultAccount.isEmpty, settings.defaultAccountId == nil {
          Text("“\(settings.defaultAccount)” doesn't match an active account.").foregroundStyle(Studio.warn)
        }
      } footer: {
        Text("Chosen first when you record a transaction.")
      }
      Section {
        Toggle(
          "Hide amounts",
          isOn: Binding(
            get: { model.status?.privacy ?? false },
            set: { if $0 != (model.status?.privacy ?? false) { model.togglePrivacy() } }))
      } footer: {
        Text("Privacy mode shows percentages but hides dollar amounts, here and in the menu bar.")
      }
    }.disabled(settings == nil || model.saving)
  }

  /// Saved by name, as the CLI suggests: SQLite reuses a deleted account's id, so an id could
  /// later pick an unrelated account. The CLI reads an all-digit value (any script's digits) as
  /// an id, so such a name is saved as its id instead.
  private var defaultAccount: Binding<Int> {
    Binding(
      get: { model.desktop?.settings?.defaultAccountId ?? 0 },
      set: { id in
        let name = model.desktop?.accounts.first { $0.id == id }?.name ?? ""
        let numeric = !name.isEmpty && name.allSatisfy(\.isNumber)
        model.setConfig("default_account", numeric ? String(id) : name)
      })
  }
}

private struct DataSettings: View {
  @ObservedObject var model: StatusModel

  var body: some View {
    let storage = model.desktop?.storage
    SettingsPage(model: model, writes: false) {
      Section {
        location(String(localized: "Portfolio"), model.demo ? nil : model.dataDir)
        location(String(localized: "Settings file"), model.demo ? nil : model.desktop?.settings?.configPath)
      } footer: {
        Text("Your portfolio stays on this Mac and is never uploaded. MarketPulse goes online only for prices, exchange rates and the update check.")
      }
      Section("Backups") {
        LabeledContent(
          "Backups kept",
          value: model.demo ? String(localized: "None in the demo") : (storage?.backups?.count ?? 0).formatted())
        if let latest = storage?.backups?.first {
          LabeledContent("Latest", value: "\(latest.when) · \(latest.reasonLabel)")
        }
        Button("Show Backups…") { model.showWorkspace(.automation) }.disabled(model.demo)
      }
      // The only place archived accounts appear, solely so they can be brought back.
      if let archived = model.desktop?.archivedAccounts, !archived.isEmpty {
        Section {
          DisclosureGroup("Archived accounts (\(archived.count))") {
            ForEach(archived) { account in
              LabeledContent {
                Button("Unarchive") { model.unarchiveAccount(account) }.disabled(!model.canEdit)
              } label: {
                Text(account.name)
                Text(DesktopAccount.typeLabel(account.type))
              }
            }
          }
        } footer: {
          Text(
            "Archived accounts are hidden everywhere else and left out of your totals. Their transactions are kept. Unarchive one to bring it back."
          )
        }
      }
    }
  }

  private func location(_ title: String, _ path: String?) -> some View {
    LabeledContent(title) {
      HStack {
        Text(path.map(abbreviate) ?? String(localized: "Not available")).foregroundStyle(.secondary).lineLimit(1)
          .truncationMode(.middle).textSelection(.enabled).help(path ?? "")
        Button("Reveal in Finder") {
          if let path { NSWorkspace.shared.activateFileViewerSelecting([URL(fileURLWithPath: path)]) }
        }.disabled(path.map { !FileManager.default.fileExists(atPath: $0) } ?? true)
      }
    }
  }

  private func abbreviate(_ path: String) -> String {
    let home = NSHomeDirectory()
    return path.hasPrefix(home + "/") ? "~" + path.dropFirst(home.count) : path
  }
}
