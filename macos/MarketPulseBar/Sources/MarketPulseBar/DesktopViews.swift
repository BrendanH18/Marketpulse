import AppKit
import Charts
import SwiftUI

private enum Studio {
  static let background = Color(hex: "#101619")
  static let panel = Color(hex: "#171f23")
  static let line = Color.white.opacity(0.08)
  static let text = Color(hex: "#edf2f2")
  static let muted = Color(hex: "#8d9ba3")
  static let mint = Color(hex: "#9cdbc5")
  static let red = Color(hex: "#f09696")
  static let colors = [
    mint, Color(hex: "#89afd3"), Color(hex: "#c7bae9"), Color(hex: "#dec795"),
    Color(hex: "#83969d"),
  ]
  static func trend(_ value: Double?) -> Color { (value ?? 0) < 0 ? red : mint }
}

enum Workspace: String, CaseIterable, Identifiable {
  case overview = "Overview"
  case holdings = "Holdings"
  case activity = "Activity"
  case accounts = "Accounts"
  case watchlist = "Watchlist"
  case income = "Income"
  case automation = "Automation"
  var id: String { rawValue }
  var icon: String {
    switch self {
    case .overview: return "square.grid.2x2"
    case .holdings: return "chart.pie"
    case .activity: return "arrow.left.arrow.right"
    case .accounts: return "building.columns"
    case .watchlist: return "star"
    case .income: return "arrow.down.to.line"
    case .automation: return "bolt"
    }
  }
  var subtitle: String {
    switch self {
    case .overview: return "A little perspective on your portfolio."
    case .holdings: return "Every position, in one place."
    case .activity: return "The ledger behind your portfolio."
    case .accounts: return "Your accounts. Your bigger picture."
    case .watchlist: return "Keep an eye on what comes next."
    case .income: return "Distributions and interest you've recorded."
    case .automation: return "The small routines that keep things up to date."
    }
  }
}

