import AppKit
import Charts
import SwiftUI

enum Workspace: String, CaseIterable, Identifiable {
  case overview = "Overview"
  case holdings = "Holdings"
  case allocation = "Allocation"
  case activity = "Activity"
  case accounts = "Accounts"
  case watchlist = "Watchlist"
  case income = "Income"
  case tax = "Tax"
  case automation = "Automation"
  var id: String { rawValue }
  var icon: String {
    switch self {
    case .overview: return "square.grid.2x2"
    case .holdings: return "chart.pie"
    case .allocation: return "scope"
    case .activity: return "arrow.left.arrow.right"
    case .accounts: return "building.columns"
    case .watchlist: return "star"
    case .income: return "arrow.down.to.line"
    case .tax: return "percent"
    case .automation: return "bolt"
    }
  }
  var subtitle: String {
    switch self {
    case .overview: return "A little perspective on your portfolio."
    case .holdings: return "Every position, in one place."
    case .allocation: return "Your mix, against the one you're aiming for."
    case .activity: return "The ledger behind your portfolio."
    case .accounts: return "Your accounts. Your bigger picture."
    case .watchlist: return "Keep an eye on what comes next."
    case .income: return "Distributions and interest you've recorded."
    case .tax: return "Capital gains, superficial losses, and contribution room."
    case .automation: return "The small routines that keep things up to date."
    }
  }
}

enum DesktopSheet: String, Identifiable {
  case transaction, editTransaction, account, editAccount, room, alert, welcome
  case fixedAsset, manualAsset, valuation, assetClass, targets
  var id: String { rawValue }
}

struct PortfolioWindow: View {
  @StateObject private var draft = PortfolioWindowDraft()
  @ObservedObject var model: StatusModel

  var body: some View {
    NavigationSplitView {
      sidebar
        .navigationSplitViewColumnWidth(min: 190, ideal: 215, max: 245)
    } detail: {
      VStack(spacing: 0) {
        header
        if let error = model.errorMessage {
          notice(error, icon: "exclamationmark.triangle", color: Studio.red)
        }
        if let message = model.message {
          HStack {
            Text(message).font(.callout)
            Spacer()
            Button {
              model.message = nil
            } label: {
              Image(systemName: "xmark")
            }.buttonStyle(.plain)
          }.padding(12).background(Studio.mint.opacity(0.1))
        }
        if model.showUpdateBanner, let update = model.availableUpdate {
          HStack(spacing: 10) {
            Label("MarketPulse \(update.version) is available.", systemImage: "arrow.down.circle")
              .font(.system(size: 11)).foregroundStyle(Studio.mint)
            Spacer()
            Button("Release Notes") { model.openReleaseNotes() }.controlSize(.small)
            Button("Copy Install Command") { model.copyInstallCommand() }.controlSize(.small)
              .help("Paste it into Terminal to install the update. Your portfolio isn't changed.")
            Button {
              model.dismissUpdate()
            } label: {
              Image(systemName: "xmark")
            }.buttonStyle(.plain).help("Hide until the next version")
          }.padding(.horizontal, 30).padding(.vertical, 8).background(Studio.mint.opacity(0.08))
        }
        if let payload = model.desktop {
          if payload.demo {
            notice(
              "Demo portfolio · Fictional data · Read-only", icon: "sparkles", color: Studio.mint
            ).overlay(alignment: .trailing) {
              if !model.demoOnly {
                Button("Leave demo") { model.leaveDemo() }.controlSize(.small).disabled(model.saving)
                  .padding(.trailing, 30)
              }
            }
          }
          if payload.status.stale {
            notice(
              "Cached quotes are in use. Values may be out of date.", icon: "wifi.exclamationmark",
              color: Studio.warn)
          }
          if !payload.warnings.isEmpty {
            notice(
              payload.warnings.joined(separator: " · "), icon: "exclamationmark.circle",
              color: Studio.warn)
          }
          workspace(payload)
        } else if model.loading {
          Spacer()
          ProgressView("Opening your portfolio…")
          Spacer()
        } else {
          ContentUnavailableView {
            Label("Your portfolio is waiting", systemImage: "chart.xyaxis.line")
          } description: {
            Text("Install the CLI from this checkout, then run marketpulse desktop install.")
          } actions: {
            Button("Try again") { model.refresh() }
          }
        }
        footer
      }
      .background(Studio.background)
    }
    .tint(Studio.mint)
    .foregroundStyle(Studio.text)
    .frame(minWidth: 980, minHeight: 680)
    .toolbar {
      ToolbarItemGroup {
        Button {
          model.togglePrivacy()
        } label: {
          Image(systemName: (model.status?.privacy ?? false) ? "eye.slash" : "eye")
        }
        .help("Toggle privacy mode")
        .disabled(!model.canEdit)
        Button {
          model.refresh()
        } label: {
          Image(systemName: "arrow.clockwise")
        }
        .help("Refresh portfolio (⌘R)").keyboardShortcut("r")
        .disabled(model.loading || model.saving)
        Button {
          draft.sheet = .transaction
        } label: {
          Label("Record transaction", systemImage: "plus")
        }
        .disabled(!model.canEdit).keyboardShortcut("n")
      }
    }
    .sheet(item: $draft.sheet, onDismiss: presentWelcome) { item in
      switch item {
      case .transaction: TransactionSheet(model: model)
      case .editTransaction: TransactionSheet(model: model, editing: draft.editing)
      case .account: AccountSheet(model: model)
      case .editAccount: AccountSheet(model: model, editing: draft.editingAccount)
      case .room: RoomSheet(model: model, type: draft.roomType)
      case .alert: AlertSheet(model: model)
      case .fixedAsset: AssetSheet(model: model, kind: "FIXED")
      case .manualAsset: AssetSheet(model: model, kind: "MANUAL")
      case .valuation: AssetSheet(model: model, kind: "VALUE", symbol: draft.assetSymbol)
      case .assetClass: AssetClassSheet(model: model, symbol: draft.assetSymbol)
      case .targets: TargetsSheet(model: model)
      case .welcome:
        WelcomeSheet(
          model: model,
          createAccount: {
            model.leaveDemo()
            draft.sheet = .account
          },
          importCSV: {
            draft.sheet = nil
            // After the sheet closes (the file panel is modal, and the import sheet replaces this
            // one) and, from the demo, once the real portfolio is back so editing is allowed.
            Task {
              await model.leaveDemoAndReload()
              model.chooseImport()
            }
          },
          exploreDemo: {
            draft.sheet = nil
            model.enterDemo()
          })
      }
    }
    .onChange(of: model.welcomeRequest, initial: true) { _, _ in presentWelcome() }
    .onChange(of: model.desktop?.accounts.map(\.id)) { _, ids in
      // An archived account no longer filters Holdings and Activity.
      if draft.accountFilter != 0 && ids?.contains(draft.accountFilter) != true { draft.accountFilter = 0 }
    }
    .onChange(of: model.workspaceRequest, initial: true) { _, request in
      guard let request else { return }
      draft.section = request
      model.workspaceRequest = nil
    }
    .sheet(
      isPresented: $model.showImport,
      onDismiss: {
        model.closeImport()
        presentWelcome()
      }
    ) {
      ImportSheet(model: model)
    }
  }

  /// Shows a requested welcome, or leaves the request pending until the open sheet closes:
  /// never cover a form the user is filling in.
  private func presentWelcome() {
    guard model.welcomeRequest != nil else { return }
    if draft.sheet == .welcome {
      model.welcomeRequest = nil
      return
    }
    guard draft.sheet == nil && !model.showImport else { return }
    model.welcomeRequest = nil
    model.markWelcomeShown()
    draft.sheet = .welcome
  }

