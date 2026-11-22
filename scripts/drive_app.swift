import AppKit
import ApplicationServices

// Drives a running MarketPulse app through the macOS Accessibility API, the way VoiceOver or a
// person would: it finds controls by their visible or accessibility label and presses them.
// scripts/smoke_restore_app.py compiles it with swiftc and runs one command per step:
//
//   drive_app <pid> workspace <name>          choose a workspace from the Workspace menu
//   drive_app <pid> press <label>             press the first enabled control with this label
//   drive_app <pid> press-prefix <label>      ... whose label starts with this text
//   drive_app <pid> wait-enabled <label>      wait until a control with this label is enabled
//   drive_app <pid> wait-text <text>          wait until some text in the app contains <text>
//   drive_app <pid> wait-gone <label>         wait until no control has this label
//
// Each command waits up to 60 seconds. On failure it prints the app's accessibility tree and
// exits 1. The calling process needs the Accessibility permission (CI runners have it).

let timeout: TimeInterval = 60

func attribute(_ element: AXUIElement, _ name: String) -> AnyObject? {
  var value: CFTypeRef?
  guard AXUIElementCopyAttributeValue(element, name as CFString, &value) == .success else {
    return nil
  }
  return value
}

func text(_ element: AXUIElement, _ name: String) -> String? {
  attribute(element, name) as? String
}

func children(_ element: AXUIElement) -> [AXUIElement] {
  attribute(element, kAXChildrenAttribute) as? [AXUIElement] ?? []
}

func labels(_ element: AXUIElement) -> [String] {
  [kAXTitleAttribute, kAXDescriptionAttribute, kAXValueAttribute].compactMap { text(element, $0) }
}

func isEnabled(_ element: AXUIElement) -> Bool {
  (attribute(element, kAXEnabledAttribute) as? Bool) ?? true
}

/// Every element under `root`, breadth first. SwiftUI trees are shallow enough to walk whole.
func everything(under root: AXUIElement) -> [AXUIElement] {
  var found: [AXUIElement] = []
  var queue = [root]
  while !queue.isEmpty && found.count < 20_000 {
    let element = queue.removeFirst()
    found.append(element)
    queue.append(contentsOf: children(element))
  }
  return found
}

/// The open sheet's elements when a sheet is showing, so a press can't reach the window behind it.
func scope(_ app: AXUIElement) -> [AXUIElement] {
  let windows = attribute(app, kAXWindowsAttribute) as? [AXUIElement] ?? []
  for window in windows {
    if let sheet = children(window).first(where: { text($0, kAXRoleAttribute) == kAXSheetRole }) {
      return everything(under: sheet)
    }
  }
  return windows.flatMap { everything(under: $0) }
}

func controls(_ app: AXUIElement, matching match: (String) -> Bool) -> [AXUIElement] {
  scope(app).filter { element in
    let role = text(element, kAXRoleAttribute)
    return role != kAXStaticTextRole && labels(element).contains(where: match)
  }
}

func dump(_ element: AXUIElement, depth: Int = 0) {
  guard depth < 40 else { return }
  let role = text(element, kAXRoleAttribute) ?? "?"
  let shown = labels(element).filter { !$0.isEmpty }.map { "\"\($0)\"" }.joined(separator: " ")
  print(
    String(repeating: "  ", count: depth) + role + (isEnabled(element) ? "" : " (disabled)") + " "
      + shown)
  for child in children(element) { dump(child, depth: depth + 1) }
}

func fail(_ app: AXUIElement, _ message: String) -> Never {
  print("FAIL: \(message)\nAccessibility tree:")
  for window in attribute(app, kAXWindowsAttribute) as? [AXUIElement] ?? [] { dump(window) }
  exit(1)
}

/// Polls `condition` until it returns a value or the timeout passes.
func waitFor<T>(_ app: AXUIElement, _ what: String, _ condition: () -> T?) -> T {
  let deadline = Date().addingTimeInterval(timeout)
  while Date() < deadline {
    if let value = condition() { return value }
    Thread.sleep(forTimeInterval: 0.25)
  }
  fail(app, "Timed out after \(Int(timeout)) s waiting for \(what).")
}

func press(_ app: AXUIElement, _ element: AXUIElement, _ what: String) {
  let result = AXUIElementPerformAction(element, kAXPressAction as CFString)
  if result != .success { fail(app, "Pressing \(what) failed (AXError \(result.rawValue)).") }
  print("Pressed \(what)")
}

let arguments = CommandLine.arguments
guard arguments.count == 4, let pid = pid_t(arguments[1]) else {
  print("usage: drive_app <pid> <command> <argument>")
  exit(2)
}
guard AXIsProcessTrusted() else {
  print("FAIL: this process doesn't have the Accessibility permission.")
  exit(1)
}
let app = AXUIElementCreateApplication(pid)
let command = arguments[2]
let argument = arguments[3]
NSRunningApplication(processIdentifier: pid)?.activate()

switch command {
case "workspace":
  let item = waitFor(app, "the Workspace menu's \(argument) item") { () -> AXUIElement? in
    guard let menuBar = attribute(app, kAXMenuBarAttribute).map({ $0 as! AXUIElement }) else {
      return nil
    }
    let menu = children(menuBar).first { text($0, kAXTitleAttribute) == "Workspace" }
    return menu.flatMap { everything(under: $0).first { text($0, kAXTitleAttribute) == argument } }
  }
  press(app, item, "Workspace › \(argument)")
case "press", "press-prefix":
  let match: (String) -> Bool = command == "press" ? { $0 == argument } : { $0.hasPrefix(argument) }
  let control = waitFor(app, "an enabled \"\(argument)\" control") {
    controls(app, matching: match).first(where: isEnabled)
  }
  press(app, control, "\"\(labels(control).first ?? argument)\"")
case "wait-enabled":
  _ = waitFor(app, "\"\(argument)\" to be enabled") {
    controls(app, matching: { $0 == argument }).first(where: isEnabled)
  }
  print("\"\(argument)\" is enabled")
case "wait-text":
  let found = waitFor(app, "text containing \"\(argument)\"") {
    scope(app).flatMap(labels).first { $0.contains(argument) }
  }
  print("Found: \(found)")
case "wait-gone":
  _ = waitFor(app, "\"\(argument)\" to go away") {
    controls(app, matching: { $0 == argument }).isEmpty ? true : nil
  }
  print("\"\(argument)\" is gone")
default:
  print("unknown command \(command)")
  exit(2)
}
