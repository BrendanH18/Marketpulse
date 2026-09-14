import Charts
import SwiftUI

@main
struct MarketPulseBarApp: App {
    @StateObject private var model = StatusModel()

    var body: some Scene {
        MenuBarExtra {
            PopoverView(model: model)
        } label: {
            HStack(spacing: 4) {
                Image(systemName: "waveform.path.ecg")
                Text(model.menuTitle).monospacedDigit()
            }
        }
        .menuBarExtraStyle(.window)
    }
}

// MARK: - Popover

struct PopoverView: View {
    @ObservedObject var model: StatusModel

    var body: some View {
        let p = model.palette
        VStack(alignment: .leading, spacing: 12) {
            TopBar(model: model, palette: p)
            if model.showSettings {
                SettingsPanel(model: model, palette: p)
            } else if let status = model.status {
                Dashboard(status: status, palette: p)
            } else if let error = model.errorMessage {
                Card(title: "can't reach marketpulse", palette: p) {
                    Text(error).foregroundStyle(p.down).fixedSize(horizontal: false, vertical: true)
                    Text("Run `marketpulse menubar install` again from a terminal.").foregroundStyle(p.muted)
                }
            } else {
                HStack { Spacer(); ProgressView().controlSize(.small); Spacer() }.padding(24)
            }
            ActionBar(model: model, palette: p)
        }
        .padding(14)
        .frame(width: 380)
        .background(p.background)
        .foregroundStyle(p.foreground)
        .font(.system(size: 12, design: .monospaced))
        .environment(\.colorScheme, p.dark ? .dark : .light)
        .onAppear { model.refreshIfStale() }
    }
}

struct TopBar: View {
    @ObservedObject var model: StatusModel
    let palette: Palette

    var body: some View {
        HStack(spacing: 8) {
            Text("MARKETPULSE").font(.system(size: 10, weight: .bold, design: .monospaced)).tracking(2).foregroundStyle(palette.accent)
            if let state = model.status?.marketState, !state.isEmpty {
                MarketDot(state: state, palette: palette)
            }
            Spacer()
            if model.loading {
                ProgressView().controlSize(.mini)
            } else if let updated = model.lastUpdated {
                Text(updated, style: .time).foregroundStyle(palette.muted).font(.system(size: 10, design: .monospaced))
            }
        }
    }
}

struct MarketDot: View {
    let state: String
    let palette: Palette

    var body: some View {
        let (label, color): (String, Color) = switch state {
        case "REGULAR": ("open", palette.up)
        case "PRE": ("pre", palette.accent)
        case "POST": ("after hours", palette.accent)
        default: ("closed", palette.muted)
        }
        HStack(spacing: 4) {
            Circle().fill(color).frame(width: 6, height: 6)
            Text(label).foregroundStyle(palette.muted).font(.system(size: 10, design: .monospaced))
        }
    }
}

struct Dashboard: View {
    let status: StatusPayload
    let palette: Palette

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            VStack(alignment: .leading, spacing: 4) {
                Text("NET WORTH").font(.system(size: 10, design: .monospaced)).foregroundStyle(palette.muted)
                Text(Format.money(status.netWorth, status.base, privacy: status.privacy))
                    .font(.system(size: 28, weight: .semibold, design: .monospaced))
                    .monospacedDigit()
                    .foregroundStyle(palette.foreground)
                HStack(spacing: 8) {
                    Chip(text: "\(Format.arrow(status.dayChange)) \(Format.money(status.dayChange, status.base, privacy: status.privacy, decimals: 0, sign: true))  \(Format.pct(status.dayChangePct))", color: palette.trend(status.dayChange))
                    Text("today").foregroundStyle(palette.muted)
                    if status.stale {
                        Text("◌ offline").foregroundStyle(palette.down)
                    }
                }
            }

            if status.history.count > 1 {
                HistoryChart(points: status.history, palette: palette)
            }

            HStack(spacing: 10) {
                Stat(label: "UNREALIZED", value: status.privacy ? Format.pct(status.unrealizedPct) : Format.money(status.unrealized, status.base, privacy: false, decimals: 0, sign: true), color: palette.trend(status.unrealized), palette: palette)
                Stat(label: "INCOME YTD", value: Format.money(status.incomeYtd, status.base, privacy: status.privacy, decimals: 0), color: palette.up, palette: palette)
            }

            if !status.accounts.isEmpty {
                Card(title: "accounts", palette: palette) {
                    ForEach(status.accounts) { account in
                        HStack {
                            Text(account.name).lineLimit(1)
                            Text(account.type).foregroundStyle(palette.muted).font(.system(size: 10, design: .monospaced))
                            Spacer()
                            Text(Format.money(account.value, status.base, privacy: status.privacy, decimals: 0)).monospacedDigit()
                            Text(Format.pct(account.dayChangePct)).foregroundStyle(palette.trend(account.dayChangePct)).frame(width: 64, alignment: .trailing).monospacedDigit()
                        }
                    }
                }
            }

