import Foundation
import SwiftUI

/// Mirrors `marketpulse status --json` (decoded with convertFromSnakeCase).
struct StatusPayload: Decodable {
    let version: Int
    let generatedAt: String
    let title: String
    let base: String
    let privacy: Bool
    let stale: Bool
    let marketState: String
    let netWorth: Double?
    let dayChange: Double?
    let dayChangePct: Double
    let unrealized: Double?
    let unrealizedPct: Double
    let incomeYtd: Double?
    let accounts: [AccountRow]
    let movers: [Mover]
    let watchlist: [WatchRow]
    let history: [HistoryPoint]
    let alerts: [AlertRow]
    let fired: [String]
    let theme: ThemeInfo
    let errors: [String]
}

struct AccountRow: Decodable, Identifiable {
    var id: String { name }
    let name: String
    let type: String
    let value: Double?
    let dayChange: Double?
    let dayChangePct: Double
    let weight: Double
}

struct Mover: Decodable, Identifiable {
    var id: String { symbol }
    let symbol: String
    let name: String
    let price: Double?
    let changePct: Double
    let currency: String
}

struct WatchRow: Decodable, Identifiable {
    var id: String { symbol }
    let symbol: String
    let name: String
    let price: Double
    let changePct: Double
    let currency: String
    let spark: [Double]
}

struct HistoryPoint: Decodable, Identifiable {
    var id: String { date }
    let date: String
    let value: Double
}

struct AlertRow: Decodable, Identifiable {
    var id: String { symbol + summary }
    let symbol: String
    let summary: String
    let triggered: Bool

    enum CodingKeys: String, CodingKey {
        case symbol, triggered
        case summary = "description"
    }
}

struct ThemeInfo: Decodable {
    let name: String
    let dark: Bool
    let accent: String
    let up: String
    let down: String
    let background: String
    let foreground: String
    let muted: String
}

/// Omarchy palette resolved to SwiftUI colors (Tokyo Night until the first payload arrives).
struct Palette {
    let dark: Bool
    let accent: Color
    let up: Color
    let down: Color
    let background: Color
    let foreground: Color
    let muted: Color
    let panel: Color
    let border: Color

    init(_ info: ThemeInfo?) {
        dark = info?.dark ?? true
        accent = Color(hex: info?.accent ?? "#7aa2f7")
        up = Color(hex: info?.up ?? "#9ece6a")
        down = Color(hex: info?.down ?? "#f7768e")
        background = Color(hex: info?.background ?? "#1a1b26")
        foreground = Color(hex: info?.foreground ?? "#a9b1d6")
        muted = Color(hex: info?.muted ?? "#565f89")
        panel = foreground.opacity(0.05)
        border = muted.opacity(0.45)
    }

    func trend(_ value: Double?) -> Color {
        guard let value, value != 0 else { return muted }
        return value > 0 ? up : down
    }
}

extension Color {
    init(hex: String) {
        var s = hex.trimmingCharacters(in: .whitespacesAndNewlines)
        if s.hasPrefix("#") { s.removeFirst() }
        let v = UInt64(s, radix: 16) ?? 0
        self.init(
            .sRGB,
            red: Double((v >> 16) & 0xff) / 255,
            green: Double((v >> 8) & 0xff) / 255,
            blue: Double(v & 0xff) / 255
        )
    }
}

enum Format {
    static let mask = "••••"

    static func money(_ value: Double?, _ currency: String, privacy: Bool, decimals: Int = 2, sign: Bool = false) -> String {
        guard let value else { return "—" }
        if privacy { return mask }
        let f = NumberFormatter()
        f.numberStyle = .currency
        f.currencyCode = currency
        f.maximumFractionDigits = decimals
        f.minimumFractionDigits = decimals
        let body = f.string(from: NSNumber(value: abs(value))) ?? String(format: "%.2f", abs(value))
        let prefix = value < 0 ? "-" : (sign && value > 0 ? "+" : "")
        return prefix + body
    }

    static func pct(_ value: Double) -> String {
        String(format: "%@%.2f%%", value > 0 ? "+" : "", value)
    }

    static func price(_ value: Double?) -> String {
        guard let value else { return "—" }
        return value >= 1 ? String(format: "%.2f", value) : String(format: "%.4f", value)
    }

    static func arrow(_ value: Double?) -> String {
        guard let value, value != 0 else { return "•" }
        return value > 0 ? "▲" : "▼"
    }
}