  private var sidebar: some View {
    VStack(alignment: .leading, spacing: 0) {
      HStack(spacing: 10) {
        Image(systemName: "waveform.path.ecg").font(.system(size: 24)).foregroundStyle(Studio.mint)
        VStack(alignment: .leading, spacing: 2) {
          Text("MarketPulse").font(.system(size: 17, weight: .semibold))
          Text("YOUR PERSONAL LEDGER").font(.system(size: 8, weight: .medium)).tracking(1.4)
            .foregroundStyle(Studio.muted)
        }
      }.padding(.horizontal, 20).padding(.top, 28).padding(.bottom, 30)
      Text("WORKSPACE").font(.system(size: 10, weight: .medium)).tracking(1.5).foregroundStyle(
        Studio.muted
      ).padding(.leading, 22)
      List(Workspace.allCases, selection: $draft.section) { item in
        Label(item.rawValue, systemImage: item.icon).padding(.vertical, 7).tag(item)
      }.listStyle(.sidebar).scrollContentBackground(.hidden)
      Spacer()
      VStack(alignment: .leading, spacing: 14) {
        Button {
          model.chooseImport()
        } label: {
          Label("Import a CSV", systemImage: "square.and.arrow.down")
        }.disabled(!model.canEdit)
        Button {
          model.exportLedger()
        } label: {
          Label("Export ledger", systemImage: "square.and.arrow.up")
        }.disabled(!model.canEdit)
        Button {
          model.openTUI()
        } label: {
          Label("Open terminal", systemImage: "terminal")
        }.disabled(model.demo)
        Divider().overlay(Studio.line)
        Label("Stored on your Mac", systemImage: "lock.shield").font(.system(size: 11))
          .foregroundStyle(Studio.muted)
      }.buttonStyle(.plain).font(.system(size: 12)).padding(22)
    }.background(Studio.panel)
  }

  private var header: some View {
    HStack(alignment: .center) {
      VStack(alignment: .leading, spacing: 7) {
        Text("PORTFOLIO / \((draft.section ?? .overview).rawValue.uppercased())")
          .font(.system(size: 9, weight: .medium)).tracking(1.8).foregroundStyle(Studio.muted)
        Text((draft.section ?? .overview).rawValue).font(.system(size: 28, weight: .semibold))
        Text((draft.section ?? .overview).subtitle).font(.system(size: 12)).foregroundStyle(
          Studio.muted)
      }
      Spacer()
      if draft.section == .holdings || draft.section == .activity {
        HStack {
          Image(systemName: "magnifyingglass").foregroundStyle(Studio.muted)
          TextField(
            "Search \((draft.section ?? .holdings).rawValue.lowercased())", text: $draft.search
          ).textFieldStyle(.plain)
        }.padding(10).frame(width: 210).background(
          Studio.panel, in: RoundedRectangle(cornerRadius: 8))
      } else {
        Text(Date.now, format: .dateTime.weekday(.abbreviated).month(.abbreviated).day())
          .font(.system(size: 12)).foregroundStyle(Studio.muted)
      }
    }.padding(.horizontal, 30).padding(.top, 26).padding(.bottom, 24)
  }

  @ViewBuilder private func workspace(_ p: DesktopPayload) -> some View {
    switch draft.section ?? .overview {
    case .overview:
      OverviewWorkspace(
        payload: p, newAccount: { draft.sheet = .account },
        newTransaction: { draft.sheet = .transaction }, welcome: { draft.sheet = .welcome },
        canEdit: model.canEdit)
    case .holdings:
      HoldingsWorkspace(
        payload: p, search: draft.search, accountFilter: $draft.accountFilter, canEdit: model.canEdit,
        showSheet: { sheet, symbol in
          draft.assetSymbol = symbol
          draft.sheet = sheet
        })
    case .allocation:
      AllocationWorkspace(
        payload: p, canEdit: model.canEdit, setTargets: { draft.sheet = .targets },
        showHoldings: { draft.section = .holdings })
    case .activity:
      ActivityWorkspace(
        payload: p, model: model, search: draft.search, accountFilter: $draft.accountFilter,
        edit: { t in
          draft.editing = t
          draft.sheet = .editTransaction
        })
    case .accounts:
      AccountsWorkspace(
        payload: p, canEdit: model.canEdit, add: { draft.sheet = .account },
        edit: { account in
          draft.editingAccount = account
          draft.sheet = .editAccount
        },
        setRoom: { type in
          draft.roomType = type
          draft.sheet = .room
        },
        showArchived: { model.showSettingsWindow(tab: SettingsWindowController.dataTab) })
    case .watchlist: WatchlistWorkspace(model: model, addAlert: { draft.sheet = .alert })
    case .income: IncomeWorkspace(payload: p)
    case .tax: TaxWorkspace(model: model)
    case .automation: AutomationWorkspace(model: model)
    }
  }

  private var footer: some View {
    HStack(spacing: 8) {
      Circle().fill(model.errorMessage != nil ? Studio.red : Studio.mint).frame(width: 5, height: 5)
      Text(
        model.loading
          ? "Refreshing portfolio…" : model.saving ? "Saving…" : model.demo ? "Demo portfolio" : "Local ledger")
      if let date = model.lastUpdated {
        Text("· Updated \(date.formatted(date: .omitted, time: .shortened))")
      }
      Spacer()
      Text("\(model.status?.base ?? "CAD") · Quotes may be delayed")
    }.font(.system(size: 10)).foregroundStyle(Studio.muted).padding(.horizontal, 30).padding(
      .vertical, 12
    )
    .overlay(alignment: .top) { Rectangle().fill(Studio.line).frame(height: 1) }
  }

  private func notice(_ text: String, icon: String, color: Color) -> some View {
    Label(text, systemImage: icon).font(.system(size: 11)).foregroundStyle(color)
      .frame(maxWidth: .infinity, alignment: .leading).padding(.horizontal, 30).padding(
        .vertical, 10
      ).background(color.opacity(0.08))
  }
}

private struct Surface<Content: View>: View {
  let title: String
  let trailing: String
  @ViewBuilder var content: Content
  init(_ title: String, trailing: String = "", @ViewBuilder content: () -> Content) {
    self.title = title
    self.trailing = trailing
    self.content = content()
  }
  var body: some View {
    VStack(alignment: .leading, spacing: 20) {
      HStack {
        Text(title).font(.system(size: 14, weight: .semibold))
        Spacer()
        Text(trailing).font(.system(size: 10)).foregroundStyle(Studio.muted)
      }
      content
    }.padding(22).frame(maxWidth: .infinity, alignment: .leading)
      .background(Studio.panel, in: RoundedRectangle(cornerRadius: 12))
      .overlay(RoundedRectangle(cornerRadius: 12).stroke(Studio.line))
  }
}

private struct Metric: View {
  let title: String
  let value: String
  let detail: String
  var color: Color = Studio.text
  var body: some View {
    VStack(alignment: .leading, spacing: 10) {
      Text(title.uppercased()).font(.system(size: 9, weight: .medium)).tracking(1.3)
        .foregroundStyle(Studio.muted)
      Text(value).font(.system(size: 25, weight: .medium)).monospacedDigit().foregroundStyle(color)
      Text(detail).font(.system(size: 10)).foregroundStyle(Studio.muted)
    }.frame(maxWidth: .infinity, alignment: .leading).padding(20).background(
      Studio.panel, in: RoundedRectangle(cornerRadius: 10))
  }
}

