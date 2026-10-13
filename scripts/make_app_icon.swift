// Renders the MarketPulse app icon at every macOS size and packs AppIcon.icns.
//
//   swiftc scripts/make_app_icon.swift -o /tmp/make_app_icon
//   /tmp/make_app_icon macos/MarketPulseBar/AppIcon.icns [preview.png]
//
// Drawn in code (AppKit only) so the artwork is reviewable and reproducible.
import AppKit

let mint = NSColor(srgbRed: 0.612, green: 0.859, blue: 0.773, alpha: 1)  // #9cdbc5, the app's accent

/// Draws the icon on a 1024-point canvas (macOS grid: an 824-point rounded square, inset 100).
func drawIcon() {
  let body = NSRect(x: 100, y: 100, width: 824, height: 824)
  let shape = NSBezierPath(roundedRect: body, xRadius: 185, yRadius: 185)

  // Drop shadow, as on system icons.
  NSGraphicsContext.saveGraphicsState()
  let shadow = NSShadow()
  shadow.shadowOffset = NSSize(width: 0, height: -12)
  shadow.shadowBlurRadius = 28
  shadow.shadowColor = NSColor.black.withAlphaComponent(0.35)
  shadow.set()
  NSColor(srgbRed: 0.05, green: 0.08, blue: 0.09, alpha: 1).setFill()
  shape.fill()
  NSGraphicsContext.restoreGraphicsState()

  NSGraphicsContext.saveGraphicsState()
  shape.addClip()
  NSGradient(
    starting: NSColor(srgbRed: 0.137, green: 0.212, blue: 0.231, alpha: 1),  // #23363b
    ending: NSColor(srgbRed: 0.043, green: 0.071, blue: 0.082, alpha: 1)  // #0b1215
  )!.draw(in: body, angle: -90)
  // Soft mint light from the upper left, fading out with no visible edge.
  NSGradient(colors: [mint.withAlphaComponent(0.14), mint.withAlphaComponent(0)])!.draw(
    fromCenter: NSPoint(x: 260, y: 860), radius: 0, toCenter: NSPoint(x: 260, y: 860), radius: 720,
    options: [])

  // Faint chart grid.
  NSColor.white.withAlphaComponent(0.06).setStroke()
  for y in [330.0, 512, 694] {
    let line = NSBezierPath()
    line.move(to: NSPoint(x: 100, y: y))
    line.line(to: NSPoint(x: 924, y: y))
    line.lineWidth = 4
    line.stroke()
  }

  // A heartbeat that becomes a rising trend.
  let points: [NSPoint] = [
    NSPoint(x: 60, y: 452), NSPoint(x: 312, y: 452), NSPoint(x: 362, y: 404),
    NSPoint(x: 432, y: 676), NSPoint(x: 502, y: 300), NSPoint(x: 560, y: 520),
    NSPoint(x: 640, y: 500), NSPoint(x: 722, y: 580), NSPoint(x: 800, y: 628),
  ]
  let pulse = NSBezierPath()
  pulse.move(to: points[0])
  points.dropFirst().forEach { pulse.line(to: $0) }
  pulse.lineJoinStyle = .round
  pulse.lineCapStyle = .round

  NSGraphicsContext.saveGraphicsState()
  let glow = NSShadow()
  glow.shadowBlurRadius = 36
  glow.shadowColor = mint.withAlphaComponent(0.75)
  glow.set()
  mint.setStroke()
  pulse.lineWidth = 38
  pulse.stroke()
  NSGraphicsContext.restoreGraphicsState()

  // The latest value.
  let end = points.last!
  mint.withAlphaComponent(0.22).setFill()
  NSBezierPath(ovalIn: NSRect(x: end.x - 64, y: end.y - 64, width: 128, height: 128)).fill()
  mint.setFill()
  NSBezierPath(ovalIn: NSRect(x: end.x - 38, y: end.y - 38, width: 76, height: 76)).fill()
  NSColor(srgbRed: 0.043, green: 0.071, blue: 0.082, alpha: 1).setFill()
  NSBezierPath(ovalIn: NSRect(x: end.x - 15, y: end.y - 15, width: 30, height: 30)).fill()

  // Hairline edge.
  NSGraphicsContext.restoreGraphicsState()
  NSColor.white.withAlphaComponent(0.10).setStroke()
  let edge = NSBezierPath(roundedRect: body.insetBy(dx: 1.5, dy: 1.5), xRadius: 184, yRadius: 184)
  edge.lineWidth = 3
  edge.stroke()
}

func png(pixels: Int) -> Data {
  let rep = NSBitmapImageRep(
    bitmapDataPlanes: nil, pixelsWide: pixels, pixelsHigh: pixels, bitsPerSample: 8,
    samplesPerPixel: 4, hasAlpha: true, isPlanar: false, colorSpaceName: .deviceRGB,
    bytesPerRow: 0, bitsPerPixel: 0)!
  rep.size = NSSize(width: pixels, height: pixels)
  NSGraphicsContext.saveGraphicsState()
  NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: rep)
  NSGraphicsContext.current!.imageInterpolation = .high
  let scale = CGFloat(pixels) / 1024
  NSAffineTransform().with { $0.scale(by: scale) }.concat()
  drawIcon()
  NSGraphicsContext.restoreGraphicsState()
  return rep.representation(using: .png, properties: [:])!
}

extension NSAffineTransform {
  func with(_ body: (NSAffineTransform) -> Void) -> NSAffineTransform {
    body(self)
    return self
  }
}

let args = CommandLine.arguments
guard args.count >= 2 else {
  FileHandle.standardError.write("usage: make_app_icon OUTPUT.icns [PREVIEW.png]\n".data(using: .utf8)!)
  exit(2)
}
let output = URL(fileURLWithPath: args[1])
let iconset = FileManager.default.temporaryDirectory
  .appendingPathComponent("AppIcon-\(UUID().uuidString).iconset")
try FileManager.default.createDirectory(at: iconset, withIntermediateDirectories: true)
defer { try? FileManager.default.removeItem(at: iconset) }
for points in [16, 32, 128, 256, 512] {
  try png(pixels: points).write(to: iconset.appendingPathComponent("icon_\(points)x\(points).png"))
  try png(pixels: points * 2).write(to: iconset.appendingPathComponent("icon_\(points)x\(points)@2x.png"))
}
if args.count >= 3 { try png(pixels: 1024).write(to: URL(fileURLWithPath: args[2])) }
let iconutil = Process()
iconutil.executableURL = URL(fileURLWithPath: "/usr/bin/iconutil")
iconutil.arguments = ["-c", "icns", iconset.path, "-o", output.path]
try iconutil.run()
iconutil.waitUntilExit()
guard iconutil.terminationStatus == 0 else { exit(iconutil.terminationStatus) }
print("Wrote \(output.path)")