            if !status.movers.isEmpty {
                Card(title: "movers", palette: palette) {
                    ForEach(status.movers) { mover in
                        HStack {
                            Text(mover.symbol).fontWeight(.semibold)
                            Text(mover.name).foregroundStyle(palette.muted).lineLimit(1)
                            Spacer()
                            Text("\(Format.arrow(mover.changePct)) \(Format.pct(mover.changePct))").foregroundStyle(palette.trend(mover.changePct)).monospacedDigit()
                        }
                    }
                }
            }

            if !status.watchlist.isEmpty {
                Card(title: "watchlist", palette: palette) {
                    ForEach(status.watchlist.prefix(8)) { row in
                        HStack(spacing: 8) {
                            Text(row.symbol).fontWeight(.semibold).frame(width: 72, alignment: .leading).lineLimit(1)
                            Sparkline(values: row.spark, color: palette.trend(row.changePct)).frame(width: 90, height: 16)
                            Spacer()
                            Text(Format.price(row.price)).monospacedDigit()
                            Text(Format.pct(row.changePct)).foregroundStyle(palette.trend(row.changePct)).frame(width: 64, alignment: .trailing).monospacedDigit()
                        }
                    }
                }
            }

            if !status.alerts.isEmpty {
                Card(title: "alerts", palette: palette) {
                    ForEach(status.alerts) { alert in
                        HStack {
                            Image(systemName: alert.triggered ? "bell.badge.fill" : "bell").foregroundStyle(alert.triggered ? palette.accent : palette.muted)
                            Text(alert.summary)
                            Spacer()
                        }
                    }
                }
            }

            ForEach(status.errors, id: \.self) { error in
                Text("! \(error)").foregroundStyle(palette.muted).font(.system(size: 10, design: .monospaced)).lineLimit(2)
            }
        }
    }
}

struct HistoryChart: View {
    let points: [HistoryPoint]
    let palette: Palette

    var body: some View {
        let values = points.map(\.value)
        let lo = values.min() ?? 0
        let hi = values.max() ?? 1
        let pad = max((hi - lo) * 0.1, 1)
        let color = palette.trend((values.last ?? 0) - (values.first ?? 0))
        Chart(Array(points.enumerated()), id: \.offset) { index, point in
            AreaMark(x: .value("day", index), yStart: .value("floor", lo - pad), yEnd: .value("value", point.value))
                .foregroundStyle(LinearGradient(colors: [color.opacity(0.35), color.opacity(0.0)], startPoint: .top, endPoint: .bottom))
                .interpolationMethod(.monotone)
            LineMark(x: .value("day", index), y: .value("value", point.value))
                .foregroundStyle(color)
                .lineStyle(StrokeStyle(lineWidth: 1.5))
                .interpolationMethod(.monotone)
        }
        .chartXAxis(.hidden)
        .chartYAxis(.hidden)
        .chartYScale(domain: (lo - pad)...(hi + pad))
        .frame(height: 64)
    }
}

struct Sparkline: View {
    let values: [Double]
    let color: Color

    var body: some View {
        if values.count > 1, let lo = values.min(), let hi = values.max(), hi > lo {
            Chart(Array(values.enumerated()), id: \.offset) { index, value in
                LineMark(x: .value("t", index), y: .value("v", value))
                    .foregroundStyle(color)
                    .lineStyle(StrokeStyle(lineWidth: 1.2))
            }
            .chartXAxis(.hidden)
            .chartYAxis(.hidden)
            .chartYScale(domain: lo...hi)
        } else {
            Rectangle().fill(color.opacity(0.3)).frame(height: 1)
        }
    }
}

// MARK: - Settings

struct SettingsPanel: View {
    @ObservedObject var model: StatusModel
    let palette: Palette

    private let displays = [("day_pct", "Day change %"), ("day_change", "Day change $"), ("net_worth", "Net worth"), ("symbol", "A symbol")]
    private let intervals = [30, 60, 120, 300]