private struct OverviewWorkspace: View {
  @StateObject private var draft = OverviewWorkspaceDraft()
  let payload: DesktopPayload
  let newAccount: () -> Void
  let newTransaction: () -> Void
  let welcome: () -> Void
  let canEdit: Bool
  private var s: StatusPayload { payload.status }
  private var points: [HistoryPoint] {
    if draft.period == 0 { return s.history }
    let since = Calendar.current.date(byAdding: .day, value: -draft.period, to: .now) ?? .now
    // Snapshot dates are local calendar days; compare in local time, not UTC.
    let iso = Format.isoDay(since)
    return s.history.filter { $0.date >= iso }
  }
  var body: some View {
    ScrollView {
      VStack(spacing: 20) {
        if payload.accounts.isEmpty {
          ContentUnavailableView {
            Label("Make room for your first investment", systemImage: "leaf")
          } description: {
            Text("Create an account, then record a transaction or import your broker's CSV.")
          } actions: {
            Button("Create an account", action: newAccount).buttonStyle(.borderedProminent)
              .disabled(!canEdit)
            Button("Other ways to start…", action: welcome)
          }
        }
        HStack(spacing: 14) {
          Metric(
            title: "Net worth", value: Format.money(s.netWorth, s.base, privacy: s.privacy),
            detail: "Across \(payload.accounts.count) accounts")
          Metric(
            title: "Today's change",
            value: Format.money(s.dayChange, s.base, privacy: s.privacy, sign: true),
            detail: Format.pct(s.dayChangePct) + " today", color: Studio.trend(s.dayChange))
          Metric(
            title: "Unrealized gain",
            value: Format.money(s.unrealized, s.base, privacy: s.privacy, sign: true),
            detail: Format.pct(s.unrealizedPct) + " on cost", color: Studio.trend(s.unrealized))
        }
        Surface("Portfolio value", trailing: "\(s.base) · DAILY SNAPSHOTS") {
          HStack {
            Text(s.privacy ? "Values hidden" : "The bigger picture").font(.system(size: 12))
              .foregroundStyle(Studio.muted)
            Spacer()
            Picker("History range", selection: $draft.period) {
              Text("1M").tag(30)
              Text("3M").tag(90)
              Text("6M").tag(180)
              Text("1Y").tag(365)
              Text("ALL").tag(0)
            }.pickerStyle(.segmented).frame(width: 270)
          }
          if s.privacy {
            ContentUnavailableView("Chart hidden in privacy mode", systemImage: "eye.slash").frame(
              height: 215)
          } else if points.count < 2 {
            ContentUnavailableView(
              "Your history starts here", systemImage: "chart.xyaxis.line",
              description: Text(
                "MarketPulse saves a snapshot of your portfolio each day it runs with fresh prices. Your chart fills in from there."
              )
            ).frame(height: 215)
          } else {
            Chart(points) { point in
              AreaMark(
                x: .value("Date", chartDate(point.date)), yStart: .value("Baseline", lowerBound),
                yEnd: .value("Value", point.value)
              )
              .foregroundStyle(
                LinearGradient(
                  colors: [Studio.mint.opacity(0.22), Studio.mint.opacity(0.01)], startPoint: .top,
                  endPoint: .bottom))
              LineMark(x: .value("Date", chartDate(point.date)), y: .value("Value", point.value))
                .foregroundStyle(Studio.mint).lineStyle(StrokeStyle(lineWidth: 2.5))
            }
            .chartYScale(domain: lowerBound...upperBound)
            .chartYAxis {
              AxisMarks(position: .trailing, values: .automatic(desiredCount: 4)) { value in
                AxisGridLine().foregroundStyle(Studio.line)
                AxisValueLabel {
                  if let v = value.as(Double.self) {
                    Text(v, format: .number.notation(.compactName)).foregroundStyle(Studio.muted)
                  }
                }
              }
            }
            .chartXAxis {
              AxisMarks(values: .automatic(desiredCount: 5)) { _ in
                AxisValueLabel(format: .dateTime.month(.abbreviated).day()).foregroundStyle(
                  Studio.muted)
              }
            }
            .chartXSelection(value: .constant(nil as Date?))
            .frame(height: 215)
          }
        }
        HStack(alignment: .top, spacing: 20) {
          Surface("Allocation", trailing: "BY ASSET CLASS") {
            if s.privacy || payload.allocation.isEmpty {
              Text(
                s.privacy
                  ? "Allocation values hidden"
                  : "Your allocation will appear after your first transaction."
              ).foregroundStyle(Studio.muted).frame(height: 180)
            } else {
              HStack(spacing: 20) {
                Chart(payload.allocation.filter { $0.value > 0 }) { b in
                  SectorMark(
                    angle: .value("Value", b.value), innerRadius: .ratio(0.74), angularInset: 3
                  )
                  .foregroundStyle(
                    Studio.colors[
                      payload.allocation.firstIndex(where: { $0.id == b.id })! % Studio.colors.count
                    ])
                }.frame(width: 150, height: 150)
                  .chartBackground { _ in
                    VStack(spacing: 4) {
                      Text("\(payload.positions.count)").font(.system(size: 24, weight: .medium))
                      Text("positions").font(.system(size: 10)).foregroundStyle(Studio.muted)
                    }
                  }
                VStack(spacing: 13) {
                  ForEach(Array(payload.allocation.enumerated()), id: \.element.id) { i, bucket in
                    HStack {
                      Circle().fill(Studio.colors[i % Studio.colors.count]).frame(
                        width: 6, height: 6)
                      Text(bucket.label).font(.system(size: 11))
                      Spacer()
                      Text(String(format: "%.1f%%", bucket.weight)).font(.system(size: 11))
                        .monospacedDigit().foregroundStyle(Studio.muted)
                    }
                  }
                }
              }.padding(.vertical, 10)
            }
          }
          Surface("Your accounts", trailing: "\(payload.accounts.count) TOTAL") {
            if payload.accounts.isEmpty {
              Button("Add your first account", action: newAccount).disabled(!canEdit)
            }
            ForEach(payload.accounts) { account in
              let value = s.accounts.first(where: { $0.name == account.name })?.value ?? 0
              HStack(spacing: 12) {
                Image(systemName: "building.columns").foregroundStyle(Studio.mint).frame(
                  width: 32, height: 32
                ).background(Studio.mint.opacity(0.08), in: RoundedRectangle(cornerRadius: 8))
                VStack(alignment: .leading, spacing: 4) {
                  Text(account.name).font(.system(size: 12, weight: .medium))
                  Text(
                    account.institution.isEmpty
                      ? account.type : "\(account.type) · \(account.institution)"
                  ).font(.system(size: 10)).foregroundStyle(Studio.muted)
                }
                Spacer()
                Text(Format.money(value, s.base, privacy: s.privacy, decimals: 0)).font(
                  .system(size: 12)
                ).monospacedDigit()
              }
            }
          }
        }
        Surface("Recent activity", trailing: "YOUR RECORDED TRANSACTIONS") {
          if payload.activity.isEmpty {
            Button("Record a transaction", action: newTransaction).disabled(
              !canEdit || payload.accounts.isEmpty)
          }
          ForEach(payload.activity.prefix(4)) { t in
            HStack {
              Text(TransactionEntry.label(t.type)).font(.system(size: 10, weight: .medium)).foregroundStyle(
                Studio.mint
              ).frame(width: 75, alignment: .leading)
              Text(t.symbol.isEmpty ? accountName(t.accountId, payload) : t.symbol).font(
                .system(size: 12, weight: .medium))
              Text(accountName(t.accountId, payload)).font(.system(size: 11)).foregroundStyle(
                Studio.muted)
              Spacer()
              Text(t.date).font(.system(size: 10)).foregroundStyle(Studio.muted)
              Text(activityAmount(t, privacy: s.privacy)).font(.system(size: 12))
                .monospacedDigit().foregroundStyle(activityColor(t))
                .frame(width: 120, alignment: .trailing)
            }
          }
        }
      }.padding(.horizontal, 30).padding(.bottom, 24)
    }
  }
  private var lowerBound: Double { (points.map(\.value).min() ?? 0) * 0.97 }
  private var upperBound: Double { max(lowerBound + 1, (points.map(\.value).max() ?? 1) * 1.02) }
}

private func chartDate(_ raw: String) -> Date {
  ISO8601DateFormatter().date(from: raw + "T12:00:00Z") ?? .now
}
private func monthLabel(_ raw: String) -> String {
  guard let date = ISO8601DateFormatter().date(from: raw + "-15T12:00:00Z") else { return raw }
  return date.formatted(.dateTime.month(.abbreviated).year(.twoDigits))
}
private func accountName(_ id: Int, _ payload: DesktopPayload) -> String {
  payload.accounts.first { $0.id == id }?.name ?? "Account #\(id)"
}
/// Signed from the account's point of view: + money in, − money out. Splits show their ratio,
/// and share-only entries (DRIP, transfers) carry no sign.
private func activityAmount(_ t: DesktopTransaction, privacy: Bool) -> String {
  if t.type == "SPLIT" { return t.ratio > 0 ? "×\(t.ratio.formatted())" : "—" }
  // Without a market price a transfer has no value to show, only what moved.
  if t.type == "TRANSFER" && t.price == 0 {
    return privacy ? "\(Format.mask) units" : "\(t.quantity.formatted(.number.precision(.fractionLength(0...4)))) units"
  }
  return Format.money(t.signedValue, t.currency, privacy: privacy, sign: t.direction != 0)
}
private func activityColor(_ t: DesktopTransaction) -> Color {
  t.direction == 0 ? Studio.muted : Studio.trend(t.signedValue)
}

private struct AccountFilter: View {
  let accounts: [DesktopAccount]
  @Binding var selected: Int
  var body: some View {
    Picker("Account", selection: $selected) {
      Text("All accounts").tag(0)
      ForEach(accounts) { Text($0.name).tag($0.id) }
    }.frame(width: 240)
  }
}

