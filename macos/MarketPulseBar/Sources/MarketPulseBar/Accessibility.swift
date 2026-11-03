import Foundation

/// What VoiceOver says for charts, which otherwise read as a list of unlabelled marks. Each summary
/// names the direction in words, so gains and losses never depend on colour alone.
enum Spoken {
  /// "up 4.20%", "down 1.05%", or "unchanged".
  static func change(_ pct: Double) -> String {
    let size = abs(pct).formatted(.number.precision(.fractionLength(2))) + "%"
    return pct > 0.005 ? "up \(size)" : pct < -0.005 ? "down \(size)" : "unchanged"
  }

  /// "March 4, 2026" from a snapshot's `YYYY-MM-DD`.
  static func day(_ raw: String) -> String {
    guard let date = ISO8601DateFormatter().date(from: raw + "T12:00:00Z") else { return raw }
    // In UTC: noon UTC is already tomorrow in UTC+12 and later.
    let utc = TimeZone(secondsFromGMT: 0) ?? .current
    return date.formatted(Date.FormatStyle(timeZone: utc).month(.wide).day().year())
  }

  /// "March 2026" from an income month's `YYYY-MM`.
  static func month(_ raw: String) -> String {
    guard let date = ISO8601DateFormatter().date(from: raw + "-15T12:00:00Z") else { return raw }
    return date.formatted(.dateTime.month(.wide).year())
  }

  /// The value history: where it started and ended, the change, and the range.
  /// With `amounts` off (the menu bar's privacy mode) only the direction and percentage are spoken.
  static func history(_ points: [HistoryPoint], base: String, amounts: Bool = true) -> String {
    guard let first = points.first, let last = points.last, points.count > 1 else {
      return "Not enough history yet"
    }
    let pct = first.value != 0 ? (last.value - first.value) / abs(first.value) * 100 : 0
    let span = "\(day(first.date)) to \(day(last.date))"
    guard amounts else { return "\(span), \(change(pct))" }
    func money(_ v: Double) -> String { Format.money(v, base, privacy: false, decimals: 0) }
    let values = points.map(\.value)
    return
      "\(money(first.value)) on \(day(first.date)) to \(money(last.value)) on \(day(last.date)), \(change(pct)). "
      + "Low \(money(values.min() ?? 0)), high \(money(values.max() ?? 0))."
  }

  /// Monthly income: the total and the best month.
  static func income(_ months: [HistoryPoint], base: String) -> String {
    let total = months.map(\.value).reduce(0, +)
    guard let best = months.max(by: { $0.value < $1.value }), best.value > 0 else {
      return "No income recorded in these months"
    }
    return
      "\(Format.money(total, base, privacy: false)) over \(months.count) months. "
      + "Highest: \(Format.money(best.value, base, privacy: false)) in \(month(best.date))."
  }
}