enum DesktopSheet: String, Identifiable {
  case transaction, account, alert
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
        if let payload = model.desktop {
          if payload.demo {
            notice(
              "Demo portfolio · Fictional data · Read-only", icon: "sparkles", color: Studio.mint)
          }
          if payload.status.stale {
            notice(
              "Cached quotes are in use. Values may be out of date.", icon: "wifi.exclamationmark",
              color: .orange)
          }
          if !payload.warnings.isEmpty {
            notice(
              payload.warnings.joined(separator: " · "), icon: "exclamationmark.circle",
              color: .orange)
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
    .preferredColorScheme(.dark)
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
    .sheet(item: $draft.sheet) { item in
      switch item {
      case .transaction: TransactionSheet(model: model)
      case .account: AccountSheet(model: model)
      case .alert: AlertSheet(model: model)
      }
    }
    .sheet(isPresented: $model.showImport, onDismiss: { model.closeImport() }) {
      ImportSheet(model: model)
    }
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
        newTransaction: { draft.sheet = .transaction }, canEdit: model.canEdit)
    case .holdings:
      HoldingsWorkspace(payload: p, search: draft.search, accountFilter: $draft.accountFilter)
    case .activity:
      ActivityWorkspace(payload: p, search: draft.search, accountFilter: $draft.accountFilter)
    case .accounts:
      AccountsWorkspace(payload: p, canEdit: model.canEdit, add: { draft.sheet = .account })
    case .watchlist: WatchlistWorkspace(model: model, addAlert: { draft.sheet = .alert })
    case .income: IncomeWorkspace(payload: p)
    case .automation: AutomationWorkspace(model: model)
    }
  }

  private var footer: some View {
    HStack(spacing: 8) {
      Circle().fill(model.errorMessage != nil ? Studio.red : Studio.mint).frame(width: 5, height: 5)
      Text(model.loading ? "Refreshing portfolio…" : model.saving ? "Saving…" : "Local ledger")
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
              Text(t.type.capitalized).font(.system(size: 10, weight: .medium)).foregroundStyle(
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
  private var rows: [DesktopPosition] {
    payload.positions.filter {
      (accountFilter == 0 || $0.accountId == accountFilter)
        && (search.isEmpty
          || "\($0.symbol) \($0.name) \($0.account)".localizedCaseInsensitiveContains(search))
    }
    .sorted { draft.sortByValue ? ($0.value ?? 0) > ($1.value ?? 0) : $0.symbol < $1.symbol }
  }
  var body: some View {
    VStack(alignment: .leading, spacing: 16) {
      HStack {
        AccountFilter(accounts: payload.accounts, selected: $accountFilter)
        Spacer()
        Button(draft.sortByValue ? "Sort: value ↓" : "Sort: symbol A–Z") {
          draft.sortByValue.toggle()
        }.buttonStyle(.bordered)
        Text("\(rows.count) positions").foregroundStyle(Studio.muted)
      }.font(.system(size: 11)).padding(.horizontal, 30)
      Table(rows) {
        TableColumn("Asset") { p in
          VStack(alignment: .leading, spacing: 3) {
            Text(p.symbol).fontWeight(.medium)
            Text(p.name).font(.system(size: 10)).foregroundStyle(Studio.muted).lineLimit(1)
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

private struct ActivityWorkspace: View {
  let payload: DesktopPayload
  let search: String
  @Binding var accountFilter: Int
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
      Table(rows) {
        TableColumn("Date", value: \.date).width(100)
        TableColumn("Type") { t in Text(t.type.capitalized).foregroundStyle(Studio.mint) }.width(90)
        TableColumn("Symbol", value: \.symbol).width(85)
        TableColumn("Account") { t in
          Text(
            t.targetAccount.isEmpty
              ? accountName(t.accountId, payload)
              : "\(accountName(t.accountId, payload)) → \(t.targetAccount)")
        }.width(min: 130, ideal: 160)
        TableColumn("Amount") { t in
          Text(activityAmount(t, privacy: payload.status.privacy)).monospacedDigit()
            .foregroundStyle(activityColor(t))
        }.width(120)
        TableColumn("Note", value: \.note)
      }.scrollContentBackground(.hidden).alternatingRowBackgrounds(.disabled)
        .overlay {
          if rows.isEmpty {
            ContentUnavailableView("No matching activity", systemImage: "arrow.left.arrow.right")
          }
        }
    }
  }
}

private struct AccountsWorkspace: View {
  let payload: DesktopPayload
  let canEdit: Bool
  let add: () -> Void
  var body: some View {
    ScrollView {
      VStack(spacing: 18) {
        HStack {
          Text("\(payload.accounts.count) active accounts").foregroundStyle(Studio.muted)
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
                  a.trackCash
                    ? "Holdings and cash are tracked" : "Holdings are tracked; cash is excluded"
                ).font(.system(size: 11)).foregroundStyle(Studio.muted)
              }
              Spacer()
              Text(
                Format.money(
                  payload.status.accounts.first { $0.name == a.name }?.value ?? 0,
                  payload.status.base, privacy: payload.status.privacy)
              )
              .font(.system(size: 24, weight: .medium)).monospacedDigit()
            }
          }
        }
        if !payload.room.isEmpty {
          Surface("Contribution room", trailing: "BASED ON YOUR ENTERED LIMITS") {
            ForEach(payload.room) { r in
              HStack {
                Text(r.accountType)
                Spacer()
                Text(
                  Format.money(r.remaining, payload.status.base, privacy: payload.status.privacy)
                ).foregroundStyle(Studio.trend(r.remaining))
              }
            }
            Text(
              "Set starting room with marketpulse accounts room. Confirm limits against your own records."
            ).font(.system(size: 11)).foregroundStyle(Studio.muted)
          }
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
        Surface("Preferences") {
          Picker("Refresh interval", selection: $model.refreshSeconds) {
            ForEach([30, 60, 120, 300], id: \.self) { Text("\($0) seconds").tag($0) }
          }.frame(maxWidth: 400)
          Toggle(
            "Launch at login",
            isOn: Binding(
              get: { model.loginEnabled },
              set: { value in
                do {
                  try LoginItem.set(value)
                  model.loginError = nil
                } catch { model.loginError = error.localizedDescription }
                model.loginEnabled = LoginItem.enabled
              })
          ).disabled(model.demo)
          if let error = model.loginError { Text(error).foregroundStyle(Studio.red) }
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
              Text($0).foregroundStyle(.orange).textSelection(.enabled)
            }
          }
        }
        if let warnings = model.desktop?.warnings, !warnings.isEmpty {
          Surface("Ledger checks") {
            ForEach(warnings, id: \.self) {
              Text($0).foregroundStyle(.orange).textSelection(.enabled)
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

private final class PortfolioWindowDraft: ObservableObject {
  @Published var sheet: DesktopSheet?
  @Published var section: Workspace? = .overview
  @Published var search = ""
  @Published var accountFilter = 0
}

private final class OverviewWorkspaceDraft: ObservableObject {
  @Published var period = 180
}

private final class HoldingsWorkspaceDraft: ObservableObject {
  @Published var sortByValue = true
}

private final class WatchlistWorkspaceDraft: ObservableObject {
  @Published var symbol = ""
}