private struct HoldingsWorkspace: View {
  @StateObject private var draft = HoldingsWorkspaceDraft()
  let payload: DesktopPayload
  let search: String
  @Binding var accountFilter: Int
  let canEdit: Bool
  /// Opens an asset sheet, for the given symbol where it needs one.
  let showSheet: (DesktopSheet, String) -> Void
  private var rows: [DesktopPosition] {
    payload.positions.filter {
      (accountFilter == 0 || $0.accountId == accountFilter)
        && (search.isEmpty
          || "\($0.symbol) \($0.name) \($0.account)".localizedCaseInsensitiveContains(search))
    }
    .sorted { draft.sortByValue ? ($0.value ?? 0) > ($1.value ?? 0) : $0.symbol < $1.symbol }
  }
  private func asset(_ symbol: String) -> DesktopAsset? { payload.assets?.first { $0.symbol == symbol } }
  var body: some View {
    VStack(alignment: .leading, spacing: 16) {
      HStack {
        AccountFilter(accounts: payload.accounts, selected: $accountFilter)
        Spacer()
        Menu {
          Button("GIC or bond…") { showSheet(.fixedAsset, "") }
          Button("Property or other asset…") { showSheet(.manualAsset, "") }
        } label: {
          Label("Add asset", systemImage: "plus")
        }.fixedSize().disabled(!canEdit || payload.accounts.isEmpty || payload.assets == nil)
          .help("Add something the market can't price: a GIC or bond valued by its interest, or an asset you value yourself.")
        Button(draft.sortByValue ? "Sort: value ↓" : "Sort: symbol A–Z") {
          draft.sortByValue.toggle()
        }.buttonStyle(.bordered)
        Text("\(rows.count) positions").foregroundStyle(Studio.muted)
      }.font(.system(size: 11)).padding(.horizontal, 30)
      Table(rows, selection: $draft.selection) {
        TableColumn("Asset") { p in
          VStack(alignment: .leading, spacing: 3) {
            Text(p.symbol).fontWeight(.medium)
            Text(p.name).font(.system(size: 10)).foregroundStyle(Studio.muted).lineLimit(1)
            if let summary = asset(p.symbol)?.summary {
              Text(summary).font(.system(size: 10)).foregroundStyle(Studio.muted).lineLimit(1)
            }
          }.padding(.vertical, 6)
        }.width(min: 140, ideal: 190)
        TableColumn("Account", value: \.account).width(min: 100, ideal: 140)
        TableColumn("Quantity") { p in
          Text(
            payload.status.privacy
              ? Format.mask : p.quantity.formatted(.number.precision(.fractionLength(0...4)))
          ).monospacedDigit()
        }.width(80)
        TableColumn("Price") { p in
          Text("\(Format.price(p.price)) \(p.currency)\(p.stale ? " · cached" : "")")
            .foregroundStyle(Studio.muted).monospacedDigit()
        }.width(125)
        TableColumn("Value (\(payload.status.base))") { p in
          Text(Format.money(p.value, payload.status.base, privacy: payload.status.privacy))
            .monospacedDigit()
        }.width(120)
        TableColumn("Gain") { p in
          Text(
            Format.money(p.gain, payload.status.base, privacy: payload.status.privacy, sign: true)
          ).foregroundStyle(Studio.trend(p.gain)).monospacedDigit()
        }.width(110)
        TableColumn("Today") { p in
          Text(p.dayChangePct.map(Format.pct) ?? "—").foregroundStyle(Studio.trend(p.dayChangePct))
            .monospacedDigit()
        }.width(75)
      }.scrollContentBackground(.hidden).alternatingRowBackgrounds(.disabled)
        .contextMenu(forSelectionType: DesktopPosition.ID.self) { ids in
          if ids.count == 1, let p = rows.first(where: { ids.contains($0.id) }) {
            if asset(p.symbol)?.manual == true {
              Button("Record a valuation…") { showSheet(.valuation, p.symbol) }.disabled(!canEdit)
            }
            Button("Change asset class…") { showSheet(.assetClass, p.symbol) }
              .disabled(!canEdit || payload.assets == nil)
          }
        }
        .overlay {
          if rows.isEmpty {
            ContentUnavailableView(
              "No positions to show", systemImage: "chart.pie",
              description: Text("Record a buy, or adjust your search and account filter."))
          }
        }
    }
  }
}

/// The asset-class mix against the user's targets (`marketpulse allocation`). Suggestions only.
private struct AllocationWorkspace: View {
  let payload: DesktopPayload
  let canEdit: Bool
  let setTargets: () -> Void
  let showHoldings: () -> Void
  private var s: StatusPayload { payload.status }
  private var rows: [RebalanceRow] { payload.rebalance ?? [] }
  var body: some View {
    ScrollView {
      VStack(spacing: 20) {
        if payload.targets == nil {
          ContentUnavailableView(
            "Update MarketPulse to set targets", systemImage: "scope",
            description: Text("This version of the engine doesn't report allocation targets."))
        } else if rows.isEmpty {
          ContentUnavailableView {
            Label("Set the mix you're aiming for", systemImage: "scope")
          } description: {
            Text(
              "Give each asset class a target percentage, and MarketPulse shows how far your portfolio is from it."
            )
          } actions: {
            Button("Set targets…", action: setTargets).buttonStyle(.borderedProminent).disabled(!canEdit)
          }
        } else {
          Surface("Against your targets", trailing: "BY ASSET CLASS · \(s.base)") {
            HStack {
              Text("Allocated: \(percent(payload.targets?.map(\.weight).reduce(0, +) ?? 0))")
                .font(.system(size: 12)).foregroundStyle(Studio.muted)
              Spacer()
              Button("Change targets…", action: setTargets).disabled(!canEdit)
            }
            if s.privacy {
              ContentUnavailableView("Allocation hidden in privacy mode", systemImage: "eye.slash").frame(
                height: 160)
            } else {
              targetsGrid
            }
            Text(
              "Suggestions only: MarketPulse never places trades. Amounts use today's prices and exchange rates, and leave out fees and taxes. A symbol's class comes from its listing; to change it, right-click it in Holdings."
            ).font(.system(size: 11)).foregroundStyle(Studio.muted).fixedSize(horizontal: false, vertical: true)
            HStack {
              Spacer()
              Button("Show Holdings", action: showHoldings)
            }
          }
        }
      }.padding(.horizontal, 30).padding(.bottom, 24)
    }
  }
  private var targetsGrid: some View {
    Grid(alignment: .trailing, horizontalSpacing: 18, verticalSpacing: 12) {
      GridRow {
        heading("Class").gridColumnAlignment(.leading)
        heading("Now")
        heading("Target")
        heading("Drift")
        heading("To reach the target")
      }
      Divider().overlay(Studio.line).gridCellUnsizedAxes(.horizontal)
      ForEach(rows) { row in
        GridRow {
          Text(row.label).fontWeight(.medium)
          Text(percent(row.weight)).monospacedDigit()
          Text(row.target > 0 ? percent(row.target) : "—").monospacedDigit().foregroundStyle(Studio.muted)
          Text(drift(row.drift)).monospacedDigit()
            .foregroundStyle(abs(row.drift) >= 5 ? Studio.warn : Studio.muted)
          Text(suggestion(row)).monospacedDigit()
        }
      }
    }.font(.system(size: 12))
  }
  private func heading(_ text: String) -> some View {
    Text(text).font(.system(size: 10, weight: .medium)).foregroundStyle(Studio.muted)
  }
  private func percent(_ value: Double) -> String {
    value.formatted(.number.precision(.fractionLength(1))) + "%"
  }
  private func drift(_ value: Double) -> String {
    (value > 0 ? "+" : "") + value.formatted(.number.precision(.fractionLength(1))) + " pts"
  }
  /// The amount to buy or sell, or nothing once it's within a rounding error.
  private func suggestion(_ row: RebalanceRow) -> String {
    if s.privacy { return Format.mask }
    if abs(row.delta) < 1 { return "On target" }
    let amount = Format.money(abs(row.delta), s.base, privacy: false, decimals: 0)
    return row.delta > 0 ? "Add \(amount)" : "Reduce by \(amount)"
  }
}

