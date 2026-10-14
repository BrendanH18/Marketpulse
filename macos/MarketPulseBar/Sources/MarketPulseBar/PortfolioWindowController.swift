import AppKit
import SwiftUI

/// The one portfolio window, on every macOS version. Created on first use and kept for the
/// app's lifetime, so the Dock icon, the menu bar's Portfolio button and relaunching the app
/// all bring back the same window instead of depending on SwiftUI scene restoration.
@MainActor
final class PortfolioWindowController: NSWindowController {
  init(model: StatusModel) {
    let host = NSHostingController(rootView: PortfolioWindow(model: model))
    // NSHostingView alone drops SwiftUI toolbars, which hold refresh, privacy and ⌘N.
    host.sceneBridgingOptions = [.toolbars, .title]
    let window = NSWindow(contentViewController: host)
    window.title = "MarketPulse"
    window.styleMask = [.titled, .closable, .miniaturizable, .resizable, .fullSizeContentView]
    window.appearance = NSAppearance(named: .darkAqua)
    window.isReleasedWhenClosed = false
    window.tabbingMode = .disallowed
    window.setContentSize(NSSize(width: 1200, height: 850))
    window.center()
    // Remember size and position, except in the read-only demo.
    if !model.demo { window.setFrameAutosaveName("MarketPulsePortfolio") }
    super.init(window: window)
  }

  required init?(coder: NSCoder) { nil }

  func present() {
    guard let window else { return }
    if window.isMiniaturized { window.deminiaturize(nil) }
    showWindow(nil)
    window.makeKeyAndOrderFront(nil)
    NSApp.activate()
  }
}

@MainActor
final class AppDelegate: NSObject, NSApplicationDelegate {
  let model = StatusModel()

  func applicationDidFinishLaunching(_ notification: Notification) {
    // Desktop installs open the portfolio at launch; menu bar installs wait to be asked.
    if !model.menuBarOnly { model.showPortfolio() }
  }

  /// A Dock click, or opening the app again while it runs. AppKit only asks when the app
  /// is already running, so login-item launches of the menu bar build are unaffected.
  func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
    model.showPortfolio()
    return false
  }
}