    var body: some View {
        Card(title: "settings", palette: palette) {
            Picker("Menu bar shows", selection: Binding(
                get: { UserDefaults.standard.string(forKey: "menubarDisplay") ?? "day_pct" },
                set: { value in
                    UserDefaults.standard.set(value, forKey: "menubarDisplay")
                    model.setConfig("menubar_display", value)
                }
            )) {
                ForEach(displays, id: \.0) { Text($0.1).tag($0.0) }
            }
            HStack {
                TextField("Symbol for menu bar (e.g. XEQT.TO)", text: $model.symbolDraft)
                    .textFieldStyle(.roundedBorder)
                    .onSubmit { model.setConfig("menubar_symbol", model.symbolDraft.uppercased()) }
                Button("Set") { model.setConfig("menubar_symbol", model.symbolDraft.uppercased()) }
            }
            Picker("Refresh every", selection: $model.refreshSeconds) {
                ForEach(intervals, id: \.self) { Text($0 < 60 ? "\($0)s" : "\($0 / 60)m").tag($0) }
            }
            Picker("Open TUI in", selection: $model.terminal) {
                ForEach(TerminalLauncher.choices, id: \.self) { Text($0.capitalized).tag($0) }
            }
            Toggle("⌥⌘M opens MarketPulse", isOn: $model.hotKeyEnabled)
            Toggle("Launch at login", isOn: Binding(
                get: { model.loginEnabled },
                set: { on in
                    do {
                        try LoginItem.set(on)
                        model.loginError = nil
                    } catch {
                        model.loginError = error.localizedDescription
                    }
                    model.loginEnabled = LoginItem.enabled
                }
            ))
            if let loginError = model.loginError {
                Text(loginError).foregroundStyle(palette.down).font(.system(size: 10, design: .monospaced))
            }
            Text("Theme follows `marketpulse theme set …`").foregroundStyle(palette.muted).font(.system(size: 10, design: .monospaced))
        }
        .onAppear { model.loginEnabled = LoginItem.enabled }
    }
}

/// Hover tracking without @State (the command-line toolchain lacks SwiftUI's macro plugins).
final class HoverState: ObservableObject {
    @Published var on = false
}

// MARK: - Building blocks

struct ActionBar: View {
    @ObservedObject var model: StatusModel
    let palette: Palette

    var body: some View {
        HStack(spacing: 6) {
            BarButton(symbol: "terminal", label: "Open", hint: "⌥⌘M", palette: palette) { model.openTUI() }
            BarButton(symbol: "arrow.clockwise", label: nil, hint: nil, palette: palette) { model.refresh() }
            BarButton(symbol: (model.status?.privacy ?? false) ? "eye.slash" : "eye", label: nil, hint: nil, palette: palette) { model.togglePrivacy() }
            BarButton(symbol: model.showSettings ? "xmark" : "gearshape", label: nil, hint: nil, palette: palette) { model.showSettings.toggle() }
            Spacer()
            BarButton(symbol: "power", label: nil, hint: nil, palette: palette) { NSApplication.shared.terminate(nil) }
        }
    }
}

struct BarButton: View {
    let symbol: String
    let label: String?
    let hint: String?
    let palette: Palette
    let action: () -> Void
    @StateObject private var hover = HoverState()

    var body: some View {
        Button(action: action) {
            HStack(spacing: 5) {
                Image(systemName: symbol)
                if let label { Text(label) }
                if let hint { Text(hint).foregroundStyle(palette.muted).font(.system(size: 10, design: .monospaced)) }
            }
            .padding(.horizontal, 8)
            .padding(.vertical, 5)
            .background(RoundedRectangle(cornerRadius: 4).fill(hover.on ? palette.accent.opacity(0.18) : palette.panel))
            .overlay(RoundedRectangle(cornerRadius: 4).stroke(hover.on ? palette.accent : palette.border, lineWidth: 1))
        }
        .buttonStyle(.plain)
        .onHover { hover.on = $0 }
    }
}

struct Card<Content: View>: View {
    let title: String
    let palette: Palette
    @ViewBuilder let content: Content

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(title).font(.system(size: 10, weight: .semibold, design: .monospaced)).foregroundStyle(palette.accent)
            content
        }
        .padding(10)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(RoundedRectangle(cornerRadius: 4).fill(palette.panel))
        .overlay(RoundedRectangle(cornerRadius: 4).stroke(palette.border, lineWidth: 1))
    }
}

struct Chip: View {
    let text: String
    let color: Color

    var body: some View {
        Text(text)
            .monospacedDigit()
            .foregroundStyle(color)
            .padding(.horizontal, 7)
            .padding(.vertical, 3)
            .background(RoundedRectangle(cornerRadius: 3).fill(color.opacity(0.14)))
    }
}

struct Stat: View {
    let label: String
    let value: String
    let color: Color
    let palette: Palette

    var body: some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(label).font(.system(size: 9, design: .monospaced)).foregroundStyle(palette.muted)
            Text(value).foregroundStyle(color).monospacedDigit()
        }
        .padding(8)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(RoundedRectangle(cornerRadius: 4).fill(palette.panel))
        .overlay(RoundedRectangle(cornerRadius: 4).stroke(palette.border, lineWidth: 1))
    }
}