private struct ActivityWorkspace: View {
  let payload: DesktopPayload
  @ObservedObject var model: StatusModel
  let search: String
  @Binding var accountFilter: Int
  let edit: (DesktopTransaction) -> Void
  @StateObject private var draft = ActivityWorkspaceDraft()
  private var rows: [DesktopTransaction] {
    payload.activity.filter {
      (accountFilter == 0 || $0.accountId == accountFilter)
        && (search.isEmpty
          || "\($0.symbol) \($0.type) \($0.note)".localizedCaseInsensitiveContains(search))
    }
  }
  var body: some View {
    VStack(alignment: .leading, spacing: 16) {
      HStack {
        AccountFilter(accounts: payload.accounts, selected: $accountFilter)
        Spacer()
        Text("\(rows.count) transactions · + money in, − money out, in original currency").font(
          .system(size: 11))
          .foregroundStyle(Studio.muted)
      }.padding(.horizontal, 30)
      Table(rows, selection: $draft.selection) {
        TableColumn("Date", value: \.date).width(100)
        TableColumn("Type") { t in Text(TransactionEntry.label(t.type)).modifier(RowTint(Studio.mint)) }.width(90)
        TableColumn("Symbol", value: \.symbol).width(85)
        TableColumn("Account") { t in
          Text(
            t.targetAccount.isEmpty
              ? accountName(t.accountId, payload)
              : "\(accountName(t.accountId, payload)) → \(t.targetAccount)")
        }.width(min: 130, ideal: 160)
        TableColumn("Amount") { t in
          Text(activityAmount(t, privacy: payload.status.privacy)).monospacedDigit()
            .modifier(RowTint(activityColor(t)))
        }.width(120)
        TableColumn("Note", value: \.note)
      }.scrollContentBackground(.hidden).alternatingRowBackgrounds(.disabled)
        .contextMenu(forSelectionType: DesktopTransaction.ID.self) { ids in
          if let t = only(ids) {
            Button("Edit…") { edit(t) }.disabled(!canEdit(t))
            Button("Delete…", role: .destructive) { draft.deleting = t }.disabled(!model.canEdit)
          }
        } primaryAction: { ids in
          if let t = only(ids), canEdit(t) { edit(t) }
        }
        .onDeleteCommand {
          if model.canEdit, let id = draft.selection, let t = only([id]) { draft.deleting = t }
        }
        .overlay {
          if rows.isEmpty {
            ContentUnavailableView("No matching activity", systemImage: "arrow.left.arrow.right")
          }
        }
    }
    .confirmationDialog(
      "Delete this transaction?",
      isPresented: Binding(get: { draft.deleting != nil }, set: { if !$0 { draft.deleting = nil } }),
      presenting: draft.deleting
    ) { t in
      Button("Delete", role: .destructive) {
        Task {
          await model.perform(
            ["txn", "delete", "--yes"] + t.revisionArguments + ["--", String(t.id)],
            success: "Transaction deleted")
        }
      }
      Button("Cancel", role: .cancel) {}
    } message: { t in
      Text(
        "\(describe(t)). Holdings, cost base, and gains are worked out again without it. This can't be undone."
      )
    }
  }

  private func only(_ ids: Set<Int>) -> DesktopTransaction? {
    ids.count == 1 ? rows.first { ids.contains($0.id) } : nil
  }
  /// Transfers, DRIPs, splits and returns of capital can be deleted and recorded again, not edited.
  private func canEdit(_ t: DesktopTransaction) -> Bool {
    model.canEdit && TransactionEntry.editableTypes.contains(t.type)
  }
  private func describe(_ t: DesktopTransaction) -> String {
    [
      t.date, [TransactionEntry.label(t.type), t.symbol].filter { !$0.isEmpty }.joined(separator: " "),
      activityAmount(t, privacy: payload.status.privacy), accountName(t.accountId, payload),
    ].joined(separator: " · ")
  }
}

/// A table cell's colour, dropped while its row is selected so the text takes the selection's
/// own (white on the accent colour) instead of green or red on blue.
private struct RowTint: ViewModifier {
  @Environment(\.backgroundProminence) private var prominence
  let color: Color
  init(_ color: Color) { self.color = color }
  func body(content: Content) -> some View {
    if prominence == .increased { content } else { content.foregroundStyle(color) }
  }
}

private final class ActivityWorkspaceDraft: ObservableObject {
  @Published var selection: Int?
  @Published var deleting: DesktopTransaction?
}

private struct AccountsWorkspace: View {
  let payload: DesktopPayload
  let canEdit: Bool
  let add: () -> Void
  let edit: (DesktopAccount) -> Void
  let setRoom: (String) -> Void
  let showArchived: () -> Void
  /// Room types worth showing: ones with room entered, or an account that uses them. With
  /// neither, all of them, so room can be entered before the account is opened.
  private var roomTypes: [String] {
    let used = ContributionRoom.types.filter { type in
      payload.room.contains { $0.accountType == type } || payload.accounts.contains { $0.type == type }
    }
    return used.isEmpty ? ContributionRoom.types : used
  }
  var body: some View {
    let privacy = payload.status.privacy
    ScrollView {
      VStack(spacing: 18) {
        HStack {
          Text("\(payload.accounts.count) active accounts").foregroundStyle(Studio.muted)
          if let archived = payload.archivedAccounts?.count, archived > 0 {
            Button(archived == 1 ? "1 archived" : "\(archived) archived", action: showArchived)
              .buttonStyle(.link).help("Archived accounts are listed in Settings › Data, to unarchive them")
          }
          Spacer()
          Button("Add account", systemImage: "plus", action: add).disabled(!canEdit)
        }
        ForEach(payload.accounts) { a in
          Surface(a.name, trailing: a.type) {
            HStack {
              VStack(alignment: .leading, spacing: 8) {
                Text(a.institution.isEmpty ? "Personal account" : a.institution).foregroundStyle(
                  Studio.muted)
                Text(
                  (a.trackCash ? "Holdings and cash are tracked" : "Holdings are tracked; cash is excluded")
                    + " · \(a.currency)"
                ).font(.system(size: 11)).foregroundStyle(Studio.muted)
                Button("Edit account…") { edit(a) }.disabled(!canEdit).controlSize(.small)
              }
              Spacer()
              Text(
                Format.money(
                  payload.status.accounts.first { $0.name == a.name }?.value ?? 0,
                  payload.status.base, privacy: privacy)
              )
              .font(.system(size: 24, weight: .medium)).monospacedDigit()
            }
          }.contextMenu {
            Button("Edit Account…") { edit(a) }.disabled(!canEdit)
          }
        }
        Surface("Contribution room", trailing: "IN CAD · FROM THE ROOM YOU ENTERED") {
          ForEach(roomTypes, id: \.self) { type in
            let room = payload.room.first { $0.accountType == type }
            HStack {
              VStack(alignment: .leading, spacing: 4) {
                Text(type)
                Text(
                  room.map {
                    "From \(Format.money($0.startingRoom, "CAD", privacy: privacy)) on January 1, \(String($0.asOfYear))"
                  } ?? "Not set yet"
                ).font(.system(size: 11)).foregroundStyle(Studio.muted)
              }
              Spacer()
              if let room {
                Text(Format.money(room.remaining, "CAD", privacy: privacy)).foregroundStyle(
                  Studio.trend(room.remaining)
                ).monospacedDigit()
              }
              Button(room == nil ? "Set…" : "Update…") { setRoom(type) }.disabled(!canEdit)
                .controlSize(.small)
            }
          }
          // Room entered in the terminal for other types (e.g. RESP) is shown, not edited here.
          ForEach(payload.room.filter { !ContributionRoom.types.contains($0.accountType) }) { r in
            HStack {
              Text(r.accountType)
              Spacer()
              Text(Format.money(r.remaining, "CAD", privacy: privacy)).foregroundStyle(Studio.trend(r.remaining))
                .monospacedDigit()
            }
          }
          Text(
            "Deposits to your accounts of each type are subtracted. Confirm the figures against CRA My Account before contributing."
          ).font(.system(size: 11)).foregroundStyle(Studio.muted)
        }
      }.padding(.horizontal, 30).padding(.bottom, 24)
    }
  }
}

