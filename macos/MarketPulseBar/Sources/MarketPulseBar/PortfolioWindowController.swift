import AppKit
import SwiftUI

/// Explicit window presentation for macOS 14, where scene launch suppression is unavailable.
@MainActor
final class PortfolioWindowController: NSWindowController {
  init(model: StatusModel) {
    let window = NSWindow(
      contentRect: NSRect(x: 0, y: 0, width: 1200, height: 850),
      styleMask: [.titled, .closable, .miniaturizable, .resizable],
      backing: .buffered, defer: false)
    window.title = "MarketPulse"
    window.isReleasedWhenClosed = false
    window.contentView = NSHostingView(rootView: PortfolioWindow(model: model))
    window.center()
    super.init(window: window)
  }

  required init?(coder: NSCoder) { nil }
}
