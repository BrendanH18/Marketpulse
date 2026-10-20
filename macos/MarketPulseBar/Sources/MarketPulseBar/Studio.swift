import AppKit
import SwiftUI

/// The portfolio window's palette. Each colour has a light and a dark value and follows the
/// window's appearance, so Settings › Appearance needs no restart. `tests/test_palette_contrast.py`
/// checks every text colour against both backgrounds; keep the `Color(light:dark:)` form.
enum Studio {
  static let background = Color(light: "#f3f6f6", dark: "#101619")
  static let panel = Color(light: "#ffffff", dark: "#171f23")
  static let line = Color(
    nsColor: dynamic(light: .black.withAlphaComponent(0.1), dark: .white.withAlphaComponent(0.08)))
  static let text = Color(light: "#162125", dark: "#edf2f2")
  static let muted = Color(light: "#56656c", dark: "#8d9ba3")
  static let mint = Color(light: "#17785b", dark: "#9cdbc5")
  static let red = Color(light: "#b42d36", dark: "#f09696")
  /// Cautions (cached quotes, ledger checks). System orange is unreadable on white.
  static let warn = Color(light: "#965200", dark: "#ff9f0a")
  static let colors = [
    mint, Color(light: "#33689e", dark: "#89afd3"), Color(light: "#7158b0", dark: "#c7bae9"),
    Color(light: "#8a670c", dark: "#dec795"), Color(light: "#5d7178", dark: "#83969d"),
  ]
  static func trend(_ value: Double?) -> Color { (value ?? 0) < 0 ? red : mint }

  static func dynamic(light: NSColor, dark: NSColor) -> NSColor {
    NSColor(name: nil) { appearance in
      appearance.bestMatch(from: [.darkAqua, .aqua]) == .darkAqua ? dark : light
    }
  }
}

extension Color {
  init(light: String, dark: String) {
    self.init(nsColor: Studio.dynamic(light: NSColor(Color(hex: light)), dark: NSColor(Color(hex: dark))))
  }
}

/// Settings › Appearance. Stored in the app's own preferences: it's a property of this Mac's app,
/// not of the ledger, so the CLI's config file doesn't carry it.
enum AppAppearance: String, CaseIterable, Identifiable {
  case system, light, dark
  static let key = "appearance"
  var id: String { rawValue }
  var label: String { rawValue.capitalized }

  static var saved: AppAppearance {
    UserDefaults.standard.string(forKey: key).flatMap(AppAppearance.init) ?? .system
  }

  /// Applies to every window, sheet and the Settings window at once.
  func apply() {
    switch self {
    case .system: NSApp.appearance = nil
    case .light: NSApp.appearance = NSAppearance(named: .aqua)
    case .dark: NSApp.appearance = NSAppearance(named: .darkAqua)
    }
  }
}