private struct WatchlistWorkspace: View {
  @StateObject private var draft = WatchlistWorkspaceDraft()
  @ObservedObject var model: StatusModel
  let addAlert: () -> Void
  var body: some View {
    ScrollView {
      VStack(spacing: 18) {
        HStack {
          TextField("Symbol, e.g. XEQT.TO", text: $draft.symbol).textFieldStyle(.roundedBorder)
            .frame(width: 240)
          Button("Watch", systemImage: "plus") {
            let s = draft.symbol
            Task {
              if await model.perform(
                ["watch", "add", "--", s.trimmingCharacters(in: .whitespaces).uppercased()],
                success: "Added to watchlist")
              {
                draft.symbol = ""
              }
            }
          }
          .disabled(!model.canEdit || draft.symbol.trimmingCharacters(in: .whitespaces).isEmpty)
          Spacer()
          Button("Create alert", systemImage: "bell", action: addAlert).disabled(!model.canEdit)
        }
        ForEach(model.status?.watchlist ?? []) { q in
          Surface(q.symbol, trailing: q.currency) {
            HStack {
              Text(q.name).foregroundStyle(Studio.muted).frame(
                maxWidth: .infinity, alignment: .leading)
              Sparkline(values: q.spark, color: Studio.trend(q.changePct)).frame(
                width: 100, height: 32)
              Text(Format.price(q.price)).monospacedDigit().frame(width: 90)
              Text(Format.pct(q.changePct)).monospacedDigit().foregroundStyle(
                Studio.trend(q.changePct)
              ).frame(width: 80)
              Button {
                Task {
                  await model.perform(
                    ["watch", "rm", "--", q.symbol], success: "Removed from watchlist")
                }
              } label: {
                Image(systemName: "minus.circle")
              }.buttonStyle(.plain).disabled(!model.canEdit).help("Remove \(q.symbol)")
            }
          }
        }
        if model.status?.watchlist.isEmpty ?? true {
          ContentUnavailableView(
            "Follow your next idea", systemImage: "star",
            description: Text(
              "Add a symbol to start your watchlist. Quote failures appear in Automation."))
        }
        Surface("Price alerts", trailing: "CHECKED ON EACH REFRESH") {
          if model.desktop?.alerts.isEmpty ?? true {
            Text(
              "Create an alert to get notified when a price or daily change meets your threshold."
            ).foregroundStyle(Studio.muted)
          }
          ForEach(model.desktop?.alerts ?? []) { a in
            HStack {
              Image(systemName: a.triggeredAt.isEmpty ? "bell" : "bell.badge").foregroundStyle(
                Studio.mint)
              VStack(alignment: .leading, spacing: 4) {
                Text(a.description)
                if !a.note.isEmpty {
                  Text(a.note).font(.system(size: 11)).foregroundStyle(Studio.muted)
                }
              }
              Spacer()
              Text(!a.active ? "Disabled" : a.triggeredAt.isEmpty ? "Watching" : "Triggered").font(
                .system(size: 11)
              ).foregroundStyle(Studio.muted)
              Button {
                Task {
                  await model.perform(["alerts", "rm", String(a.id)], success: "Alert removed")
                }
              } label: {
                Image(systemName: "trash")
              }.buttonStyle(.plain).disabled(!model.canEdit).help("Delete alert")
            }
          }
        }
      }.padding(.horizontal, 30).padding(.bottom, 24)
    }
  }
}

private struct IncomeWorkspace: View {
  let payload: DesktopPayload
  var body: some View {
    ScrollView {
      VStack(spacing: 20) {
        Metric(
          title: "Income this year",
          value: Format.money(
            payload.status.incomeYtd, payload.status.base, privacy: payload.status.privacy),
          detail: "Recorded dividends, reinvestments, and interest")
        Surface("Monthly income", trailing: "LAST 12 MONTHS · \(payload.status.base)") {
          if payload.status.privacy {
            ContentUnavailableView("Income hidden", systemImage: "eye.slash").frame(height: 230)
          } else {
            Chart(payload.incomeMonths) { p in
              BarMark(x: .value("Month", monthLabel(p.date)), y: .value("Income", p.value))
                .foregroundStyle(Studio.mint.gradient).cornerRadius(5)
            }
            .frame(height: 230)
          }
          Text("Amounts use today's exchange rates. Only income you've entered is included.").font(
            .system(size: 11)
          ).foregroundStyle(Studio.muted)
        }
      }.padding(.horizontal, 30).padding(.bottom, 24)
    }
  }
}

/// Capital gains per tax year from `marketpulse desktop tax`: the same figures as `marketpulse tax`.
private struct TaxWorkspace: View {
  @ObservedObject var model: StatusModel
  @StateObject private var draft = TaxWorkspaceDraft()
  private var privacy: Bool { model.status?.privacy ?? false }

  var body: some View {
    ScrollView {
      VStack(spacing: 20) {
        if let tax = model.tax {
          report(tax)
        } else if let error = model.taxError {
          ContentUnavailableView {
            Label("Couldn't work out your capital gains", systemImage: "exclamationmark.triangle")
          } description: {
            Text(error)
          } actions: {
            Button("Try Again") { model.loadTax(force: true) }
          }
        } else {
          ProgressView("Working out your capital gains…").frame(maxWidth: .infinity, minHeight: 260)
        }
      }.padding(.horizontal, 30).padding(.bottom, 24)
    }
    .onAppear { model.loadTax() }
    .onChange(of: model.taxKey) { _, _ in model.loadTax() }
  }

  @ViewBuilder private func report(_ tax: TaxPayload) -> some View {
    let year = tax.years.first { $0.year == draft.year } ?? tax.years.first
    HStack(spacing: 12) {
      if let year {
        Picker("Tax year", selection: Binding(get: { year.year }, set: { draft.year = $0 })) {
          ForEach(tax.years) { Text(String($0.year)).tag($0.year) }
        }.frame(width: 170)
      }
      Spacer()
      if model.taxLoading { ProgressView().controlSize(.small) }
      if let error = model.taxError {
        Label("Not updated", systemImage: "exclamationmark.triangle").foregroundStyle(Studio.warn)
          .help(error)
      }
      Button("Recalculate", systemImage: "arrow.clockwise") { model.loadTax(force: true) }
        .disabled(model.taxLoading)
        .help("Work the figures out again, with fresh exchange rates")
      if let year {
        Button("Export CSV…", systemImage: "square.and.arrow.up") { model.exportTax(year: year.year) }
          .disabled(model.demo || model.desktop == nil)
          .help(
            model.demo
              ? "Export is available for your own portfolio."
              : "Save \(String(year.year))'s sales as a spreadsheet for your accountant")
      }
    }.font(.system(size: 11))
    if let year {
      yearReport(year, tax)
    } else {
      ContentUnavailableView {
        Label("No sales in taxable accounts yet", systemImage: "percent")
      } description: {
        Text(
          "When you sell in a non-registered account, that year's capital gain or loss appears here, worked out with pooled cost base and each trade day's exchange rate. Gains in a TFSA, RRSP, or FHSA aren't taxed, so they aren't listed."
        )
      }.frame(minHeight: 220)
    }
    if !tax.issues.isEmpty {
      Surface("Needs attention", trailing: "MAY CHANGE THESE FIGURES") {
        ForEach(tax.issues) { issue in
          HStack(alignment: .top) {
            Text(issue.date).foregroundStyle(Studio.muted).frame(width: 90, alignment: .leading)
            Text(issue.message).foregroundStyle(Studio.warn).textSelection(.enabled)
              .fixedSize(horizontal: false, vertical: true)
          }.font(.system(size: 12))
        }
      }
    }
    roomSurface(tax)
    VStack(alignment: .leading, spacing: 6) {
      ForEach(tax.notes, id: \.self) { note in
        Label(note, systemImage: "info.circle")
      }
    }.font(.system(size: 11)).foregroundStyle(Studio.muted).frame(maxWidth: .infinity, alignment: .leading)
      .fixedSize(horizontal: false, vertical: true)
  }

  @ViewBuilder private func yearReport(_ year: TaxYearReport, _ tax: TaxPayload) -> some View {
    let base = tax.baseCurrency
    HStack(spacing: 14) {
      Metric(
        title: "Net capital gain",
        value: Format.money(year.netGain, base, privacy: privacy, sign: true),
        detail:
          "Proceeds \(Format.money(year.proceeds, base, privacy: privacy, decimals: 0)) · Cost \(Format.money(year.acb, base, privacy: privacy, decimals: 0))",
        color: Studio.trend(year.netGain))
      Metric(
        title: "Taxable capital gain",
        value: Format.money(year.taxable, base, privacy: privacy),
        detail: year.netGain < 0
          ? "A net loss isn't taxable; it can be carried to other years"
          : "\(percent(year.inclusionRate)) of the net gain is included")
      Metric(
        title: "Denied losses",
        value: Format.money(year.denied, base, privacy: privacy),
        detail: year.denied > 0 ? "Don't reduce this year's gains" : "None this year",
        color: year.denied > 0 ? Studio.warn : Studio.text)
    }
    if year.missingFx > 0 {
      Label(
        year.missingFx == 1
          ? "1 sale is missing an exchange rate, so it's left out of these totals. Recalculate when you're online."
          : "\(year.missingFx) sales are missing an exchange rate, so they're left out of these totals. Recalculate when you're online.",
        systemImage: "exclamationmark.triangle"
      ).font(.system(size: 11)).foregroundStyle(Studio.warn).frame(maxWidth: .infinity, alignment: .leading)
    }
    Surface("Realized gains by security", trailing: "\(String(year.year)) · \(base) · POOLED COST BASE") {
      securityHeader
      ForEach(year.securities) { security in
        DisclosureGroup(
          isExpanded: Binding(
            get: { draft.expanded.contains(security.symbol) },
            set: { open in
              if open { draft.expanded.insert(security.symbol) } else { draft.expanded.remove(security.symbol) }
            })
        ) {
          VStack(spacing: 8) {
            ForEach(year.rows.filter { $0.symbol == security.symbol }) { row in
              dispositionRow(row, base)
            }
          }.padding(.top, 6)
        } label: {
          securityRow(security, base)
        }
        Divider().overlay(Studio.line)
      }
    }
    let denied = year.rows.filter { ($0.denied ?? 0) > 0 }
    if !denied.isEmpty {
      Surface("Denied losses", trailing: "WHY A LOSS DOESN'T COUNT") {
        ForEach(denied) { row in
          HStack(alignment: .top, spacing: 12) {
            Image(systemName: "exclamationmark.circle").foregroundStyle(Studio.warn)
            Text(explanation(row, base)).font(.system(size: 12)).fixedSize(horizontal: false, vertical: true)
          }
        }
        if denied.contains(where: \.superficial) {
          Text(
            "A superficial loss is added to the cost base of the shares you bought back in taxable accounts, so it lowers your gain when you sell them. Shares bought back in a TFSA, RRSP, or FHSA don't get it, and the loss is lost."
          ).font(.system(size: 11)).foregroundStyle(Studio.muted).fixedSize(horizontal: false, vertical: true)
        }
      }
    }
  }

