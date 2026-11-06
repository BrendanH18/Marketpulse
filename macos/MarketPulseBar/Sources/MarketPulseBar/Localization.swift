import Foundation

/// Localization helpers. SwiftUI views localize string literals by themselves (`Text("Net
/// worth")` looks the literal up in `Localizable.strings`); a `String` built elsewhere has to
/// be localized where it's written, with `String(localized: "…")`. The tables live in
/// `macos/MarketPulseBar/Localization/*.lproj` and are copied into `Contents/Resources` when the
/// app is assembled (`menubar.assemble_app`), so they load from `Bundle.main`, never
/// `Bundle.module`.
enum Loc {
  /// Fixed English text from the engine (tax notes, asset classes, backup reasons), in the
  /// user's language when `Backend.strings` has it, otherwise as sent.
  static func backend(_ text: String) -> String {
    Bundle.main.localizedString(forKey: text, value: text, table: "Backend")
  }

}