  private var securityHeader: some View {
    HStack {
      Text("SECURITY").frame(maxWidth: .infinity, alignment: .leading)
      Text("SALES").frame(width: 50, alignment: .trailing)
      Text("PROCEEDS").frame(width: 115, alignment: .trailing)
      Text("COST BASE").frame(width: 115, alignment: .trailing)
      Text("DENIED").frame(width: 95, alignment: .trailing)
      Text("GAIN / LOSS").frame(width: 115, alignment: .trailing)
    }.font(.system(size: 9, weight: .medium)).tracking(1.1).foregroundStyle(Studio.muted)
      .padding(.leading, 20)
  }

  private func securityRow(_ s: TaxSecurity, _ base: String) -> some View {
    HStack {
      HStack(spacing: 6) {
        Text(s.symbol).font(.system(size: 13, weight: .medium))
        if s.missingFx > 0 {
          Image(systemName: "exclamationmark.triangle").foregroundStyle(Studio.warn)
            .help("Missing an exchange rate; left out of the totals")
        }
      }.frame(maxWidth: .infinity, alignment: .leading)
      Text("\(s.dispositions)").foregroundStyle(Studio.muted).frame(width: 50, alignment: .trailing)
      Text(Format.money(s.proceeds, base, privacy: privacy)).frame(width: 115, alignment: .trailing)
      Text(Format.money(s.acb, base, privacy: privacy)).foregroundStyle(Studio.muted)
        .frame(width: 115, alignment: .trailing)
      Text(s.denied > 0 ? Format.money(s.denied, base, privacy: privacy) : "—")
        .foregroundStyle(s.denied > 0 ? Studio.warn : Studio.muted).frame(width: 95, alignment: .trailing)
      Text(Format.money(s.netGain, base, privacy: privacy, sign: true)).foregroundStyle(Studio.trend(s.netGain))
        .frame(width: 115, alignment: .trailing)
    }.font(.system(size: 12)).monospacedDigit().padding(.vertical, 4)
  }

  private func dispositionRow(_ r: TaxDisposition, _ base: String) -> some View {
    HStack(alignment: .firstTextBaseline) {
      VStack(alignment: .leading, spacing: 3) {
        Text("\(r.date) · \(r.accountLabel)").font(.system(size: 11, weight: .medium))
        Text(detail(r)).font(.system(size: 10)).foregroundStyle(Studio.muted)
      }.frame(maxWidth: .infinity, alignment: .leading)
      Text(Format.money(r.proceeds, base, privacy: privacy)).frame(width: 115, alignment: .trailing)
      Text(Format.money(r.acb, base, privacy: privacy)).foregroundStyle(Studio.muted)
        .frame(width: 115, alignment: .trailing)
      Text((r.denied ?? 0) > 0 ? Format.money(r.denied, base, privacy: privacy) : "—")
        .foregroundStyle((r.denied ?? 0) > 0 ? Studio.warn : Studio.muted).frame(width: 95, alignment: .trailing)
      Text(Format.money(r.allowedGain, base, privacy: privacy, sign: true))
        .foregroundStyle(r.complete ? Studio.trend(r.allowedGain) : Studio.muted)
        .frame(width: 115, alignment: .trailing)
    }.font(.system(size: 11)).monospacedDigit().padding(.leading, 20)
  }

  /// Units, trading currency and rate, and any note: "20 units · USD at 1.3604 · superficial".
  private func detail(_ r: TaxDisposition) -> String {
    var parts: [String] = [r.kindLabel]
    if r.quantity > 0 { parts.append(privacy ? "\(Format.mask) units" : "\(units(r.quantity)) units") }
    if r.currency != model.tax?.baseCurrency {
      parts.append(r.fx.map { "\(r.currency) at \(String(format: "%.4f", $0))" } ?? "\(r.currency), no exchange rate")
    }
    if !r.note.isEmpty && r.complete { parts.append(r.note) }
    return parts.joined(separator: " · ")
  }

  private func explanation(_ r: TaxDisposition, _ base: String) -> String {
    let denied = Format.money(r.denied, base, privacy: privacy)
    let account = r.archived ? "an archived account" : r.accountLabel
    if r.deniedReason == "registered" {
      return
        "\(r.date) · \(r.symbol): moved from \(account) into a registered account at a loss. The \(denied) loss is never allowed."
    }
    let loss = Format.money(r.gain.map { -$0 }, base, privacy: privacy)
    let counts =
      privacy
      ? ""
      : " You sold \(units(r.quantity)), bought \(units(r.acquiredInWindow)) within 30 days before or after, and held \(units(r.heldAfterWindow)) 30 days later."
    let open = r.windowOpen ? " The 30 days aren't over yet, so this can still change." : ""
    return "\(r.date) · \(r.symbol): \(denied) of a \(loss) loss is superficial.\(counts)\(open)"
  }

  @ViewBuilder private func roomSurface(_ tax: TaxPayload) -> some View {
    Surface("Contribution room", trailing: "IN CAD · FROM THE ROOM YOU ENTERED") {
      if tax.room.isEmpty {
        Text("Enter your TFSA, RRSP, or FHSA room in Accounts to see what's left.").foregroundStyle(Studio.muted)
      }
      ForEach(tax.room) { r in
        HStack(alignment: .top) {
          VStack(alignment: .leading, spacing: 4) {
            Text(r.accountType).font(.system(size: 13, weight: .medium))
            Text(roomWorking(r)).font(.system(size: 11)).foregroundStyle(Studio.muted)
              .fixedSize(horizontal: false, vertical: true)
          }
          Spacer()
          Text(Format.money(r.remaining, "CAD", privacy: privacy)).foregroundStyle(Studio.trend(r.remaining))
            .font(.system(size: 15, weight: .medium)).monospacedDigit()
        }
      }
      if !tax.room.isEmpty {
        Text("Confirm the figures against CRA My Account before contributing.").font(.system(size: 11))
          .foregroundStyle(Studio.muted)
      }
    }
  }

  /// "7,000.00 on January 1, 2025 + 7,000.00 new room − 2,000.00 contributed"
  private func roomWorking(_ r: ContributionRoom) -> String {
    func money(_ v: Double) -> String { Format.money(v, "CAD", privacy: privacy) }
    var text = "\(money(r.startingRoom)) on January 1, \(String(r.asOfYear))"
    if let v = r.newLimits, v > 0 { text += " + \(money(v)) new room" }
    if let v = r.withdrawalsAddedBack, v > 0 { text += " + \(money(v)) withdrawals added back" }
    if let v = r.contributions, v > 0 { text += " − \(money(v)) contributed" }
    if let v = r.forfeited, v > 0.005 { text += " − \(money(v)) above the FHSA limits" }
    return text
  }

  private func units(_ value: Double) -> String { NumberInput.editable(value) }
  private func percent(_ rate: Double) -> String { rate.formatted(.percent.precision(.fractionLength(0...2))) }
}

private final class TaxWorkspaceDraft: ObservableObject {
  /// nil shows the newest year.
  @Published var year: Int?
  @Published var expanded: Set<String> = []
}

private struct AutomationWorkspace: View {
  @ObservedObject var model: StatusModel
  var body: some View {
    ScrollView {
      VStack(spacing: 20) {
        Surface("Your portfolio, kept current", trailing: "WHILE MARKETPULSE IS RUNNING") {
          automationRow(
            "arrow.clockwise", "Quote refresh",
            "Every \(model.refreshSeconds) seconds. Cached quotes remain available offline.")
          automationRow(
            "chart.xyaxis.line", "Daily snapshots",
            "Fresh, complete valuations are saved automatically. Latest: \(model.desktop?.automation.snapshotDate ?? "No snapshot yet")."
          )
          automationRow(
            "bell", "Price alerts",
            "Checked each refresh, including symbols outside your watchlist. Alerts re-arm when the condition clears."
          )
          automationRow(
            "externaldrive.badge.checkmark", "Daily safety backup",
            model.desktop?.automation.backup
              ?? "A backup is created once your ledger contains transactions.")
          HStack {
            Button("Refresh now") { model.refresh() }.disabled(model.loading || model.saving)
            Button("Back up now") {
              Task { await model.perform(["backup", "now"], success: "Safety backup created") }
            }.disabled(!model.canEdit)
          }
        }
        BackupsPanel(model: model)
        Surface("Preferences") {
          automationRow(
            "gearshape", "Refresh interval, launch at login, and more",
            "Change how often quotes refresh, whether MarketPulse opens when you log in, its appearance, and your portfolio's defaults in Settings."
          )
          Button("Open Settings…") { model.showSettingsWindow() }
          Text(
            "Closing the portfolio window keeps the menu bar and automation running. Quitting the app stops them. For unattended runs, use marketpulse automation run --once with launchd or cron."
          ).font(.system(size: 11)).foregroundStyle(Studio.muted).fixedSize(
            horizontal: false, vertical: true)
        }
        Surface("About MarketPulse") {
          aboutRow("App", appVersion)
          aboutRow(
            "Backend",
            model.desktop?.backend.map { "MarketPulse \($0.version) · Python \($0.python)" }
              ?? "Version unavailable until the first refresh")
          aboutRow("Runs", CLI.resolved.source.rawValue)
          Text(CLI.path).font(.system(size: 11, design: .monospaced)).foregroundStyle(Studio.muted)
            .textSelection(.enabled).fixedSize(horizontal: false, vertical: true)
        }
        if let errors = model.desktop?.automation.errors, !errors.isEmpty {
          Surface("Needs attention") {
            ForEach(errors, id: \.self) {
              Text($0).foregroundStyle(Studio.red).textSelection(.enabled)
            }
          }
        }
        if let errors = model.desktop?.automation.quoteErrors, !errors.isEmpty {
          Surface("Quotes unavailable") {
            ForEach(errors, id: \.self) {
              Text($0).foregroundStyle(Studio.warn).textSelection(.enabled)
            }
          }
        }
        if let warnings = model.desktop?.warnings, !warnings.isEmpty {
          Surface("Ledger checks") {
            ForEach(warnings, id: \.self) {
              Text($0).foregroundStyle(Studio.warn).textSelection(.enabled)
            }
          }
        }
      }.padding(.horizontal, 30).padding(.bottom, 24)
    }
  }
  private var appVersion: String {
    Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? "Development build"
  }
  private func aboutRow(_ title: String, _ value: String) -> some View {
    HStack {
      Text(title).font(.system(size: 13, weight: .medium))
      Spacer()
      Text(value).font(.system(size: 12)).foregroundStyle(Studio.muted).textSelection(.enabled)
    }
  }
  private func automationRow(_ icon: String, _ title: String, _ detail: String) -> some View {
    HStack(alignment: .top, spacing: 14) {
      Image(systemName: icon).foregroundStyle(Studio.mint).frame(width: 24)
      VStack(alignment: .leading, spacing: 6) {
        Text(title).font(.system(size: 13, weight: .medium))
        Text(detail).font(.system(size: 11)).foregroundStyle(Studio.muted).fixedSize(
          horizontal: false, vertical: true)
      }
      Spacer()
    }
  }
}

/// The backups folder, with a confirmed Restore for each backup.
private struct BackupsPanel: View {
  @ObservedObject var model: StatusModel
  @StateObject private var draft = BackupsPanelDraft()
  private static let collapsedCount = 6

  var body: some View {
    let backups = model.desktop?.storage?.backups ?? []
    let folder = model.desktop?.storage?.backupDir
    Surface("Backups", trailing: "KEPT ON THIS MAC") {
      if model.demo {
        Text("The demo has no backups. Your own portfolio's backups appear here.")
          .foregroundStyle(Studio.muted)
      } else if backups.isEmpty {
        Text(
          folder == nil
            ? "Backups appear here after the next refresh."
            : "No backups yet. One is made each day once your portfolio has transactions, and before every import."
        ).foregroundStyle(Studio.muted)
      }
      ForEach(draft.showAll ? backups : Array(backups.prefix(Self.collapsedCount))) { backup in
        HStack(spacing: 14) {
          Image(systemName: "externaldrive").foregroundStyle(Studio.mint).frame(width: 24)
          VStack(alignment: .leading, spacing: 4) {
            Text(backup.when).font(.system(size: 13, weight: .medium))
            Text(
              "\(backup.reasonLabel) · \(ByteCountFormatter.string(fromByteCount: Int64(backup.size), countStyle: .file))"
            ).font(.system(size: 11)).foregroundStyle(Studio.muted)
          }
          Spacer()
          Button {
            if let folder { reveal(URL(fileURLWithPath: folder).appendingPathComponent(backup.name)) }
          } label: {
            Image(systemName: "magnifyingglass")
          }.buttonStyle(.plain).help("Show \(backup.name) in Finder")
          Button("Restore…") { draft.pending = backup }.disabled(!model.canEdit)
        }
      }
      HStack {
        if backups.count > Self.collapsedCount {
          Button(draft.showAll ? "Show fewer" : "Show all \(backups.count)") { draft.showAll.toggle() }
        }
        Button("Show in Finder") {
          if let folder { NSWorkspace.shared.open(URL(fileURLWithPath: folder)) }
        }.disabled(folder.map { !FileManager.default.fileExists(atPath: $0) } ?? true)
      }
      Text(
        "Restoring replaces your portfolio with the backup. Your current portfolio is backed up first, so a restore can be undone by restoring that backup. Settings aren't part of a backup and don't change."
      ).font(.system(size: 11)).foregroundStyle(Studio.muted).fixedSize(
        horizontal: false, vertical: true)
    }
    .confirmationDialog(
      draft.pending.map { "Restore the backup from \($0.when)?" } ?? "Restore this backup?",
      isPresented: Binding(get: { draft.pending != nil }, set: { if !$0 { draft.pending = nil } }),
      presenting: draft.pending
    ) { backup in
      Button("Restore", role: .destructive) {
        Task { await model.restoreBackup(backup) }
      }
      Button("Cancel", role: .cancel) {}
    } message: { backup in
      Text(
        "Your portfolio will be replaced with this backup (\(backup.reasonLabel.lowercased())). Anything recorded after \(backup.when) will no longer appear. Your current portfolio is saved as a new backup first, so you can undo this."
      )
    }
  }

  private func reveal(_ url: URL) {
    NSWorkspace.shared.activateFileViewerSelecting([url])
  }
}

private final class BackupsPanelDraft: ObservableObject {
  @Published var pending: BackupInfo?
  @Published var showAll = false
}

private final class PortfolioWindowDraft: ObservableObject {
  @Published var sheet: DesktopSheet?
  /// The entry the `.editTransaction` sheet changes.
  @Published var editing: DesktopTransaction?
  /// The account the `.editAccount` sheet changes.
  @Published var editingAccount: DesktopAccount?
  /// The type the `.room` sheet opens on.
  @Published var roomType = "TFSA"
  /// The symbol the `.valuation` and `.assetClass` sheets change.
  @Published var assetSymbol = ""
  @Published var section: Workspace? = .overview
  @Published var search = ""
  @Published var accountFilter = 0
}

private final class OverviewWorkspaceDraft: ObservableObject {
  @Published var period = 180
}

private final class HoldingsWorkspaceDraft: ObservableObject {
  @Published var sortByValue = true
  @Published var selection: String?
}

private final class WatchlistWorkspaceDraft: ObservableObject {
  @Published var symbol = ""
}
